"""Prove private context transport/fold joins without inference or sealed rows."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa

from hachi.evaluation.clinical_protocol import ClinicalProtocol
from hachi.evaluation.folds import NestedFoldConfig, nested_participant_folds
from hachi.evaluation.serialization import document_bytes, document_sha256
from hachi.models.chronos.inference import read_requests
from hachi.models.illness.context_export import export, verify_packet
from hachi.models.illness.hourly import NativePoint, NativeSeries, load_context_protocol


def test_export_actual_chronos_boundary_private_folds_and_sealed_reads(tmp_path, monkeypatch):
    import hachi.models.illness.context_export as module

    config = NestedFoldConfig(outer_folds=4, inner_folds=3, min_train_subjects=4, seed=42)
    plan = nested_participant_folds([f"synthetic-{i}" for i in range(24)], config)
    source_protocol = load_context_protocol(
        Path("configs/experiments/illness/clinical-contexts.toml")
    )
    protocol = source_protocol.model_copy(
        update={
            "context_hours": 1,
            "min_observed_hr_hours": 1,
            "nested_plan_sha256": document_sha256(plan),
        }
    )
    clinical = ClinicalProtocol(
        compatible_snapshots=[
            {
                "dataset_id": protocol.dataset_id,
                "dataset_version": "2020-nbe",
                "snapshot_sha256": protocol.snapshot_sha256,
            }
        ],
        clock=protocol.clock,
        roster="all_subjects_before_task_eligibility",
        folds=config,
        active_outer_fold=0,
        nested_plan_sha256=document_sha256(plan),
        split_created_at_utc=datetime(2026, 10, 11, 11, 45, tzinfo=UTC),
    )
    clinical_path = tmp_path / "clinical.json"
    clinical_path.write_bytes(document_bytes(clinical))
    monkeypatch.setattr(module, "load_context_protocol", lambda _: protocol)
    monkeypatch.setattr(module, "clinical_fold_plan", lambda *args: plan)
    monkeypatch.setattr(module, "dataset_snapshot_ref", lambda _: clinical.compatible_snapshots[0])
    monkeypatch.setattr(module, "verify_archive", lambda *args: "a" * 64)
    monkeypatch.setattr(
        module.subprocess,
        "check_output",
        lambda args, **kwargs: "" if "--porcelain" in args else "a" * 40,
    )
    active = [f for f in plan.folds if f.outer_fold == 0]
    development = {s for f in active for s in f.validation_subjects}
    test = set(active[0].test_subjects)
    contributors = sorted(development)[:2]
    cutoff = datetime(2020, 1, 2, tzinfo=UTC)

    def guarded(snapshot, name, selected):
        assert set(selected) == development and not test & set(selected)
        assert name == "onset_windows"
        rows = [
            {
                "subject_id": s,
                "cutoff_utc": cutoff,
                **{f"onset_{h}h": "negative" for h in (24, 48, 72)},
            }
            for s in contributors
        ]
        return pa.Table.from_pylist(rows)

    monkeypatch.setattr(module, "read_table", guarded)

    def native(archive, subject, cutoffs, protocol):
        assert subject in development and subject not in test and cutoffs == [cutoff]
        rows = tuple(
            NativePoint(
                at=cutoff - timedelta(minutes=m),
                available_at=cutoff - timedelta(minutes=m),
                metric="heart_rate",
                value=60.0,
            )
            for m in range(1, 31)
        )
        return NativeSeries(rows, {"heart_rate:bounded_points": 30}, "b" * 64)

    monkeypatch.setattr(module, "read_native_context", native)
    output = tmp_path / "packet"
    summary = export(tmp_path, tmp_path / "native.zip", output, tmp_path, clinical_path)
    assert summary["unique_requests"] == 1  # identical physiology deduplicates across people
    assert summary["counts"]["eligible_cutoffs"] == 2
    assert summary["outer_test_status"] == "sealed" and summary["inference_status"] == "not_run"
    requests = read_requests(output / "requests.jsonl")
    assert len(requests) == 1 and requests[0].context == [60.0]
    rows = [json.loads(row) for row in (output / "requests.jsonl").read_text().splitlines()]
    assert set(rows[0]) == {"request_id", "context", "prediction_length"}
    encoder = json.loads((output / "encoder-requests.jsonl").read_text())
    encoder_id = encoder.pop("request_sha256")
    assert encoder_id == document_sha256(encoder)
    assert encoder["channels"] == {"heart_rate": [60.0]}
    assert encoder["units"] == {"heart_rate": "bpm"}
    assert encoder["first_hour_local"] == 23  # synthetic one-hour context
    joins = json.loads((output / "joins.json").read_bytes())
    assert len(joins) == 6 and not test & {j["subject_id"] for j in joins}
    assert {j["encoder_request_sha256"] for j in joins} == {encoder_id}
    assert all("cutoff_floating" in j and "cutoff" not in j for j in joins)
    for subject in contributors:
        roles = [j["role"] for j in joins if j["subject_id"] == subject]
        assert roles.count("validation") == 1 and roles.count("train") == 2
    assert output.stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in output.iterdir())
    verification = verify_packet(tmp_path, output)
    assert verification["boundary_verification"]["private_fold_joins_checked"] == 6
    assert verification["boundary_verification"]["encoder_content_hashes_checked"] == 1
    # Extra physiology must not enter worker inputs without an eligible private join.
    import hashlib

    import pytest

    from hachi.models.chronos.inference import request_id

    names = ("requests.jsonl", "encoder-requests.jsonl", "summary.json", "joins.json")
    saved = {name: (output / name).read_bytes() for name in names}
    extra = {**encoder, "channels": {"heart_rate": [61.0]}}
    extra["request_sha256"] = document_sha256(extra)
    with (output / "encoder-requests.jsonl").open("ab") as stream:
        stream.write(document_bytes(extra))
    with (output / "requests.jsonl").open("ab") as stream:
        stream.write(
            document_bytes(
                {
                    "request_id": request_id([61.0], protocol.prediction_hours),
                    "context": [61.0],
                    "prediction_length": protocol.prediction_hours,
                }
            )
        )
    summary["unique_requests"] = summary["unique_encoder_requests"] = 2
    summary["request_file_sha256"] = hashlib.sha256(
        (output / "requests.jsonl").read_bytes()
    ).hexdigest()
    summary["encoder_request_file_sha256"] = hashlib.sha256(
        (output / "encoder-requests.jsonl").read_bytes()
    ).hexdigest()
    (output / "summary.json").write_bytes(document_bytes(summary))
    with pytest.raises(ValueError, match="without an eligible"):
        verify_packet(tmp_path, output)
    for name, payload in saved.items():
        (output / name).write_bytes(payload)
    # A claimed zero count cannot hide a nonempty Chronos file from the reader.
    summary = json.loads(saved["summary.json"])
    summary["unique_requests"] = summary["unique_encoder_requests"] = 0
    summary["counts"].update(requested_cutoffs=0, insufficient_hourly_context=2)
    (output / "encoder-requests.jsonl").write_bytes(b"")
    summary["encoder_request_file_sha256"] = hashlib.sha256(b"").hexdigest()
    (output / "summary.json").write_bytes(document_bytes(summary))
    empty_joins = [
        {**j, "request_id": None, "encoder_request_sha256": None, "observed_hr_hours": 0}
        for j in joins
    ]
    (output / "joins.json").write_bytes(document_bytes(empty_joins))
    with pytest.raises(ValueError, match="encoder and Chronos"):
        verify_packet(tmp_path, output)
    for name, payload in saved.items():
        (output / name).write_bytes(payload)

    # Changing active outer would read the originally sealed people. Reject before any read.
    def no_read(*args, **kwargs):
        pytest.fail("unfrozen plan reached private data")

    monkeypatch.setattr(module, "clinical_fold_plan", no_read)
    monkeypatch.setattr(module, "read_table", no_read)
    monkeypatch.setattr(module, "verify_archive", no_read)
    clinical_path.write_bytes(document_bytes(clinical.model_copy(update={"active_outer_fold": 1})))
    with pytest.raises(ValueError, match="frozen outer0"):
        export(tmp_path, tmp_path / "native.zip", tmp_path / "rejected", tmp_path, clinical_path)
    assert not (tmp_path / "rejected").exists()


def test_context_summary_rejects_private_payloads():
    import pytest
    from pydantic import ValidationError

    from hachi.models.illness.context_export import ContextSummary

    summary = json.loads(Path("reports/models/illness/clinical-contexts.json").read_bytes())
    summary.pop("boundary_verification")
    ContextSummary.model_validate_json(json.dumps(summary))
    summary["git_sha"] = {"synthetic-private-rows": [60.0]}
    with pytest.raises(ValidationError):
        ContextSummary.model_validate_json(json.dumps(summary))
