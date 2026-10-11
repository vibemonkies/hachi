"""One prospective symptomatic landmark per labeled episode, after participant splitting."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from hachi.data.clinical import read_table
from hachi.data.clinical.tables import SURVEY_AVAILABILITY_RULE

from .survival import Observation

ENDPOINT = "outcomes-1-sustained-symptom-free-2d"
SCALE = "stanford-phase1-daily-survey-10-symptoms-severity-1-to-5"
FEATURES = ("symptom_count", "max_severity", "severity_sum")


@dataclass(frozen=True)
class Landmark:
    observation: Observation
    cutoff: datetime
    source_scale: str
    paired_wearable_day: bool


def landmarks(
    snapshot: Path,
    subjects: tuple[str, ...],
) -> tuple[list[Landmark], dict[str, int]]:
    """Labels define episode membership/outcomes only; they never enter predictors.

    Restrict reads to an assigned partition; the sealed outer test is not loaded.
    The first observed symptomatic survey is current at the next floating-local
    midnight. Recovery day indices count future days after that survey day.
    """
    if not subjects:
        return [], {}
    recovery = read_table(snapshot, "recovery", subjects).to_pylist()
    episodes = read_table(snapshot, "episodes", subjects).to_pylist()
    surveys = read_table(snapshot, "surveys", subjects).to_pylist()
    scores = read_table(snapshot, "symptom_scores", subjects).to_pylist()
    wearable = read_table(snapshot, "wearable_days", subjects).to_pylist()
    return build_landmarks(recovery, episodes, surveys, scores, wearable)


def build_landmarks(
    recovery: list[dict],
    episodes: list[dict],
    surveys: list[dict],
    scores: list[dict],
    wearable: list[dict],
) -> tuple[list[Landmark], dict[str, int]]:
    by_subject: dict[str, list[date]] = defaultdict(list)
    for row in episodes:
        by_subject[row["subject_id"]].append(row["onset_first_day"])
    symptom_days: dict[str, list[date]] = defaultdict(list)
    for row in surveys:
        if row["state"] == "symptomatic":
            symptom_days[row["subject_id"]].append(row["local_date"])
    score_days = {(r["subject_id"], r["local_date"]): r for r in scores}
    if len(score_days) != len(scores):
        raise ValueError("duplicate daily symptom scores")
    paired = {
        (r["subject_id"], r["local_date"])
        for r in wearable
        if r["heart_rate_records"] or r["steps_records"] or r["sleep_records"]
    }
    audit: Counter[str] = Counter()
    result: list[Landmark] = []
    for row in recovery:
        if row["endpoint"] != "sustained_symptom_free":
            continue
        if row["resolution_definition"] != ENDPOINT:
            raise ValueError("recovery endpoint differs from the frozen protocol")
        audit["canonical_episodes"] += 1
        audit[f"endpoint_{row['status']}_{row['reason']}"] += 1
        if row["reason"] == "no_follow_up":
            audit["excluded_no_follow_up"] += 1
            continue
        subject = row["subject_id"]
        onset = row["onset_first_day"]
        next_onsets = [d for d in by_subject[subject] if d > onset]
        next_onset = min(next_onsets) if next_onsets else None
        days = sorted(
            d
            for d in symptom_days[subject]
            if onset <= d <= row["follow_up_last_day"] and (next_onset is None or d < next_onset)
        )
        if not days:
            audit["excluded_no_symptomatic_landmark"] += 1
            continue
        day = days[0]
        cutoff = datetime.combine(day + timedelta(days=1), datetime.min.time(), UTC)
        score = score_days.get((subject, day))
        if score is None:
            audit["excluded_no_current_score"] += 1
            continue
        if (
            score["scale"] != SCALE
            or score["availability_rule"] != SURVEY_AVAILABILITY_RULE
            or score["available_at_utc"] != cutoff
        ):
            raise ValueError("symptom scale/availability differs from the frozen protocol")
        if not all(isinstance(score[f], int) and score[f] >= 0 for f in FEATURES):
            raise ValueError("missing/invalid current symptom predictors")
        if row["status"] == "resolved":
            lower = (row["resolution_first_day"] - day).days
            upper = (row["resolution_last_day"] - day).days
            if lower < 1:
                audit["excluded_interval_not_after_landmark"] += 1
                continue
        elif row["status"] == "right_censored":
            lower = None
            upper = (row["follow_up_last_day"] - day).days
        else:
            raise ValueError("unknown recovery label status")
        if upper < 1:
            audit["excluded_no_future_follow_up"] += 1
            continue
        observation = Observation(
            subject, row["episode_id"], tuple(float(score[f]) for f in FEATURES), lower, upper
        )
        has_wearable = (subject, day) in paired
        result.append(Landmark(observation, cutoff, score["scale"], has_wearable))
        audit["eligible_resolved" if lower is not None else "eligible_censored"] += 1
        audit["eligible_paired_wearable_day"] += has_wearable
    if len({r.observation.episode for r in result}) != len(result):
        raise ValueError("duplicate episode landmarks")
    return result, dict(sorted(audit.items()))
