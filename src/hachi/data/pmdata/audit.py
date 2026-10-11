"""Build audit: counts, exclusions, missingness and the evidence behind each time mapping.

The private audit sits inside the snapshot and may break counts down by participant. The
sanitized report keeps cohort-level numbers only (distributions, never participant ids) and
is the only part fit for Git.
"""

import statistics
from collections import Counter, defaultdict
from datetime import UTC
from typing import Any

from .clock import MINUTE, to_us
from .sources import Participant
from .wellness import SCALES, Report, WellnessDay

# Entry counts published in the PMData paper (Figure 3), for reconciliation.
PAPER_COUNTS = {
    "fitbit/calories.json": 3_377_529,
    "fitbit/steps.json": 1_534_705,
    "fitbit/distance.json": 1_534_705,
    "fitbit/sleep.json": 2_064,
    "fitbit/lightly_active_minutes.json": 2_244,
    "fitbit/moderately_active_minutes.json": 2_396,
    "fitbit/very_active_minutes.json": 2_396,
    "fitbit/sedentary_minutes.json": 2_396,
    "fitbit/heart_rate.json": 20_991_392,
    "fitbit/time_in_heart_rate_zones.json": 2_178,
    "fitbit/resting_heart_rate.json": 1_803,
    "fitbit/exercise.json": 2_440,
    "fitbit/sleep_score.csv": 1_836,
    "googledocs/reporting.csv": 1_569,
    "pmsys/wellness.csv": 1_747,
    "pmsys/injury.csv": 225,
    "pmsys/srpe.csv": 783,
}

EXCLUSION_REASONS = {
    "fitbit/calories.json": "Total energy expenditure including basal; not active_energy.",
    "fitbit/exercise.json": "Vendor activity summaries; no canonical metric.",
    "fitbit/lightly_active_minutes.json": "Vendor activity-level minutes; no canonical metric.",
    "fitbit/moderately_active_minutes.json": "Vendor activity-level minutes; no canonical metric.",
    "fitbit/very_active_minutes.json": "Vendor activity-level minutes; no canonical metric.",
    "fitbit/sedentary_minutes.json": "Vendor activity-level minutes; no canonical metric.",
    "fitbit/time_in_heart_rate_zones.json": "Vendor HR-zone minutes; no canonical metric.",
    "fitbit/sleep_score.csv": "Vendor sleep score; no canonical metric.",
    "pmsys/srpe.csv": "Training-load reports; not part of this snapshot.",
    "pmsys/injury.csv": "Injury reports; not part of this snapshot.",
    "googledocs/reporting.csv": "Food, fluid, weight and alcohol reports; not ingested.",
    "food-images": "Meal photographs; never opened.",
    "participant-overview.xlsx": "Demographics; never opened.",
}

SHIFTS_MINUTES = tuple(range(-120, 121, 30))
ASLEEP = {"light", "deep", "rem", "asleep"}
MIN_WEEK_MINUTES = 120


def _distribution(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "n": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
    }


class ClockAlignment:
    """Do Fitbit intraday data (read as UTC) and sleep logs (read as local) line up?

    Each asleep minute of a main sleep, placed in UTC through the assumed timezone, is looked up
    in the UTC-read intraday data at a probe shift. If both mappings hold, steps and heart rate
    inside sleep are lowest at shift 0; intraday data on local time would put it at +60 min.
    """

    def __init__(self) -> None:
        self.steps, self.steps_n = Counter(), Counter()
        self.hr, self.hr_n = Counter(), Counter()
        self.weeks = Counter()

    def add(self, participant: Participant) -> None:
        weekly: dict[tuple, Counter] = defaultdict(Counter)
        for log in participant.sleep_logs:
            if not log.main_sleep:
                continue
            week = tuple(log.start_naive.isocalendar()[:2])
            for begin, end, level in log.segments:
                if level not in ASLEEP:
                    continue
                for minute in range(begin - begin % MINUTE, end, MINUTE):
                    for shift in SHIFTS_MINUTES:
                        key = minute + shift * MINUTE
                        steps = participant.steps_by_minute.get(key)
                        if steps is not None:
                            self.steps[shift] += steps
                            self.steps_n[shift] += 1
                        hr = participant.heart_rate_by_minute.get(key)
                        if hr is not None:
                            self.hr[shift] += hr
                            self.hr_n[shift] += 1
                            weekly[week][(shift, "sum")] += hr
                            weekly[week][(shift, "n")] += 1
        for tally in weekly.values():
            if tally[(0, "n")] < MIN_WEEK_MINUTES:
                self.weeks["insufficient_data"] += 1
                continue
            means = {
                s: tally[(s, "sum")] / tally[(s, "n")] for s in SHIFTS_MINUTES if tally[(s, "n")]
            }
            best = min(means, key=lambda s: (means[s], abs(s)))
            self.weeks[f"lowest_heart_rate_at_shift_{best:+d}min"] += 1

    def result(self) -> dict[str, Any]:
        rows = [
            {
                "probe_shift_minutes": s,
                "steps_per_asleep_minute": self.steps[s] / self.steps_n[s]
                if self.steps_n[s]
                else None,
                "steps_minutes": self.steps_n[s],
                "mean_heart_rate_asleep": self.hr[s] / self.hr_n[s] if self.hr_n[s] else None,
                "heart_rate_minutes": self.hr_n[s],
            }
            for s in SHIFTS_MINUTES
        ]
        best = [r for r in rows if r["mean_heart_rate_asleep"] is not None]
        return {
            "method": (
                "Asleep minutes of main sleeps, located with the assumed timezone, probed in the "
                "UTC-read intraday data at shifts around that mapping; 0 means the mapping holds."
            ),
            "by_probe_shift": rows,
            "lowest_heart_rate_shift_minutes": (
                min(best, key=lambda r: r["mean_heart_rate_asleep"])["probe_shift_minutes"]
                if best
                else None
            ),
            "participant_weeks": dict(sorted(self.weeks.items())),
        }


def wellness_timing(reports: list[Report], participant: Participant, counter: Counter) -> None:
    """Count reports falling inside a main sleep, reading their Z as UTC versus as local time."""
    spans = [(log.start, log.end, log) for log in participant.sleep_logs if log.main_sleep]
    for report in reports:
        as_utc = to_us(report.reported_at)
        counter["reports"] += 1
        counter["inside_sleep_if_utc"] += any(a <= as_utc < b for a, b, _ in spans)
        for a, b, log in spans:
            offset = to_us(log.start_naive.replace(tzinfo=UTC)) - log.start
            if a <= as_utc - offset < b:
                counter["inside_sleep_if_local"] += 1
                break


def direction_evidence(rows: list[WellnessDay]) -> dict[str, Any]:
    """Participant-centred correlation of each wellness item with readiness (0 not ready)."""
    by_subject: dict[str, dict] = defaultdict(lambda: defaultdict(dict))
    for row in rows:
        if row.value is not None:
            by_subject[row.subject_id][row.local_date][row.item] = row.value
    pairs: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for days in by_subject.values():
        for item in SCALES:
            if item == "readiness":
                continue
            xs = [
                (d[item], d["readiness"]) for d in days.values() if item in d and "readiness" in d
            ]
            if len(xs) < 3:
                continue
            mx = statistics.fmean(x for x, _ in xs)
            my = statistics.fmean(y for _, y in xs)
            pairs[item] += [(x - mx, y - my) for x, y in xs]
    out = {}
    for item, xs in sorted(pairs.items()):
        x = [a for a, _ in xs]
        y = [b for _, b in xs]
        try:
            r = statistics.correlation(x, y)
        except statistics.StatisticsError:
            r = None
        out[item] = {"correlation_with_readiness": r, "days": len(xs)}
    return {
        "method": "Pearson correlation of participant-centred daily values with readiness.",
        "items": out,
        "documented_directions": {
            item: {"higher_means": s.higher_means, "evidence": s.evidence}
            for item, s in SCALES.items()
        },
    }


def missingness(tables: dict[str, Any]) -> list[dict[str, Any]]:
    """Per resolution, metric and aggregation: bins, values and nulls by reason."""
    out = []
    for resolution, table in tables.items():
        cols = table.select(["metric", "aggregation", "null_reason", "coverage", "value"])
        tally: dict[tuple, Counter] = defaultdict(Counter)
        coverage: dict[tuple, list[float]] = defaultdict(list)
        for metric, aggregation, reason, cov in zip(
            cols["metric"].to_pylist(),
            cols["aggregation"].to_pylist(),
            cols["null_reason"].to_pylist(),
            cols["coverage"].to_pylist(),
            strict=True,
        ):
            key = (metric, aggregation)
            tally[key]["bins"] += 1
            tally[key][reason or "value"] += 1
            if reason is None:
                coverage[key].append(cov)
        for (metric, aggregation), t in sorted(tally.items()):
            out.append(
                {
                    "resolution": resolution,
                    "metric": metric,
                    "aggregation": aggregation,
                    "bins": t["bins"],
                    "with_value": t["value"],
                    "null_no_observations": t["no_observations"],
                    "null_insufficient_coverage": t["insufficient_coverage"],
                    "mean_coverage_of_valued_bins": (
                        statistics.fmean(coverage[(metric, aggregation)])
                        if coverage[(metric, aggregation)]
                        else None
                    ),
                }
            )
    return out


def source_table(counts: Counter, members: list) -> list[dict[str, Any]]:
    kinds = sorted({kind for kind, _ in counts} | {m.kind for m in members})
    files = Counter(m.kind for m in members)
    sizes = Counter()
    for m in members:
        sizes[m.kind] += m.size
    out = []
    for kind in kinds:
        outcomes = {o: n for (k, o), n in sorted(counts.items()) if k == kind and o != "rows"}
        entry: dict[str, Any] = {
            "member": kind,
            "files": files[kind],
            "bytes": sizes[kind],
            "rows_parsed": counts.get((kind, "rows"), None),
            "paper_count": PAPER_COUNTS.get(kind),
            "outcomes": outcomes,
        }
        if kind in PAPER_COUNTS and entry["rows_parsed"] is not None:
            entry["matches_paper"] = entry["rows_parsed"] == PAPER_COUNTS[kind]
        if kind in EXCLUSION_REASONS:
            entry["excluded_reason"] = EXCLUSION_REASONS[kind]
        if kind.startswith("fitbit/") and kind not in EXCLUSION_REASONS:
            # Every parsed row lands in exactly one disposition.
            settled = sum(n for outcome, n in outcomes.items() if _is_disposition(outcome))
            entry["dispositions_reconcile"] = settled == (entry["rows_parsed"] or 0)
        out.append(entry)
    return out


def _is_disposition(outcome: str) -> bool:
    return outcome in {
        "accepted",
        "duplicate_identical_dropped",
        "duplicate_conflicting_dropped",
    } or outcome.startswith(("rejected_", "excluded_", "quarantined_"))
