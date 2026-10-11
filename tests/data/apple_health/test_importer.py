"""Synthetic records exercise the import boundary, not personal export validation."""

import json
import sqlite3
import zipfile
from datetime import UTC, datetime
from xml.sax.saxutils import quoteattr

import pytest

from hachi.data.apple_health import (
    ImportLimits,
    ImportProblem,
    import_export,
    iter_observations,
)


def record(**changes):
    attrs = {
        "type": "HKQuantityTypeIdentifierHeartRate",
        "unit": "count/min",
        "value": "64",
        "sourceName": "Synthetic Apple Watch",
        "device": "<HKDevice: name:Private, model:Watch>",
        "startDate": "2026-10-10 00:00:00 -0700",
        "endDate": "2026-10-10 00:00:00 -0700",
        "creationDate": "2026-10-10 00:00:01 -0700",
    }
    attrs.update(changes)
    return attrs


def xml(records):
    rows = [
        "<Record " + " ".join(f"{k}={quoteattr(v)}" for k, v in r.items()) + "/>" for r in records
    ]
    return ("<HealthData>" + "".join(rows) + "</HealthData>").encode()


def run(tmp_path, config, records):
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "export.xml"
    source.write_bytes(xml(records))
    database = tmp_path / "private" / "import.sqlite3"
    audit = import_export(source, config, database)
    return audit, list(iter_observations(database)), database


def test_reconciled_buckets_and_provenance(tmp_path, config):
    rows = [
        record(),
        record(),
        record(unit="unknown"),
        record(value="NaN"),
        record(type="HKQuantityTypeIdentifierAppleSleepingWristTemperature", unit="degC"),
        record(startDate="not-a-date"),
        record(type="HKQuantityTypeIdentifierStepCount", unit="count", value="12"),
    ]
    audit, observations, database = run(tmp_path, config, rows)
    assert audit.counts.model_dump() == {
        "records_seen": 7,
        "records_accepted": 2,
        "records_duplicate": 1,
        "records_unsupported": 1,
        "records_rejected": 2,
        "records_quarantined": 1,
    }
    assert audit.counts.bucket_total() == 7
    assert {(i.code, i.count) for i in audit.issues} == {
        ("UNKNOWN_UNIT", 1),
        ("VALUE_OUT_OF_RANGE", 1),
        ("INVALID_TIMESTAMP", 1),
    }
    hr = next(o for o in observations if o.metric == "heart_rate")
    assert hr.start_utc == datetime(2026, 10, 10, 7, tzinfo=UTC)
    assert hr.available_at_utc == datetime(2026, 10, 10, 7, 0, 1, tzinfo=UTC)
    assert hr.utc_offset_minutes == -420 and hr.tz_provenance == "record_offset"
    assert hr.availability == "observed" and hr.availability_rule is None
    assert hr.device_model == "Watch" and "Private" not in hr.model_dump_json()
    assert "Synthetic Apple Watch" not in hr.model_dump_json()
    assert database.stat().st_mode & 0o777 == 0o600
    assert database.parent.stat().st_mode & 0o777 == 0o700
    with sqlite3.connect(database) as connection:
        raw = json.loads(
            connection.execute("SELECT raw_json FROM records WHERE row_id=1").fetchone()[0]
        )
    assert raw == rows[0]


@pytest.mark.parametrize(
    ("record_type", "unit", "value", "metric", "expected"),
    [
        ("HeartRateVariabilitySDNN", "s", "0.045", "hrv_sdnn", 45),
        ("OxygenSaturation", "%", "0.98", "oxygen_saturation", 98),
        ("BodyTemperature", "degF", "98.6", "body_temperature", 37),
        ("DistanceWalkingRunning", "km", "1.2", "walking_running_distance", 1200),
        ("ActiveEnergyBurned", "kJ", "4.184", "active_energy", 1),
        ("RespiratoryRate", "count/min", "16", "respiratory_rate", 16),
    ],
)
def test_known_units_are_converted(tmp_path, config, record_type, unit, value, metric, expected):
    _, observations, _ = run(
        tmp_path,
        config,
        [record(type="HKQuantityTypeIdentifier" + record_type, unit=unit, value=value)],
    )
    assert observations[0].metric == metric
    assert observations[0].value == pytest.approx(expected)


def test_missing_steps_remain_unavailable(tmp_path, config):
    audit, observations, _ = run(tmp_path, config, [record()])
    assert "steps" in audit.missing_metrics
    assert all(o.metric != "steps" for o in observations)


def test_source_precedence_never_sums_competing_step_totals(tmp_path, config):
    step = record(
        type="HKQuantityTypeIdentifierStepCount",
        unit="count",
        value="120",
        endDate="2026-10-10 01:00:00 -0700",
        creationDate="2026-10-10 01:01:00 -0700",
    )
    phone = {
        **step,
        "sourceName": "Synthetic iPhone",
        "device": "",
        "value": "90",
        "startDate": "2026-10-10 00:30:00 -0700",
        "endDate": "2026-10-10 01:30:00 -0700",
    }
    for i, rows in enumerate(([step, phone], [phone, step])):
        folder = tmp_path / str(i)
        folder.mkdir()
        audit, observations, _ = run(folder, config, rows)
        assert audit.counts.records_duplicate == 1
        assert len(observations) == 1 and observations[0].value == 120
        assert observations[0].source_kind == "watch"


def test_creation_cutoff_is_applied_before_source_precedence(tmp_path, config):
    phone = record(sourceName="Synthetic iPhone", device="", value="60")
    watch = record(value="70", creationDate="2026-10-12 00:00:00 -0700")
    audit, full, database = run(tmp_path, config, [phone, watch])
    assert full[0].value == 70 and audit.counts.records_duplicate == 1
    early = list(iter_observations(database, as_of=datetime(2026, 10, 11, tzinfo=UTC)))
    assert len(early) == 1 and early[0].value == 60
    assert early[0].source_kind == "phone"


def test_cross_midnight_dst_sleep_is_elapsed_time_and_stages_win(tmp_path, config):
    sleep = record(
        type="HKCategoryTypeIdentifierSleepAnalysis",
        unit="",
        value="HKCategoryValueSleepAnalysisAsleep",
        startDate="2026-11-01 00:30:00 -0700",
        endDate="2026-11-01 02:30:00 -0800",
        creationDate="2026-11-01 03:00:00 -0800",
    )
    core = {
        **sleep,
        "value": "HKCategoryValueSleepAnalysisAsleepCore",
        "startDate": "2026-11-01 01:30:00 -0700",
        "endDate": "2026-11-01 01:30:00 -0800",
    }
    in_bed = {**sleep, "value": "HKCategoryValueSleepAnalysisInBed"}
    audit, observations, _ = run(tmp_path, config, [sleep, core, in_bed])
    assert audit.counts.records_duplicate == 1
    assert {o.metric: o.value for o in observations} == {
        "sleep_asleep_core": 3600,
        "sleep_in_bed": 10800,
    }
    # Summary outside the staged interval is intentionally not manufactured.
    assert "sleep_asleep_unspecified" in audit.missing_metrics
    _, overnight, _ = run(
        tmp_path / "overnight",
        config,
        [
            {
                **sleep,
                "startDate": "2026-10-09 23:00:00 -0700",
                "endDate": "2026-10-10 06:30:00 -0700",
                "creationDate": "2026-10-10 07:00:00 -0700",
            }
        ],
    )
    assert overnight[0].value == 7.5 * 3600


@pytest.mark.parametrize(
    "payload",
    [
        b"<HealthData><Record></HealthData>",
        b'<!DOCTYPE HealthData [<!ENTITY x "value">]><HealthData>&x;</HealthData>',
        b'<!DOCTYPE HealthData SYSTEM "https://example.invalid/x"><HealthData/>',
        b"<HealthData>" + b"<Nested>" * 40 + b"</Nested>" * 40 + b"</HealthData>",
        b'<HealthData><Record value="' + b"x" * 200000 + b'"/></HealthData>',
    ],
)
def test_unsafe_or_malformed_xml_leaves_no_snapshot(tmp_path, config, payload):
    path = tmp_path / "export.xml"
    path.write_bytes(payload)
    database = tmp_path / "private" / "import.sqlite3"
    with pytest.raises(ImportProblem) as error:
        import_export(path, config, database)
    assert error.value.failure.error_code == "MALFORMED_XML"
    assert not database.exists()


def test_apple_internal_schema_dtd_is_allowed(tmp_path, config):
    path = tmp_path / "export.xml"
    path.write_bytes(
        b"<!DOCTYPE HealthData [<!ELEMENT HealthData (Record*)>\n"
        b"<!ELEMENT Record EMPTY>\n<!ATTLIST Record type CDATA #IMPLIED>]>" + xml([record()])
    )
    audit = import_export(path, config, tmp_path / "private" / "import.sqlite3")
    assert audit.counts.records_accepted == 1


@pytest.mark.parametrize(
    "member", ["../export.xml", "/export.xml", "a\\export.xml", "C:/export.xml"]
)
def test_archive_paths_are_checked_without_extracting(tmp_path, config, member):
    path = tmp_path / "export.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, xml([record()]))
    with pytest.raises(ImportProblem) as error:
        import_export(path, config, tmp_path / "private" / "import.sqlite3")
    assert error.value.failure.error_code == "ARCHIVE_UNSAFE"
    assert not (tmp_path / "export.xml").exists()


def test_zip_and_xml_reconcile_identically(tmp_path, config):
    data = xml([record(), record(unit="bad")])
    path = tmp_path / "export.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("apple_health_export/export.xml", data)
    audit = import_export(path, config, tmp_path / "private" / "import.sqlite3")
    assert audit.counts.records_accepted == 1 and audit.counts.records_quarantined == 1


@pytest.mark.parametrize(
    "limits", [ImportLimits(upload_bytes=10), ImportLimits(xml_bytes=10), ImportLimits(records=1)]
)
def test_resource_limits_fail_with_actionable_error(tmp_path, config, limits):
    source = tmp_path / "export.xml"
    source.write_bytes(xml([record(), record(value="66")]))
    with pytest.raises(ImportProblem) as error:
        import_export(source, config, tmp_path / "private" / "import.sqlite3", limits=limits)
    assert error.value.failure.error_code == "FILE_TOO_LARGE"
    assert error.value.failure.action


def test_existing_snapshot_is_preserved(tmp_path, config):
    _, _, database = run(tmp_path, config, [record()])
    before = database.read_bytes()
    with pytest.raises(FileExistsError):
        import_export(tmp_path / "export.xml", config, database)
    assert database.read_bytes() == before


def test_equivalent_instants_with_different_offsets_select_deterministically(tmp_path, config):
    local = record()
    utc = record(
        startDate="2026-10-10 07:00:00 +0000",
        endDate="2026-10-10 07:00:00 +0000",
        creationDate="2026-10-10 07:00:01 +0000",
    )
    first = run(tmp_path / "first", config, [local, utc])[1]
    second = run(tmp_path / "second", config, [utc, local])[1]
    assert [o.model_dump() for o in first] == [o.model_dump() for o in second]


def test_timestamp_overflow_is_rejected_without_aborting_other_records(tmp_path, config):
    stamp = "0001-01-01 00:00:00 +1400"
    broken = record(startDate=stamp, endDate=stamp, creationDate=stamp)
    audit, observations, _ = run(tmp_path, config, [broken, record()])
    assert audit.counts.records_rejected == 1
    assert audit.issues[0].code == "INVALID_TIMESTAMP"
    assert len(observations) == 1
