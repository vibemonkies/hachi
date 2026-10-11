import json
import shutil
import stat
import zipfile
from datetime import UTC, date, datetime, timedelta

import pyarrow.parquet as pq
import pytest

from hachi.contracts.causality import available_by
from hachi.data.pmdata import aggregates as agg
from hachi.data.pmdata.archive import ArchiveError, open_archive
from hachi.data.pmdata.config import load_config
from hachi.data.pmdata.reconcile import reconcile
from hachi.data.pmdata.snapshot import (
    GitState,
    build,
    iter_aggregates,
    iter_observations,
    load_manifest,
    read_outcomes,
    read_wellness,
    verify,
)

from .conftest import build_members, write_archive


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def counts(report, member):
    return next(s for s in report["sources"] if s["member"] == member)


def test_snapshot_is_valid_and_verifies(built):
    outcome = verify(
        built.snapshot, full=True, archive_path=built.archive, admission=built.admission
    )
    assert outcome["ok"], outcome["problems"]
    manifest = load_manifest(built.snapshot)
    assert manifest["snapshot_id"] == built.snapshot.name
    assert manifest["subjects"] == ["p01", "p02"]
    assert set(manifest["source"]["members"]["not_read"]) == {
        "food-images",
        "participant-overview.xlsx",
    }
    mode = built.snapshot.stat().st_mode
    assert not mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)


def test_rebuild_is_byte_identical(built, tmp_path):
    again = build(
        built.archive, tmp_path, load_config(), built.admission, GitState("0" * 40, False)
    )
    assert again.path.name == built.snapshot.name
    assert (again.path / "SHA256SUMS").read_text() == (built.snapshot / "SHA256SUMS").read_text()


def test_snapshot_is_never_overwritten(built):
    with pytest.raises(ValueError, match="never overwritten"):
        build(
            built.archive,
            built.snapshot.parent,
            load_config(),
            built.admission,
            GitState("0" * 40, False),
        )
    leftovers = [p for p in built.snapshot.parent.iterdir() if p.name.startswith(".building")]
    assert leftovers == []


def test_tampering_is_detected(built, tmp_path):
    copy = tmp_path / built.snapshot.name
    shutil.copytree(built.snapshot, copy)
    target = copy / "aggregates_daily.parquet"
    target.chmod(stat.S_IRUSR | stat.S_IWUSR)
    data = bytearray(target.read_bytes())
    data[len(data) // 2] ^= 0xFF
    target.write_bytes(bytes(data))
    outcome = verify(copy)
    assert not outcome["ok"]
    assert any("aggregates_daily.parquet" in p for p in outcome["problems"])


def test_intraday_is_utc_and_sleep_is_local(built):
    hr = list(iter_observations(built.snapshot, subjects=["p01"], metrics=["heart_rate"]))
    assert hr[0].start_utc == utc(2020, 3, 27, 18, 0)
    assert hr[0].availability == "assumed"
    assert hr[0].availability_rule == "pmdata-fitbit-intraday-end-plus-0s"
    assert hr[0].tz_name == "Europe/Oslo"
    in_bed = {
        o.record_id: o
        for o in iter_observations(built.snapshot, subjects=["p01"], metrics=["sleep_in_bed"])
    }
    # 23:00 local in CET (UTC+1) and 22:00 local in CEST (UTC+2).
    assert in_bed["p01-sleep-1001-inbed"].start_utc == utc(2020, 3, 27, 22, 0)
    assert in_bed["p01-sleep-1003-inbed"].start_utc == utc(2020, 3, 29, 20, 0)
    assert set(in_bed) == {"p01-sleep-1001-inbed", "p01-sleep-1003-inbed"}


def test_sleep_segments_become_available_when_the_log_ends(built):
    deep = next(
        o
        for o in iter_observations(built.snapshot, subjects=["p01"], metrics=["sleep_asleep_deep"])
    )
    log_end = utc(2020, 3, 27, 22, 0) + timedelta(seconds=11400)
    assert deep.end_utc < log_end == deep.available_at_utc
    # Ended but not yet available: a backdated record is excluded at that cutoff.
    assert not available_by(deep, deep.end_utc)
    assert available_by(deep, log_end)


def test_short_wakes_reconcile_stages_with_fitbit_summary(built):
    sleep = counts(built.report, "fitbit/sleep.json")["outcomes"]
    assert sleep["summary_reconciled"] == 2
    assert "summary_mismatch" not in sleep
    stages = list(
        iter_observations(
            built.snapshot, subjects=["p01"], start=utc(2020, 3, 27, 22), end=utc(2020, 3, 28, 2)
        )
    )
    awake = sum(o.value for o in stages if o.metric == "sleep_awake")
    assert awake == 600 + 60 + 90


def test_quarantine_duplicates_and_exclusions_are_counted(built):
    sleep = counts(built.report, "fitbit/sleep.json")["outcomes"]
    assert sleep["duplicate_identical_dropped"] == 1
    assert sleep["duplicate_conflicting_dropped"] == 2
    assert sleep["quarantined_dst_transition"] == 1
    assert sleep["quarantined_overlapping_logs"] == 2
    assert sleep["segments_excluded_classic_restless"] == 1
    hr = counts(built.report, "fitbit/heart_rate.json")["outcomes"]
    assert hr["duplicate_identical_dropped"] == 1
    assert hr["duplicate_conflicting_dropped"] == 2
    assert hr["rejected_out_of_bounds"] == 1
    assert hr["participants_missing_file"] == 1
    rhr = counts(built.report, "fitbit/resting_heart_rate.json")["outcomes"]
    assert rhr["excluded_zero_means_no_estimate"] == 1
    for member in ("heart_rate", "steps", "distance", "resting_heart_rate", "sleep"):
        assert counts(built.report, f"fitbit/{member}.json")["dispositions_reconcile"]
    calories = counts(built.report, "fitbit/calories.json")
    assert calories["excluded_reason"].startswith("Total energy expenditure")
    assert calories["rows_parsed"] == 66 * 60


def test_missing_minutes_stay_missing(built):
    hours = {
        a.interval_start_utc: a
        for a, _ in iter_aggregates(built.snapshot, "hour", subjects=["p01"], metrics=["steps"])
    }
    off = hours[utc(2020, 3, 28, 13)]
    assert off.value is None and off.null_reason == "no_observations" and off.coverage == 0
    sparse = hours[utc(2020, 3, 28, 3)]  # odd minutes absent: half covered, never filled
    assert sparse.value == 10 * 12 and sparse.observed_count == 30 and sparse.coverage == 0.5
    asleep = hours[utc(2020, 3, 27, 23)]  # recorded zeros are real zeros
    assert asleep.value == 0 and asleep.observed_count == 60 and asleep.coverage == 1
    hr_hours = {
        a.interval_start_utc: a
        for a, _ in iter_aggregates(
            built.snapshot, "hour", subjects=["p01"], metrics=["heart_rate"]
        )
        if a.aggregation == "mean"
    }
    assert hr_hours[utc(2020, 3, 28, 13)].null_reason == "no_observations"


def test_daily_bins_follow_local_days_across_dst(built):
    days = {
        a.local_date: a
        for a, _ in iter_aggregates(built.snapshot, "day", subjects=["p01"], metrics=["steps"])
    }
    dst = days[date(2020, 3, 29)]
    assert dst.interval_end_utc - dst.interval_start_utc == timedelta(hours=23)
    rhr = {
        a.local_date: a.value
        for a, _ in iter_aggregates(
            built.snapshot, "day", subjects=["p01"], metrics=["resting_heart_rate_vendor"]
        )
    }
    assert rhr[date(2020, 3, 27)] is None
    assert rhr[date(2020, 3, 28)] == 51.5


def test_stored_bins_equal_as_of_recomputation_once_available(built):
    config = load_config().config
    every = list(iter_observations(built.snapshot, subjects=["p01"]))
    grids = agg.subject_grids(agg.group_observations(every), config.local_timezone)
    stored = {
        (r.metric, r.aggregation, r.resolution, r.interval_start_utc): (r, available)
        for resolution in ("hour", "day")
        for r, available in iter_aggregates(built.snapshot, resolution, subjects=["p01"])
    }
    # Every 7th distinct availability, plus a cutoff inside the first night: its hour bins
    # have ended but the sleep log only becomes available at 01:10 UTC.
    cutoffs = sorted({available for _, available in stored.values()})[::7]
    cutoffs.append(utc(2020, 3, 28, 0, 30))
    differs_earlier = 0
    for cutoff in cutoffs:
        visible = agg.group_observations(o for o in every if available_by(o, cutoff))
        recomputed = agg.subject_aggregates("p01", visible, config, grids)
        for resolution, rows in recomputed.items():
            for row in rows:
                key = (row["metric"], row["aggregation"], resolution, row["interval_start_utc"])
                aggregate, available = stored[key]
                same = (row["value"], row["observed_count"], row["coverage"]) == (
                    aggregate.value,
                    aggregate.observed_count,
                    aggregate.coverage,
                )
                if available <= cutoff:
                    assert same, key
                elif row["interval_end_utc"] <= cutoff and not same:
                    differs_earlier += 1
    # Bins that had ended but were not yet final really did change later (sleep logs).
    assert differs_earlier > 0


def test_as_of_reading_respects_cutoffs(built):
    cutoff = utc(2020, 3, 28, 1)
    for o in iter_observations(built.snapshot, subjects=["p01"], as_of=cutoff):
        assert available_by(o, cutoff)
    for a, available in iter_aggregates(built.snapshot, "hour", as_of=cutoff):
        assert available <= cutoff and a.interval_end_utc <= cutoff


def test_wellness_scales_masks_and_latest_report(built):
    rows = {(r.subject_id, r.local_date, r.item): r for r in read_wellness(built.snapshot)}
    day = rows[("p01", date(2020, 3, 28), "fatigue")]
    assert day.value == 4 and day.reports_that_day == 2
    assert day.reported_at_utc == utc(2020, 3, 28, 9, 30, 0, 500000)
    assert day.higher_means == "less fatigued"
    assert rows[("p01", date(2020, 3, 28), "sleep_duration_h")].value == 7.5
    missing = rows[("p01", date(2020, 3, 29), "fatigue")]
    assert missing.value is None and missing.null_reason == "no_survey"
    bad = rows[("p01", date(2020, 3, 30), "fatigue")]
    assert bad.value is None and bad.null_reason == "out_of_scale"
    assert rows[("p01", date(2020, 3, 30), "mood")].value == 3
    assert rows[("p01", date(2020, 3, 28), "sleep_quality")].higher_means == "undocumented"


def test_no_illness_labels_only_unknown_status(built):
    outcomes = read_outcomes(built.snapshot)
    assert {o.subject_id for o in outcomes} == {"p01", "p02"}
    assert all(o.kind == "status_unknown" for o in outcomes)


def test_sanitized_report_names_no_participant(built):
    text = json.dumps(built.report)
    assert "p01" not in text and "p02" not in text
    private = json.loads((built.snapshot / "audit.json").read_text())
    assert set(private["per_subject"]) == {"p01", "p02"}


def test_reconcile_from_raw_archive(built):
    outcome = reconcile(built.snapshot, built.archive, built.admission)
    assert outcome["ok"], outcome["mismatch_examples"]
    assert outcome["checks"]["hour:steps:sum"] > 0
    assert outcome["checks"]["day:sleep_asleep_deep:sum"] > 0


def test_clock_alignment_detects_the_mapping(built):
    alignment = built.report["clock_alignment"]
    assert alignment["lowest_heart_rate_shift_minutes"] == 0


def test_archive_must_match_its_admission(synthetic_archive, tmp_path):
    path, admission = synthetic_archive
    wrong = admission.model_copy(update={"archive_sha256": "0" * 64})
    with pytest.raises(ArchiveError, match="SHA-256"), open_archive(path, wrong):
        pass


@pytest.mark.parametrize(
    "name", ["p01/fitbit/unexpected.json", "../escape.json", "p01/fitbit/../../x.json"]
)
def test_unexpected_members_refuse_the_archive(tmp_path, name):
    members = build_members()
    members[name] = b"[]"
    admission = write_archive(tmp_path / "pmdata.zip", members)
    with pytest.raises(ArchiveError), open_archive(tmp_path / "pmdata.zip", admission):
        pass


def test_tables_hold_exactly_the_contract_columns(built):
    from hachi.contracts.tables import Aggregate, Observation

    observation_columns = pq.read_schema(built.snapshot / "observations.parquet").names
    assert observation_columns == list(Observation.model_fields)
    aggregate_columns = pq.read_schema(built.snapshot / "aggregates_hourly.parquet").names
    assert aggregate_columns == [*Aggregate.model_fields, "available_at_utc"]


def test_member_checksums_cover_whole_members(built):
    import hashlib

    manifest = load_manifest(built.snapshot)
    with zipfile.ZipFile(built.archive) as handle:
        for name, entry in manifest["source"]["members"]["read"].items():
            assert hashlib.sha256(handle.read(name)).hexdigest() == entry["sha256"]
