"""PMSys wellness reports as daily wellness outcomes, kept apart from illness outcomes.

These are self-rated wellness scores, not symptoms. Fatigue is never an illness label, and a
day without a report is unknown (null with "no_survey"), never a healthy day. PMData records
no illness, so the only canonical Outcome rows it yields are StatusUnknown.

Scale directions come from the PMSys answer labels shown in the PMData paper (Thambawita et
al., MMSys 2020, Figure 2). Sleep quality's labels are not shown, so its direction is recorded as
undocumented rather than assumed.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from hachi.contracts.base import (
    Contract,
    IanaTimezone,
    Identifier,
    SubjectId,
    UtcDatetime,
)
from hachi.contracts.tables import StatusUnknown

from . import parse
from .archive import Archive

type Item = Literal[
    "fatigue", "mood", "readiness", "sleep_duration_h", "sleep_quality", "soreness", "stress"
]


@dataclass(frozen=True)
class Scale:
    minimum: float
    maximum: float
    integer: bool
    higher_means: str
    evidence: str


SCALES: dict[Item, Scale] = {
    "fatigue": Scale(
        1, 5, True, "less fatigued", "PMSys labels: 1 Very tired ... 3 Normal ... 5 Very fresh"
    ),
    "mood": Scale(1, 5, True, "better mood", "PMSys labels: 1 Very bad mood ... 5 Very good mood"),
    "readiness": Scale(
        0, 10, True, "more ready to train", "PMSys labels: 0 Not Ready ... 10 Max Ready"
    ),
    "sleep_duration_h": Scale(
        0, 12, False, "longer reported sleep", "PMSys choices: 0 h to 12 h, in half hours to 8.5"
    ),
    "sleep_quality": Scale(
        1, 5, True, "undocumented", "Paper: 3 is normal, 1-2 below and 4-5 above; labels unshown"
    ),
    "soreness": Scale(1, 5, True, "less sore", "PMSys labels: 1 Very sore ... 5 Great"),
    "stress": Scale(
        1, 5, True, "less stressed", "PMSys labels: 1 Highly stressed ... 5 Very relaxed"
    ),
}
EXCLUDED_ITEMS = {"soreness_area": "body-area codes; not a wellness score"}


class WellnessDay(Contract):
    """One wellness item on one local day: the day's last report, or explicitly missing."""

    dataset_id: Identifier
    subject_id: SubjectId
    local_date: date
    tz_name: IanaTimezone
    item: Item
    value: float | None
    null_reason: Literal["no_survey", "out_of_scale", "blank"] | None
    higher_means: Annotated[str, Field(min_length=1, max_length=64)]
    report_id: Identifier | None
    reported_at_utc: UtcDatetime | None = Field(
        description="Submission time of the report used; the label is known from then on."
    )
    reports_that_day: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _check(self) -> Self:
        if (self.value is None) == (self.null_reason is None):
            raise ValueError("value is null exactly when null_reason is given")
        if (self.null_reason == "no_survey") != (self.reports_that_day == 0):
            raise ValueError("no_survey means no report that day, and only then")
        if (self.report_id is None) != (self.reports_that_day == 0):
            raise ValueError("a day with reports names the report used")
        if (self.reported_at_utc is None) != (self.report_id is None):
            raise ValueError("the report used carries its submission time")
        scale = SCALES[self.item]
        if self.value is not None and not scale.minimum <= self.value <= scale.maximum:
            raise ValueError(f"{self.item} must lie in [{scale.minimum}, {scale.maximum}]")
        if self.higher_means != scale.higher_means:
            raise ValueError("higher_means must match the documented scale")
        return self


@dataclass(frozen=True)
class Report:
    report_id: str
    reported_at: datetime
    local_date: date
    items: dict[str, str]


def read_reports(archive: Archive, subject: str, zone: str, counts) -> list[Report]:
    kind = "pmsys/wellness.csv"
    member = archive.member(subject, kind)
    if member is None:
        counts[(kind, "participants_missing_file")] += 1
        return []
    tz = ZoneInfo(zone)
    reports = []
    with archive.open(member) as stream:
        for row in parse.iter_wellness(stream):
            counts[(kind, "rows")] += 1
            stamp = f"{row.reported_at:%Y%m%dT%H%M%S%f}"
            reports.append(
                Report(
                    f"{subject}-wellness-{stamp}",
                    row.reported_at,
                    row.reported_at.astimezone(tz).date(),
                    row.items,
                )
            )
    reports.sort(key=lambda r: (r.reported_at, r.report_id))
    ids = [r.report_id for r in reports]
    if len(ids) != len(set(ids)):
        raise parse.ParseError("two wellness reports share a submission time")
    return reports


def _value(item: Item, raw: str) -> tuple[float | None, str | None]:
    if raw.strip() == "":
        return None, "blank"
    if not (parse.INTEGER if SCALES[item].integer else parse.DECIMAL).match(raw):
        raise parse.ParseError(f"wellness {item} is not a number")
    value = float(raw)
    scale = SCALES[item]
    if not scale.minimum <= value <= scale.maximum:
        return None, "out_of_scale"
    return value, None


def daily_rows(
    dataset_id: str,
    subject: str,
    reports: list[Report],
    first_day: date,
    last_day: date,
    zone: str,
    counts,
) -> list[WellnessDay]:
    """Every (local day, item) from first_day to last_day; the latest report of a day wins."""
    kind = "pmsys/wellness.csv"
    by_day: dict[date, list[Report]] = defaultdict(list)
    for report in reports:
        by_day[report.local_date].append(report)
    rows = []
    day = min([first_day, *by_day])
    final = max([last_day, *by_day])
    while day <= final:
        todays = by_day.get(day, [])
        if len(todays) > 1:
            counts[(kind, "superseded_same_day_reports")] += len(todays) - 1
        chosen = todays[-1] if todays else None
        for item in SCALES:
            if chosen is None:
                value, reason = None, "no_survey"
            else:
                value, reason = _value(item, chosen.items[item])
                counts[(kind, f"{item}_{reason or 'observed'}")] += 1
            rows.append(
                WellnessDay(
                    dataset_id=dataset_id,
                    subject_id=subject,
                    local_date=day,
                    tz_name=zone,
                    item=item,
                    value=value,
                    null_reason=reason,
                    higher_means=SCALES[item].higher_means,
                    report_id=chosen.report_id if chosen else None,
                    reported_at_utc=chosen.reported_at if chosen else None,
                    reports_that_day=len(todays),
                )
            )
        if chosen is not None:
            counts[(kind, "days_with_report")] += 1
            for column in EXCLUDED_ITEMS:
                counts[(kind, f"excluded_{column}")] += 1
        else:
            counts[(kind, "days_without_report")] += 1
        day += timedelta(days=1)
    return rows


def unknown_status(dataset_id: str, subject: str, start: datetime, end: datetime) -> StatusUnknown:
    return StatusUnknown(
        kind="status_unknown",
        dataset_id=dataset_id,
        subject_id=subject,
        start_utc=start,
        end_utc=end,
        reason="other",
        note=(
            "PMData records no illness, symptom-episode or test labels. Wellness ratings, "
            "including fatigue, are not illness outcomes, and missing reports are not healthy."
        ),
    )
