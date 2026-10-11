"""Apple records become canonical observations at one untrusted boundary."""

import hashlib
import json
import math
import re
from datetime import UTC, datetime

from pydantic import ValidationError

from hachi.contracts.metrics import Metric, Unit
from hachi.contracts.tables import Observation, SourceKind


class RecordIssue(ValueError):
    def __init__(self, code: str, disposition: str = "rejected") -> None:
        self.code = code
        self.disposition = disposition
        super().__init__(code)


# Sleeping wrist temperature is an absolute wrist measurement, not the registered
# wrist_temperature_deviation or body_temperature. It stays unsupported.
QUANTITIES: dict[str, tuple[Metric, Unit, dict[str, tuple[float, float]]]] = {
    "HKQuantityTypeIdentifierHeartRate": ("heart_rate", "bpm", {"count/min": (1, 0)}),
    "HKQuantityTypeIdentifierRestingHeartRate": (
        "resting_heart_rate_vendor",
        "bpm",
        {"count/min": (1, 0)},
    ),
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": (
        "hrv_sdnn",
        "ms",
        {"ms": (1, 0), "s": (1000, 0)},
    ),
    "HKQuantityTypeIdentifierRespiratoryRate": (
        "respiratory_rate",
        "breaths_per_min",
        {"count/min": (1, 0)},
    ),
    "HKQuantityTypeIdentifierOxygenSaturation": ("oxygen_saturation", "percent", {"%": (100, 0)}),
    "HKQuantityTypeIdentifierBodyTemperature": (
        "body_temperature",
        "degC",
        {"degC": (1, 0), "degF": (5 / 9, -32 * 5 / 9)},
    ),
    "HKQuantityTypeIdentifierStepCount": ("steps", "count", {"count": (1, 0)}),
    "HKQuantityTypeIdentifierActiveEnergyBurned": (
        "active_energy",
        "kcal",
        {"kcal": (1, 0), "kJ": (1 / 4.184, 0)},
    ),
    "HKQuantityTypeIdentifierDistanceWalkingRunning": (
        "walking_running_distance",
        "m",
        {"m": (1, 0), "km": (1000, 0), "mi": (1609.344, 0)},
    ),
}

SLEEP: dict[str, Metric] = {
    "HKCategoryValueSleepAnalysisInBed": "sleep_in_bed",
    "HKCategoryValueSleepAnalysisAsleep": "sleep_asleep_unspecified",
    "HKCategoryValueSleepAnalysisAsleepUnspecified": "sleep_asleep_unspecified",
    "HKCategoryValueSleepAnalysisAsleepCore": "sleep_asleep_core",
    "HKCategoryValueSleepAnalysisAsleepDeep": "sleep_asleep_deep",
    "HKCategoryValueSleepAnalysisAsleepREM": "sleep_asleep_rem",
    "HKCategoryValueSleepAnalysisAwake": "sleep_awake",
}


def parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError("offset required")
        offset = parsed.utcoffset().total_seconds() / 60
        if not offset.is_integer() or not -720 <= offset <= 840:
            raise ValueError("offset outside canonical range")
        return parsed
    except (ValueError, OverflowError) as exc:
        raise RecordIssue("INVALID_TIMESTAMP") from exc


def _source_kind(attrs: dict[str, str]) -> SourceKind:
    source = (attrs.get("sourceName", "") + " " + attrs.get("device", "")).lower()
    if "apple watch" in source or "watch" in source:
        return "watch"
    if "iphone" in source:
        return "phone"
    return "third_party_app"


def _device_model(device: str) -> str | None:
    # Never publish the device's user-supplied name, UUID or full description.
    match = re.search(r"(?:^|[,<])\s*model:([^,>]+)", device)
    if match is None:
        return None
    model = match.group(1).strip()
    return model if re.fullmatch(r"[A-Za-z0-9 ._+-]{1,64}", model) else None


def normalize_record(
    attrs: dict[str, str], *, dataset_id: str, subject_id: str
) -> Observation | None:
    record_type = attrs.get("type")
    if record_type is None:
        raise RecordIssue("MISSING_FIELD")
    sleep = record_type == "HKCategoryTypeIdentifierSleepAnalysis"
    required = {"startDate", "endDate", "creationDate", "sourceName", "value"}
    if not required <= attrs.keys() or any(not attrs[k] for k in required):
        raise RecordIssue("MISSING_FIELD")
    start = parse_timestamp(attrs["startDate"])
    end = parse_timestamp(attrs["endDate"])
    created = parse_timestamp(attrs["creationDate"])
    try:
        start_utc, end_utc = start.astimezone(UTC), end.astimezone(UTC)
        created_utc = created.astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise RecordIssue("INVALID_TIMESTAMP") from exc
    if end_utc < start_utc:
        raise RecordIssue("END_BEFORE_START")
    if created_utc < start_utc:
        raise RecordIssue("INVALID_TIMESTAMP")
    if record_type not in QUANTITIES and not sleep:
        return None
    if sleep:
        metric = SLEEP.get(attrs["value"])
        if metric is None:
            return None
        unit: Unit = "s"
        value = (end_utc - start_utc).total_seconds()
    else:
        metric, unit, conversions = QUANTITIES[record_type]
        conversion = conversions.get(attrs.get("unit", ""))
        if conversion is None:
            raise RecordIssue("UNKNOWN_UNIT", "quarantined")
        try:
            raw_value = float(attrs["value"])
            value = raw_value * conversion[0] + conversion[1]
            if not math.isfinite(value):
                raise ValueError("nonfinite")
        except (ValueError, OverflowError) as exc:
            raise RecordIssue("VALUE_OUT_OF_RANGE") from exc
    source_identity = json.dumps(
        [dataset_id, subject_id, attrs["sourceName"], attrs.get("device", "")],
        separators=(",", ":"),
    )
    source_id = "apple-" + hashlib.sha256(source_identity.encode()).hexdigest()
    identity = json.dumps(
        [
            source_id,
            metric,
            value,
            start_utc.isoformat(),
            end_utc.isoformat(),
            created_utc.isoformat(),
            int(start.utcoffset().total_seconds() / 60),
        ],
        separators=(",", ":"),
    )
    try:
        return Observation(
            dataset_id=dataset_id,
            subject_id=subject_id,
            record_id="record-" + hashlib.sha256(identity.encode()).hexdigest(),
            source_kind=_source_kind(attrs),
            source_id=source_id,
            device_model=_device_model(attrs.get("device", "")),
            metric=metric,
            unit=unit,
            value=value,
            start_utc=start_utc,
            end_utc=end_utc,
            available_at_utc=created_utc,
            availability="observed",
            availability_rule=None,
            tz_name=None,
            utc_offset_minutes=int(start.utcoffset().total_seconds() / 60),
            tz_provenance="record_offset",
        )
    except ValidationError as exc:
        raise RecordIssue("VALUE_OUT_OF_RANGE") from exc
