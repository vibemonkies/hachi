"""Generated ordering, canonical binding, private-file and competing-writer regressions."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from hachi.contracts.requests import ReportRequest
from hachi.contracts.results import ReportResult
from hachi.evaluation.prospective import Journal, ProspectiveRefused
from hachi.evaluation.prospective.specification import Receipt
from hachi.evaluation.prospective.synthetic import (
    INPUT,
    PLAN,
    fixture,
    generated_proof,
    outcome,
)
from hachi.evaluation.serialization import document_bytes, document_sha256

AT = datetime(2040, 1, 10, 12, tzinfo=UTC)
CLOCK = "hachi.evaluation.prospective.journal._now"


@pytest.fixture
def registered(tmp_path):
    protocol, prediction = fixture(AT)
    root = tmp_path.resolve() / "journal"
    with patch(CLOCK, return_value=AT - timedelta(seconds=1)):
        registration = Journal.create(root, protocol, analysis_plan=PLAN)
    return Journal(root), registration, protocol, prediction


def save(registered):
    journal, registration, _, prediction = registered
    with patch(CLOCK, return_value=AT + timedelta(seconds=1)):
        return journal.predict(prediction, expected_head=registration.sha256, input_document=INPUT)


def test_generated_full_disk_workflow():
    proof = generated_proof()
    assert proof["verified_receipts"] == 3
    assert len(proof["refusals"]) == 7
    assert proof["clock"] == "simulated_future_for_generated_proof"
    assert proof["trusted_attestation"] is False


@pytest.mark.parametrize("field", ["subject_id", "as_of", "metrics", "resolution"])
def test_exact_request_refused(registered, field):
    journal, registration, _, prediction = registered
    raw = prediction.request.model_dump(mode="json")
    changes = {
        "subject_id": "synthetic-other",
        "as_of": (AT + timedelta(seconds=1)).isoformat(),
        "metrics": ["steps"],
        "resolution": "hour",
    }
    raw[field] = changes[field]
    if field == "resolution":
        del raw["horizon_days"]
        raw["horizon_hours"] = 24
    bad = prediction.model_copy(
        update={"request": ReportRequest.model_validate_json(json.dumps(raw))}
    )
    with patch(CLOCK, return_value=AT + timedelta(seconds=2)), pytest.raises(ProspectiveRefused):
        journal.predict(bad, expected_head=registration.sha256, input_document=INPUT)
    assert len(journal.verify(registration.sha256)) == 1


@pytest.mark.parametrize(
    "field", ["artifact", "dataset_snapshot", "git_sha", "data_mode", "window"]
)
def test_wrong_identity_and_window_refused(registered, field):
    journal, registration, _, prediction = registered
    raw = prediction.result.model_dump(mode="json")
    if field in {"artifact", "dataset_snapshot"}:
        key = "artifact_sha256" if field == "artifact" else "snapshot_sha256"
        raw["provenance"][field][key] = "a" * 64
    elif field == "window":
        p = raw["forecast"]["series"][0]["points"][0]
        p["interval_start_utc"] = prediction.window_end_utc.isoformat()
        p["interval_end_utc"] = (prediction.window_end_utc + timedelta(days=1)).isoformat()
        p["local_date"] = prediction.window_end_utc.date().isoformat()
    else:
        raw[field] = "a" * 40 if field == "git_sha" else "real"
    bad = prediction.model_copy(
        update={"result": ReportResult.model_validate_json(json.dumps(raw))}
    )
    with patch(CLOCK, return_value=AT + timedelta(seconds=2)), pytest.raises(ProspectiveRefused):
        journal.predict(bad, expected_head=registration.sha256, input_document=INPUT)


@pytest.mark.parametrize("seconds", [-2, 301, 86400])
def test_clock_rollback_backfill_and_late_window(registered, seconds):
    journal, registration, _, prediction = registered
    with (
        patch(CLOCK, return_value=AT + timedelta(seconds=seconds)),
        pytest.raises(ProspectiveRefused),
    ):
        journal.predict(prediction, expected_head=registration.sha256, input_document=INPUT)


def test_competing_writers_one_append_and_no_implicit_retry(registered):
    journal, registration, _, prediction = registered

    def append():
        try:
            journal.predict(prediction, expected_head=registration.sha256, input_document=INPUT)
            return "saved"
        except ProspectiveRefused:
            return "refused"

    with patch(CLOCK, return_value=AT + timedelta(seconds=1)), ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: append(), range(2)))
    assert sorted(results) == ["refused", "saved"]
    assert len(list(journal.root.iterdir())) == 2


def test_tail_deletion_and_recomputed_chain_fail_retained_pin(registered):
    journal, _, _, prediction = registered
    saved = save(registered)
    raw = document_bytes(saved)
    path = journal.root / "00000001.json"
    path.unlink()
    with pytest.raises(ProspectiveRefused):
        journal.verify(saved.sha256)
    path.write_bytes(raw)
    path.chmod(0o600)
    modified = saved.body.model_copy(
        update={"payload": prediction.model_copy(update={"input_sha256": "a" * 64})}
    )
    path.write_bytes(document_bytes(Receipt(body=modified, sha256=document_sha256(modified))))
    with pytest.raises(ProspectiveRefused, match="externally retained"):
        journal.verify(saved.sha256)


@pytest.mark.parametrize(
    "failure", ["symlink", "hardlink", "public_file", "public_directory", "partial", "fifo"]
)
def test_unsafe_or_interrupted_receipt_fails_closed(registered, tmp_path, failure):
    journal, registration, _, _ = registered
    path = journal.root / "00000000.json"
    if failure == "symlink":
        other = tmp_path / "target"
        path.rename(other)
        path.symlink_to(other)
    elif failure == "hardlink":
        os.link(path, tmp_path / "other")
    elif failure == "fifo":
        path.unlink()
        os.mkfifo(path, 0o600)
    elif failure == "public_file":
        path.chmod(0o644)
    elif failure == "public_directory":
        journal.root.chmod(0o755)
    else:
        (journal.root / "00000001.json").write_bytes(b'{"interrupted":')
    with pytest.raises(ProspectiveRefused):
        journal.verify(registration.sha256)


def test_missing_and_null_measurements_are_preserved(registered):
    journal, _, _, prediction = registered
    saved = save(registered)
    follow_up = outcome(prediction, saved.sha256)
    aggregate = follow_up.aggregates[0].model_copy(
        update={
            "value": None,
            "null_reason": "no_observations",
            "observed_count": 0,
            "coverage": 0.0,
            "source_ids": [],
        }
    )
    follow_up = follow_up.model_copy(
        update={
            "aggregates": [aggregate],
            "outcome_document_sha256": document_sha256([aggregate]),
        }
    )
    with patch(CLOCK, return_value=follow_up.recorded_at_utc):
        final = journal.follow_up(
            follow_up,
            expected_head=saved.sha256,
            outcome_document=document_bytes(follow_up.aggregates),
        )
    restored = journal.verify(final.sha256)[-1].body.payload
    assert restored.aggregates[0].value is None
    assert restored.aggregates[0].null_reason == "no_observations"


@pytest.mark.parametrize(
    "mutation", ["subject", "aggregate_window", "aggregation", "missing", "real", "outcome_hash"]
)
def test_follow_up_refusals(registered, mutation):
    journal, _, _, prediction = registered
    saved = save(registered)
    follow_up = outcome(prediction, saved.sha256)
    if mutation == "subject":
        follow_up = follow_up.model_copy(
            update={
                "aggregates": [
                    follow_up.aggregates[0].model_copy(update={"subject_id": "synthetic-other"})
                ]
            }
        )
    elif mutation == "aggregate_window":
        follow_up = follow_up.model_copy(
            update={
                "aggregates": [
                    follow_up.aggregates[0].model_copy(
                        update={"interval_end_utc": prediction.window_end_utc + timedelta(days=1)}
                    )
                ]
            }
        )
    elif mutation == "aggregation":
        follow_up = follow_up.model_copy(
            update={
                "aggregates": [follow_up.aggregates[0].model_copy(update={"aggregation": "median"})]
            }
        )
    elif mutation == "missing":
        follow_up = follow_up.model_copy(update={"status": "missing"})
    elif mutation == "real":
        follow_up = follow_up.model_copy(update={"data_mode": "real"})
    else:
        follow_up = follow_up.model_copy(update={"outcome_document_sha256": "a" * 64})
    with patch(CLOCK, return_value=follow_up.recorded_at_utc), pytest.raises(ProspectiveRefused):
        journal.follow_up(
            follow_up,
            expected_head=saved.sha256,
            outcome_document=document_bytes(follow_up.aggregates),
        )
    assert len(journal.verify(saved.sha256)) == 2


def test_cli_error_never_prints_private_path_or_invalid_payload(tmp_path):
    private = tmp_path / "PRIVATE-ID-AND-SECRET.json"
    private.write_text('{"subject_id":"PRIVATE-ID-AND-SECRET"}')
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hachi.evaluation.prospective",
            "register",
            str(tmp_path / "output"),
            str(private),
            str(private),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "PRIVATE-ID-AND-SECRET" not in result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "refused"


def test_git_directory_output_refused(registered):
    _, _, protocol, _ = registered
    with pytest.raises(ProspectiveRefused, match="outside Git"):
        Journal.create(Path.cwd() / "forbidden-private-journal", protocol, analysis_plan=PLAN)


def test_cross_dataset_follow_up_cannot_alias_same_subject(registered):
    journal, _, _, prediction = registered
    saved = save(registered)
    follow_up = outcome(prediction, saved.sha256)
    aggregates = [follow_up.aggregates[0].model_copy(update={"dataset_id": "synthetic-unrelated"})]
    follow_up = follow_up.model_copy(
        update={
            "outcome_snapshot": follow_up.outcome_snapshot.model_copy(
                update={"dataset_id": "synthetic-unrelated"}
            ),
            "aggregates": aggregates,
            "outcome_document_sha256": document_sha256(aggregates),
        }
    )
    with (
        patch(CLOCK, return_value=follow_up.recorded_at_utc),
        pytest.raises(ProspectiveRefused, match="same source dataset"),
    ):
        journal.follow_up(
            follow_up, expected_head=saved.sha256, outcome_document=document_bytes(aggregates)
        )


def test_pre_window_withdrawal_preserves_actual_censor_time(registered):
    journal, _, _, prediction = registered
    saved = save(registered)
    follow_up = outcome(prediction, saved.sha256).model_copy(
        update={
            "status": "right_censored",
            "recorded_at_utc": AT + timedelta(seconds=3),
            "observed_through_utc": AT + timedelta(seconds=2),
            "aggregates": [],
            "missing_reason": "withdrawn",
            "outcome_document_sha256": document_sha256([]),
        }
    )
    with patch(CLOCK, return_value=AT + timedelta(seconds=3)):
        final = journal.follow_up(
            follow_up, expected_head=saved.sha256, outcome_document=document_bytes([])
        )
    restored = journal.verify(final.sha256)[-1].body.payload
    assert restored.status == "right_censored"
    assert restored.observed_through_utc < prediction.window_start_utc


def test_capacity_refusal_preserves_verifiable_head(registered):
    journal, _, _, prediction = registered
    saved = save(registered)
    follow_up = outcome(prediction, saved.sha256)
    with (
        patch("hachi.evaluation.prospective.journal.MAX_RECEIPTS", 2),
        patch(CLOCK, return_value=follow_up.recorded_at_utc),
    ):
        with pytest.raises(ProspectiveRefused, match="capacity"):
            journal.follow_up(
                follow_up,
                expected_head=saved.sha256,
                outcome_document=document_bytes(follow_up.aggregates),
            )
        assert len(journal.verify(saved.sha256)) == 2
        assert len(list(journal.root.iterdir())) == 2


@pytest.mark.parametrize("status", ["ok", "unavailable"])
def test_clinical_success_refused_unavailable_retained(registered, status):
    journal, registration, _, prediction = registered
    request = ReportRequest.model_validate_json(
        json.dumps(
            {
                "schema_version": "0.1",
                "subject_id": prediction.request.root.subject_id,
                "as_of": AT.isoformat(),
                "task": "illness_onset",
                "horizon_hours": 24,
            }
        )
    )
    name = "ok-illness-onset.json" if status == "ok" else "unavailable-illness-onset.json"
    raw = json.loads((Path.cwd() / "contracts/fixtures/ReportResult" / name).read_bytes())
    raw.update(
        {
            "subject_id": request.root.subject_id,
            "as_of": AT.isoformat(),
            "generated_at_utc": AT.isoformat(),
            "git_sha": "0" * 40,
            "data_mode": "synthetic",
        }
    )
    if status == "unavailable":
        raw["provenance"] = None
    result = ReportResult.model_validate_json(json.dumps(raw))
    changed = prediction.model_copy(update={"request": request, "result": result})
    with patch(CLOCK, return_value=AT + timedelta(seconds=1)):
        if status == "ok":
            with pytest.raises(ProspectiveRefused, match="clinical"):
                journal.predict(changed, expected_head=registration.sha256, input_document=INPUT)
        else:
            saved = journal.predict(
                changed, expected_head=registration.sha256, input_document=INPUT
            )
            assert journal.verify(saved.sha256)[-1].body.payload.result.root.status == "unavailable"


@pytest.mark.parametrize(
    "arguments", [["generated-proof", "SYNTHETIC-PRIVATE-PATH"], ["SYNTHETIC-PRIVATE-PATH"]]
)
def test_cli_argument_errors_do_not_echo_private_values(arguments):
    result = subprocess.run(
        [sys.executable, "-m", "hachi.evaluation.prospective", *arguments],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "SYNTHETIC-PRIVATE-PATH" not in result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "refused"


def test_mutated_canonical_nested_list_refused_before_append(registered):
    journal, registration, _, prediction = registered
    series = prediction.result.root.forecast.series[0]
    series.points.append(series.points[0])
    with (
        patch(CLOCK, return_value=AT + timedelta(seconds=1)),
        pytest.raises(ProspectiveRefused, match="canonical contracts"),
    ):
        journal.predict(prediction, expected_head=registration.sha256, input_document=INPUT)
    assert len(journal.verify(registration.sha256)) == 1
    assert len(list(journal.root.iterdir())) == 1


def test_saved_return_payload_detaches_caller_lists(registered):
    journal, _, _, prediction = registered
    saved = save(registered)
    prediction.result.root.forecast.series.clear()
    assert len(saved.body.payload.result.root.forecast.series) == 1
    assert len(journal.verify(saved.sha256)) == 2
