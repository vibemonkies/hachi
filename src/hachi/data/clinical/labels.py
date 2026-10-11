"""Dataset-agnostic label construction on a local-day grid (#8).

Sources give illness information at day precision: a reported onset day, a test day, a daily
survey. Everything here works in local calendar days on one dataset clock and follows the locked
definitions in configs/outcomes/definitions.toml. Adapters turn source rows into
`SubjectInput`; `label_subject` turns that into episodes, tests, recovery endpoints, unknown
periods and onset-window labels. Conversion to contract rows happens in `rows`.
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from .config import Definitions

DAY = timedelta(days=1)
UNSPECIFIED = "unspecified_illness"

type SurveyState = Literal["symptomatic", "symptom_free", "intermediate"]
type Endpoint = Literal["sustained_symptom_free", "self_reported_recovery"]
type EndpointReason = Literal[
    "resolved",
    "no_follow_up",
    "no_qualifying_run",
    "not_reported",
    "rejected_before_onset",
    "rejected_after_next_onset",
    "rejected_contradicted_by_survey",
]
type OnsetLabel = Literal[
    "positive",
    "negative",
    "uncertain_partial_onset",
    "uncertain_unexplained_symptoms",
    "unknown_no_survey",
    "unknown_follow_up_ended",
    "excluded_ongoing_episode",
    "excluded_washout",
    "excluded_infection_without_onset",
    "excluded_undated_illness",
]
type TestLabel = Literal[
    "positive_test",
    "uncertain_partial_test",
    "no_reported_positive_test",
    "excluded_recent_positive",
]


@dataclass(frozen=True)
class DayRange:
    """Inclusive range of local days; an onset reported for one day has first == last."""

    first: date
    last: date

    def __post_init__(self) -> None:
        if self.last < self.first:
            raise ValueError("a day range must not end before it starts")


@dataclass(frozen=True)
class TestDay:
    __test__ = False  # not a pytest test class

    day: date
    pathogen: str
    method: str
    result: Literal["positive", "negative", "inconclusive"]


@dataclass(frozen=True)
class IllnessReport:
    """One illness record as a source gives it, before episodes are formed."""

    category: str
    onsets: Sequence[DayRange]
    recoveries: Sequence[date] = ()
    tests: Sequence[TestDay] = ()
    # Lab-confirmed infection status where the source records one apart from its tests (for
    # example seroconversion): True confirms the illness's episodes, False makes them uncertain.
    infection_confirmed: bool | None = None


@dataclass(frozen=True)
class SubjectInput:
    subject_id: str
    span: DayRange  # every local day this participant contributes, wearable or outcome
    illnesses: Sequence[IllnessReport] = ()
    surveys: dict[date, SurveyState] = field(default_factory=dict)
    has_self_reported_recovery: bool = False


@dataclass(frozen=True)
class EndpointResult:
    endpoint: Endpoint
    status: Literal["resolved", "right_censored"]
    reason: EndpointReason
    resolution: DayRange | None
    follow_up_last: date  # last local day of follow-up, inclusive


@dataclass
class Episode:
    episode_id: str
    subject_id: str
    category: str
    onset: DayRange
    reported_onsets: int
    confidence: Literal["confirmed", "probable", "uncertain"] = "probable"
    test_ids: list[str] = field(default_factory=list)
    endpoints: dict[str, EndpointResult] = field(default_factory=dict)
    info_last: date | None = None  # last day with outcome information for this episode


@dataclass(frozen=True)
class Test:
    __test__ = False  # not a pytest test class

    test_id: str
    subject_id: str
    day: date
    pathogen: str
    method: str
    result: str
    episode_id: str | None


@dataclass(frozen=True)
class WindowRow:
    cutoff: date  # cutoff at local midnight starting this day
    onset: tuple[OnsetLabel, ...]  # one per horizon
    onset_episode: tuple[str | None, ...]
    test: tuple[TestLabel, ...]


@dataclass(frozen=True)
class EpisodeBlock:
    """How long an episode keeps its participant out of the onset risk set."""

    episode_id: str
    onset: DayRange
    ongoing_last: date
    washout_last: date


@dataclass(frozen=True)
class Timeline:
    """Everything an onset-window label at any cutoff depends on, for one participant."""

    subject_id: str
    span: DayRange
    blocks: tuple[EpisodeBlock, ...]
    orphan_positive_days: tuple[date, ...]  # positive tests linked to no episode
    positive_test_days: tuple[date, ...]
    surveys: Mapping[date, SurveyState]
    undated_illness: bool


@dataclass
class SubjectLabels:
    subject_id: str
    span: DayRange
    episodes: list[Episode]
    tests: list[Test]
    unknown: list[DayRange]
    windows: list[WindowRow]
    issues: Counter
    timeline: Timeline


def at(day: date) -> datetime:
    """A local day's start on the dataset's floating clock, written as UTC."""
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _days(first: date, last: date) -> Iterable[date]:
    d = first
    while d <= last:
        yield d
        d += DAY


# Episodes ------------------------------------------------------------------------------------


def _form_episodes(
    subject_id: str, illnesses: Sequence[IllnessReport], defs: Definitions, issues: Counter
) -> tuple[list[tuple[Episode, IllnessReport]], list[tuple[TestDay, IllnessReport]]]:
    """Merge each illness's reported onsets into episodes; collect its tests."""
    merge = timedelta(days=defs.onset.episode_merge_days)
    formed: list[tuple[Episode, IllnessReport]] = []
    tests: list[tuple[TestDay, IllnessReport]] = []
    for illness in illnesses:
        tests.extend((t, illness) for t in illness.tests)
        onsets = sorted(set(illness.onsets), key=lambda r: (r.first, r.last))
        if not onsets:
            issues["illness_without_onset"] += 1
            continue
        recoveries = sorted(set(illness.recoveries))
        current: Episode | None = None
        latest_onset: DayRange | None = None
        for onset in onsets:
            recovered_between = latest_onset is not None and any(
                latest_onset.first <= r < onset.first for r in recoveries
            )
            if (
                current is not None
                and latest_onset is not None
                and onset.first - latest_onset.first <= merge
                and not recovered_between
            ):
                current.reported_onsets += 1
                issues["reported_onset_merged_as_relapse"] += 1
            else:
                current = Episode("", subject_id, illness.category, onset, 1)
                formed.append((current, illness))
            latest_onset = onset
    formed.sort(key=lambda pair: (pair[0].onset.first, pair[0].category))
    for n, (episode, _) in enumerate(formed, 1):
        episode.episode_id = f"{subject_id}-e{n}"
    return formed, tests


def _survey_days(surveys: dict[date, SurveyState], first: date, before: date | None) -> list[date]:
    return sorted(d for d in surveys if d >= first and (before is None or d < before))


def _sustained(
    episode: Episode,
    next_onset: date | None,
    surveys: dict[date, SurveyState],
    defs: Definitions,
) -> EndpointResult:
    """First run of `sustained_days` consecutive symptom-free survey days after onset."""
    need = defs.recovery.sustained_days
    days = _survey_days(surveys, episode.onset.first, next_onset)
    last_unwell: date | None = None
    for d in days:
        if surveys[d] != "symptom_free":
            last_unwell = d
            continue
        if d <= episode.onset.last:
            continue
        run_last = d + (need - 1) * DAY
        if next_onset is not None and run_last >= next_onset:
            break
        if all(surveys.get(d + k * DAY) == "symptom_free" for k in range(need)):
            earliest = last_unwell + DAY if last_unwell is not None else episode.onset.first
            return EndpointResult(
                "sustained_symptom_free", "resolved", "resolved", DayRange(earliest, d), run_last
            )
    after = [d for d in days if d > episode.onset.last]
    if not after:
        return EndpointResult(
            "sustained_symptom_free", "right_censored", "no_follow_up", None, episode.onset.last
        )
    return EndpointResult(
        "sustained_symptom_free", "right_censored", "no_qualifying_run", None, after[-1]
    )


def _self_reported(
    episode: Episode,
    recovery: date | None,
    next_onset: date | None,
    surveys: dict[date, SurveyState],
    defs: Definitions,
    issues: Counter,
) -> EndpointResult:
    days = _survey_days(surveys, episode.onset.first, next_onset)
    info_last = max([episode.onset.last, *days])
    if recovery is None:
        return EndpointResult(
            "self_reported_recovery", "right_censored", "not_reported", None, info_last
        )
    if next_onset is not None and recovery >= next_onset:
        reason: EndpointReason = "rejected_after_next_onset"
    else:
        window_end = recovery + timedelta(days=defs.recovery.contradiction_days)
        contradicted = any(recovery < d <= window_end and surveys[d] == "symptomatic" for d in days)
        reason = "rejected_contradicted_by_survey" if contradicted else "resolved"
    if reason != "resolved":
        issues[f"self_reported_recovery_{reason}"] += 1
        return EndpointResult("self_reported_recovery", "right_censored", reason, None, info_last)
    return EndpointResult(
        "self_reported_recovery",
        "resolved",
        "resolved",
        DayRange(recovery, recovery),
        max(info_last, recovery),
    )


def _assign_recoveries(
    formed: list[tuple[Episode, IllnessReport]], issues: Counter
) -> dict[str, date | None]:
    """Each reported recovery goes to the latest episode of its illness that began by then.

    Several dates for one episode mean the earlier recoveries did not last; the latest is kept.
    """
    assigned: dict[str, date | None] = {e.episode_id: None for e, _ in formed}
    illnesses = {id(src): src for _, src in formed}
    for key, illness in illnesses.items():
        mine = sorted((e for e, src in formed if id(src) == key), key=lambda e: e.onset.first)
        for recovery in sorted(set(illness.recoveries)):
            owner = [e for e in mine if e.onset.first <= recovery]
            if not owner:
                issues["self_reported_recovery_rejected_before_onset"] += 1
                continue
            episode = owner[-1]
            if assigned[episode.episode_id] is not None:
                # A recovery followed by another recovery date was not lasting: keep the latest.
                issues["self_reported_recovery_earlier_date_superseded"] += 1
            assigned[episode.episode_id] = recovery
    return assigned


def label_subject(
    subject: SubjectInput, defs: Definitions, test_prefix: str = "t"
) -> SubjectLabels:
    issues: Counter = Counter()
    formed, raw_tests = _form_episodes(subject.subject_id, subject.illnesses, defs, issues)
    recoveries = _assign_recoveries(formed, issues)
    episodes = [e for e, _ in formed]
    for episode in episodes:
        later = [e.onset.first for e in episodes if e.onset.first > episode.onset.first]
        next_onset = min(later) if later else None
        episode.endpoints["sustained_symptom_free"] = _sustained(
            episode, next_onset, subject.surveys, defs
        )
        if subject.has_self_reported_recovery:
            episode.endpoints["self_reported_recovery"] = _self_reported(
                episode, recoveries[episode.episode_id], next_onset, subject.surveys, defs, issues
            )
        episode.info_last = max(r.follow_up_last for r in episode.endpoints.values())

    tests = _link_tests(subject.subject_id, formed, raw_tests, defs, test_prefix, issues)
    illness_of = {e.episode_id: src for e, src in formed}
    for episode in episodes:
        linked = [t for t in tests if t.episode_id == episode.episode_id]
        episode.test_ids = [t.test_id for t in linked]
        source = illness_of[episode.episode_id]
        if source.infection_confirmed is False:
            episode.confidence = "uncertain"
        elif any(t.result == "positive" for t in linked) or source.infection_confirmed:
            episode.confidence = "confirmed"
        elif any(t.result == "positive" for t in illness_of[episode.episode_id].tests):
            # The illness's positive test belongs to another of its episodes, so this one is
            # some other illness: it keeps no pathogen-specific category.
            episode.category = UNSPECIFIED
            issues["episode_unlinked_from_its_illness_test"] += 1
    undated = any(not i.onsets and not i.tests for i in subject.illnesses)
    if undated:
        issues["illness_without_any_date"] += 1
    unknown = _unknown_periods(subject, episodes)
    timeline = Timeline(
        subject.subject_id,
        subject.span,
        tuple(EpisodeBlock(e.episode_id, e.onset, *episode_block_last(e, defs)) for e in episodes),
        tuple(sorted(t.day for t in tests if t.result == "positive" and t.episode_id is None)),
        tuple(sorted(t.day for t in tests if t.result == "positive")),
        dict(subject.surveys),
        undated,
    )
    windows = daily_windows(timeline, defs)
    return SubjectLabels(
        subject.subject_id, subject.span, episodes, tests, unknown, windows, issues, timeline
    )


def _link_tests(
    subject_id: str,
    formed: list[tuple[Episode, IllnessReport]],
    raw: list[tuple[TestDay, IllnessReport]],
    defs: Definitions,
    prefix: str,
    issues: Counter,
) -> list[Test]:
    before = timedelta(days=defs.test.link_days_before_onset)
    after = timedelta(days=defs.test.link_days_after_onset)
    out: list[Test] = []
    ordered = sorted(raw, key=lambda pair: (pair[0].day, pair[0].pathogen, pair[0].result))
    for n, (t, illness) in enumerate(ordered, 1):
        candidates = [
            e
            for e, src in formed
            if src is illness and e.onset.first - before <= t.day <= e.onset.last + after
        ]
        episode = min(candidates, key=lambda e: abs((t.day - e.onset.first).days), default=None)
        if episode is None and t.result == "positive":
            issues["positive_test_unlinked"] += 1
        out.append(
            Test(
                f"{subject_id}-{prefix}{n}",
                subject_id,
                t.day,
                t.pathogen,
                t.method,
                t.result,
                episode.episode_id if episode else None,
            )
        )
    return out


def episode_block_last(episode: Episode, defs: Definitions) -> tuple[date, date]:
    """Last day the episode is ongoing, and last day of the washout after it."""
    resolved = [
        r.resolution.last
        for r in episode.endpoints.values()
        if r.status == "resolved" and r.resolution is not None
    ]
    if resolved:
        end = min(resolved)
        return end, end + timedelta(days=defs.onset.washout_after_resolution_days)
    assert episode.info_last is not None
    washout = episode.onset.first + timedelta(days=defs.onset.washout_after_censored_onset_days)
    return episode.info_last, max(washout, episode.info_last)


def _unknown_periods(subject: SubjectInput, episodes: list[Episode]) -> list[DayRange]:
    """Maximal runs of span days with neither a completed survey nor a covering episode."""
    covered: set[date] = set(subject.surveys)
    for e in episodes:
        assert e.info_last is not None
        covered.update(_days(e.onset.first, e.info_last))
    runs: list[DayRange] = []
    start: date | None = None
    for d in _days(subject.span.first, subject.span.last):
        if d in covered:
            if start is not None:
                runs.append(DayRange(start, d - DAY))
                start = None
        elif start is None:
            start = d
    if start is not None:
        runs.append(DayRange(start, subject.span.last))
    return runs


def daily_windows(timeline: Timeline, defs: Definitions) -> list[WindowRow]:
    """Labels at every local midnight from the span's second day (features need a prior day)."""
    rows = []
    for cutoff in _days(timeline.span.first + DAY, timeline.span.last):
        labels = [classify(timeline, at(cutoff), h, defs) for h in defs.onset.horizons_hours]
        rows.append(
            WindowRow(
                cutoff,
                tuple(x[0] for x in labels),
                tuple(x[1] for x in labels),
                tuple(x[2] for x in labels),
            )
        )
    return rows


def classify(
    timeline: Timeline, cutoff: datetime, horizon_hours: int, defs: Definitions
) -> tuple[OnsetLabel, str | None, TestLabel]:
    """Onset label, the episode behind it, and the positive-test label for one window.

    The window is [cutoff, cutoff + horizon). Any cutoff works, on the dataset's clock; onset
    and test intervals keep their day precision, so a window only fully contains one when the
    window's edges allow it, and a partial overlap is uncertain rather than guessed.
    """
    if cutoff.utcoffset() != timedelta(0):
        raise ValueError("cutoff must be a UTC-aware datetime on the dataset clock")
    end = cutoff + timedelta(hours=horizon_hours)
    before = timedelta(days=defs.onset.infection_without_onset_days_before)
    after = timedelta(days=defs.onset.infection_without_onset_days_after)
    recent = timedelta(days=defs.test.exclude_days_after_positive)

    def contains(first: date, last: date) -> bool:
        return cutoff <= at(first) and at(last + DAY) <= end

    def overlaps(first: date, last: date) -> bool:
        return at(first) < end and at(last + DAY) > cutoff

    tests = timeline.positive_test_days
    if any(at(t + DAY) <= cutoff < at(t + DAY) + recent for t in tests):
        test: TestLabel = "excluded_recent_positive"
    elif any(contains(t, t) for t in tests):
        test = "positive_test"
    elif any(overlaps(t, t) for t in tests):
        test = "uncertain_partial_test"
    else:
        test = "no_reported_positive_test"

    blocks = timeline.blocks
    if timeline.undated_illness:  # an illness reported without any date could be anywhere
        return "excluded_undated_illness", None, test
    # Ongoing once the whole onset interval lies before the cutoff; a cutoff inside the
    # interval leaves the onset's side of the cutoff unknown (uncertain_partial_onset).
    if any(at(b.onset.last + DAY) <= cutoff < at(b.ongoing_last + DAY) for b in blocks):
        return "excluded_ongoing_episode", None, test
    if any(at(b.onset.last + DAY) <= cutoff < at(b.washout_last + DAY) for b in blocks):
        return "excluded_washout", None, test
    if any(at(t) - before <= cutoff < at(t + DAY) + after for t in timeline.orphan_positive_days):
        return "excluded_infection_without_onset", None, test
    inside = [b for b in blocks if contains(b.onset.first, b.onset.last)]
    if inside:
        return "positive", inside[0].episode_id, test
    partial = [b for b in blocks if overlaps(b.onset.first, b.onset.last)]
    if partial:
        return "uncertain_partial_onset", partial[0].episode_id, test
    if end > at(timeline.span.last + DAY):
        return "unknown_follow_up_ended", None, test
    last = (end - timedelta(microseconds=1)).date()
    states = [timeline.surveys.get(d) for d in _days(cutoff.date(), last)]
    if any(s in ("symptomatic", "intermediate") for s in states):
        return "uncertain_unexplained_symptoms", None, test
    if all(s == "symptom_free" for s in states):
        return "negative", None, test
    return "unknown_no_survey", None, test
