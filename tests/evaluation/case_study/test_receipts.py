"""Meaningful refusal properties on generated inputs, without real case acceptance."""

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from hachi.api.catalog import Catalog
from hachi.api.service import Service
from hachi.api.settings import Settings
from hachi.contracts.api import ImportStatus
from hachi.contracts.base import ArtifactRef, DatasetSnapshotRef
from hachi.contracts.results import (
    ForecastPayload,
    ForecastPoint,
    ForecastSeries,
    PartialProvenance,
    PhysiologyForecastResult,
    Provenance,
    ReportResult,
)
from hachi.data.apple_health import ImportConfig
from hachi.evaluation.case_study import lifecycle as flow
from hachi.evaluation.case_study.__main__ import main
from hachi.evaluation.case_study.specification import (
    Consent,
    InputPins,
    Prespecification,
    ResultBatch,
)
from hachi.evaluation.case_study.synthetic import fixture, parser_seam, unavailable_batch
from hachi.evaluation.serialization import document_sha256
from hachi.storage import Metadata, Workspace, private_directory


@pytest.fixture
def prepared(tmp_path):
    # Isolated generated repository allows mutation probes without changing this checkout.
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src/hachi").mkdir(parents=True)
    (repo / "src/hachi/generated.py").write_text("# synthetic source\n")
    (repo / "pyproject.toml").write_text("# synthetic toolchain\n")
    (repo / "uv.lock").write_text("# synthetic lock\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Synthetic",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "Generated fixture",
        ],
        cwd=repo,
        check=True,
    )
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    inputs = private / "inputs"
    spec = fixture(inputs, repo)
    root = private / "receipts"
    pin = flow.preregister(spec, inputs, repo, root)
    batch = unavailable_batch(spec, flow.source_snapshot(repo))
    return repo, inputs, spec, root, pin, batch


def test_complete_readback_and_separate_presentation_permission(prepared):
    repo, inputs, spec, root, pin, batch = prepared
    sealed = flow.seal(root, pin, batch, inputs, repo)
    opened = flow.reveal(root, pin, sealed, inputs, repo)
    proof = flow.verify(root, pin, sealed, opened, inputs, repo)
    assert proof["unavailable_results"] == proof["results"] == 8
    assert proof["clinical_case_status"] == "unavailable"
    assert proof["presentation_consent"] == "unavailable"
    assert proof["source_git_sha"] == flow.source_snapshot(repo).git_sha
    for path in root.rglob("*"):
        assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)
    with pytest.raises(FileExistsError):
        flow.preregister(spec, inputs, repo, root)
    with pytest.raises(FileExistsError):
        flow.reveal(root, pin, sealed, inputs, repo)
    with pytest.raises(flow.CaseRefused, match="after reveal"):
        flow.seal(root, pin, batch, inputs, repo)


def test_real_mode_refuses_current_false_freeze_even_with_processing_metadata(prepared):
    repo, inputs, spec, root, _, _ = prepared
    real = Prespecification.model_validate_json(
        spec.model_dump_json().replace('"data_mode":"synthetic"', '"data_mode":"real"')
    )
    assert json.loads((inputs / "freeze.json").read_bytes())["final_test_authorized"] is False
    with pytest.raises(flow.CaseRefused, match="final_test_authorized=false"):
        flow.preregister(real, inputs, repo, root.parent / "real")
    assert not (root.parent / "real").exists()


def test_foreign_input_snapshot_cannot_be_sealed(prepared):
    repo, inputs, spec, root, pin, batch = prepared
    values = batch.model_dump(mode="json")
    values["results"][0]["result"]["provenance"] = PartialProvenance(
        dataset_snapshot=DatasetSnapshotRef(
            dataset_id="foreign-tail", dataset_version="synthetic-1", snapshot_sha256="f" * 64
        ),
        artifact=spec.system.artifact,
        feature_coverage=[],
    ).model_dump(mode="json")
    changed = ResultBatch.model_validate_json(json.dumps(values))
    with pytest.raises(flow.CaseRefused, match="snapshot"):
        flow.seal(root, pin, changed, inputs, repo)


def test_canonical_import_identity_is_distinct_from_sqlite_byte_pin(prepared):
    _, inputs, spec, _, _, _ = prepared
    config = ImportConfig.model_validate_json((inputs / "import-config.json").read_bytes())
    version = "apple-health-import-1"
    canonical = DatasetSnapshotRef(
        dataset_id=config.dataset_id,
        dataset_version=version,
        snapshot_sha256=document_sha256(
            {"xml_sha256": spec.inputs.export_xml.sha256, "config": config, "importer": version}
        ),
    )
    values = spec.inputs.model_dump(mode="json")
    values["dataset_snapshot"] = canonical.model_dump(mode="json")
    pins = InputPins.model_validate(values)
    assert pins.dataset_snapshot.snapshot_sha256 != pins.import_snapshot.sha256
    assert pins.dataset_snapshot == spec.inputs.dataset_snapshot


def test_generated_service_import_matches_pinned_case_identity_and_seals(prepared):
    repo, inputs, spec, root, pin, batch = prepared
    workspace = Workspace("NavyDune", root.parent / "service")
    private_directory(workspace.state)
    directory = private_directory(workspace.import_directory("imp-synthetic-parity"))
    (directory / "upload.xml").write_bytes((inputs / "export.xml").read_bytes())
    metadata = Metadata(workspace.default_database)
    try:
        now = datetime.now(UTC).replace(microsecond=0)
        status = ImportStatus(
            schema_version="0.1",
            import_id="imp-synthetic-parity",
            subject_id=spec.requests[0].root.subject_id,
            declared_tz_name="UTC",
            source_format="apple_health_export_xml",
            data_mode="synthetic",
            state="pending",
            created_at_utc=now,
            updated_at_utc=now,
            counts=None,
            record_issues=[],
            failure=None,
        )
        metadata.insert_import("generated-parity", spec.inputs.export_xml.sha256, status)
        service = Service(
            Settings(
                owner="NavyDune",
                workspace=workspace,
                database=workspace.default_database,
                git_sha=flow.source_snapshot(repo).git_sha,
                artifact_root=workspace.root / "unused-artifacts",
            ),
            metadata,
            Catalog(),
        )
        # Direct CPU import only: no server, background runner, catalog reads or inference.
        service.run_import(status.import_id)
        imported = metadata.get_import(status.import_id)
        assert imported is not None and imported.status.state == "succeeded"
        assert imported.snapshot == spec.inputs.dataset_snapshot
        values = batch.model_dump(mode="json")
        values["results"][0]["result"]["provenance"]["dataset_snapshot"] = (
            imported.snapshot.model_dump(mode="json")
        )
        flow.seal(root, pin, ResultBatch.model_validate_json(json.dumps(values)), inputs, repo)
    finally:
        metadata.close()


@pytest.mark.parametrize("field", ["dataset_version", "snapshot_sha256"])
def test_incorrect_canonical_identity_refuses_preregistration(prepared, field):
    repo, inputs, spec, root, _, _ = prepared
    values = spec.model_dump(mode="json")
    values["inputs"]["dataset_snapshot"][field] = (
        "foreign-version" if field == "dataset_version" else spec.inputs.import_snapshot.sha256
    )
    changed = Prespecification.model_validate_json(json.dumps(values))
    with pytest.raises(flow.CaseRefused, match="canonical import snapshot identity"):
        flow.preregister(changed, inputs, repo, root.parent / "wrong-identity")


def test_input_export_mutation_cannot_be_sealed(prepared):
    repo, inputs, _, root, pin, batch = prepared
    (inputs / "export.xml").write_bytes(b"changed generated export\n")
    with pytest.raises(flow.CaseRefused, match="input document"):
        flow.seal(root, pin, batch, inputs, repo)


@pytest.mark.parametrize("document", ["import-config.json", "import.sqlite3"])
def test_pinned_import_input_mutation_cannot_be_sealed(prepared, document):
    repo, inputs, _, root, pin, batch = prepared
    (inputs / document).write_bytes(b"changed generated import input\n")
    with pytest.raises(flow.CaseRefused, match="input document"):
        flow.seal(root, pin, batch, inputs, repo)


def test_import_config_must_match_snapshot_metadata_even_with_a_new_config_pin(prepared):
    repo, inputs, spec, root, _, _ = prepared
    raw = flow.document_bytes(
        json.loads((inputs / "import-config.json").read_bytes())
        | {"source_priority": ["changed-generated-priority"]}
    )
    (inputs / "import-config.json").write_bytes(raw)
    values = spec.model_dump(mode="json")
    values["inputs"]["import_config"]["sha256"] = flow.digest(raw)
    changed = Prespecification.model_validate_json(json.dumps(values))
    with pytest.raises(flow.CaseRefused, match="export and config"):
        flow.preregister(changed, inputs, repo, root.parent / "changed-config")


def forecast_batch(spec, batch, *, hours=24, shift=0, resolution="hour", snapshot=None):
    """Constant generated physiology values only, never illness probabilities."""
    original = batch.results[0]
    base = original.result.root.model_dump(exclude={"reason_code", "requirements", "provenance"})
    start = original.result.root.as_of + timedelta(hours=shift)
    if resolution == "hour":
        points = [
            ForecastPoint(
                interval_start_utc=start + timedelta(hours=i),
                interval_end_utc=start + timedelta(hours=i + 1),
                local_date=None,
                median=65.0,
                lower=None,
                upper=None,
            )
            for i in range(hours)
        ]
    else:
        start = datetime(2026, 1, 8, tzinfo=UTC)
        points = [
            ForecastPoint(
                interval_start_utc=start,
                interval_end_utc=start + timedelta(days=1),
                local_date=start.date(),
                median=65.0,
                lower=None,
                upper=None,
            )
        ]
    result = PhysiologyForecastResult(
        **{**base, "status": "ok"},
        provenance=Provenance(
            dataset_snapshot=snapshot or spec.inputs.dataset_snapshot,
            artifact=spec.system.artifact,
            feature_coverage=[],
        ),
        forecast=ForecastPayload(
            resolution=resolution,
            tz_name="UTC" if resolution == "day" else None,
            series=[
                ForecastSeries(
                    metric="heart_rate",
                    unit="bpm",
                    nominal_coverage=None,
                    interval_calibration="none",
                    baseline=None,
                    points=points,
                )
            ],
            unavailable_metrics=[],
        ),
    )
    changed = original.model_copy(update={"result": ReportResult(result)})
    return ResultBatch(results=[changed, *batch.results[1:]])


def test_canonical_forecast_request_and_dataset_success(prepared):
    repo, inputs, spec, root, pin, batch = prepared
    matched = forecast_batch(spec, batch)
    sealed = flow.seal(root, pin, matched, inputs, repo)
    opened = flow.reveal(root, pin, sealed, inputs, repo)
    assert flow.verify(root, pin, sealed, opened, inputs, repo)["unavailable_results"] == 7


@pytest.mark.parametrize(
    "change", ["horizon", "resolution", "window", "snapshot", "request_hash", "subject"]
)
def test_canonical_result_cannot_change_pinned_request_or_input(prepared, change):
    repo, inputs, spec, root, pin, batch = prepared
    if change == "horizon":
        changed = forecast_batch(spec, batch, hours=23)
    elif change == "resolution":
        changed = forecast_batch(spec, batch, resolution="day")
    elif change == "window":
        changed = forecast_batch(spec, batch, shift=1)
    elif change == "snapshot":
        changed = forecast_batch(
            spec,
            batch,
            snapshot=DatasetSnapshotRef(
                dataset_id="foreign-tail", dataset_version="synthetic-1", snapshot_sha256="f" * 64
            ),
        )
    else:
        values = batch.model_dump(mode="json")
        if change == "subject":
            values["results"][0]["result"]["subject_id"] = "foreign-subject"
        else:
            request = spec.requests[0].model_dump(mode="json")
            request["horizon_hours"] = 1
            values["results"][0]["request_sha256"] = document_sha256(request)
        changed = ResultBatch.model_validate_json(json.dumps(values))
    with pytest.raises(flow.CaseRefused):
        flow.seal(root, pin, changed, inputs, repo)
    assert not (root / "predictions_sealed").exists()


def test_half_open_outcome_boundary_is_descriptive_and_not_a_negative_label(prepared):
    _, _, spec, _, _, _ = prepared
    assert spec.outcome_rule.interpretation == "descriptive_containment_not_clinical_labels"
    assert [flow.onset_window_relation(spec, c.as_of_utc, 72) for c in spec.cutoffs] == [
        "interval_outside",
        "interval_inside",
        "interval_inside",
    ]
    lower = spec.onset.lower_utc
    exact = spec.model_copy(update={"onset": spec.onset.model_copy(update={"upper_utc": lower})})
    assert flow.onset_window_relation(exact, lower, 24) == "interval_inside"
    assert flow.onset_window_relation(exact, lower - timedelta(hours=24), 24) == "interval_outside"
    crossing = spec.model_copy(
        update={"onset": spec.onset.model_copy(update={"upper_utc": lower + timedelta(hours=24)})}
    )
    assert flow.onset_window_relation(crossing, lower, 24) == "partial_overlap"


def test_healthy_gap_and_explicit_absence_commitment(prepared):
    repo, inputs, spec, root, _, _ = prepared
    values = spec.model_dump(mode="json")
    values["outcome_rule"]["minimum_healthy_gap_hours"] = 169
    with pytest.raises(ValidationError, match="minimum gap"):
        Prespecification.model_validate_json(json.dumps(values))
    timeline_path = inputs / "timeline.json"
    timeline = json.loads(timeline_path.read_bytes())
    timeline["healthy_assertions"][0]["period_end_utc"] = "2026-01-03T11:00:00Z"
    raw = flow.document_bytes(timeline)
    timeline_path.write_bytes(raw)
    values = spec.model_dump(mode="json")
    values["onset"]["sealed_timeline"]["sha256"] = flow.digest(raw)
    changed = Prespecification.model_validate_json(json.dumps(values))
    with pytest.raises(flow.CaseRefused, match="healthy comparisons"):
        flow.preregister(changed, inputs, repo, root.parent / "bad-healthy")


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "cutoff", "source", "artifact", "time", "mode"]
)
def test_prediction_selection_and_identity_refusals(prepared, change):
    repo, inputs, _, root, pin, batch = prepared
    values = batch.model_dump(mode="json")
    rows = values["results"]
    match change:
        case "missing":
            rows.pop()
        case "duplicate":
            rows[-1] = rows[0]
        case "cutoff":
            rows[0]["result"]["as_of"] = "2026-01-07T12:00:01Z"
        case "source":
            rows[0]["result"]["git_sha"] = "f" * 40
        case "time":
            rows[0]["result"]["generated_at_utc"] = "2026-01-01T00:00:00Z"
        case "mode":
            rows[0]["result"]["data_mode"] = "real"
        case "artifact":
            rows[0]["result"]["provenance"] = PartialProvenance(
                dataset_snapshot=None,
                artifact=ArtifactRef(artifact_id="changed", artifact_sha256="f" * 64),
                feature_coverage=[],
            ).model_dump(mode="json")
    changed = ResultBatch.model_validate_json(json.dumps(values))
    with pytest.raises(flow.CaseRefused):
        flow.seal(root, pin, changed, inputs, repo)
    assert not (root / "predictions_sealed").exists()


@pytest.mark.parametrize(
    "document",
    [
        "model.json",
        "config.json",
        "feature-source.json",
        "compatibility.json",
        "timeline.json",
        "processing.json",
        "freeze.json",
    ],
)
def test_bound_input_mutation_refused_before_seal(prepared, document):
    repo, inputs, _, root, pin, batch = prepared
    (inputs / document).write_bytes(b"{}\n")
    with pytest.raises(flow.CaseRefused, match="input document"):
        flow.seal(root, pin, batch, inputs, repo)


def test_source_and_commit_mutation_refused(prepared):
    repo, inputs, _, root, pin, batch = prepared
    source = repo / "src/hachi/generated.py"
    source.write_text("# changed\n")
    with pytest.raises(flow.CaseRefused, match="original source"):
        flow.seal(root, pin, batch, inputs, repo)
    source.write_text("# synthetic source\n")
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Synthetic",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "Changed commit",
        ],
        cwd=repo,
        check=True,
    )
    with pytest.raises(flow.CaseRefused, match="producing commit"):
        flow.seal(root, pin, batch, inputs, repo)


def test_external_pins_detect_receipt_and_result_rewrite(prepared):
    repo, inputs, _, root, pin, batch = prepared
    sealed = flow.seal(root, pin, batch, inputs, repo)
    with pytest.raises(flow.CaseRefused, match="external pin"):
        flow.reveal(root, pin, "f" * 64, inputs, repo)
    result = root / "predictions_sealed/results.json"
    result.write_bytes(result.read_bytes() + b" ")
    with pytest.raises(flow.CaseRefused, match="payload"):
        flow.reveal(root, pin, sealed, inputs, repo)
    assert not (root / "revealed").exists()


def test_clock_regression_and_saved_receipt_time_mutation_refused(prepared, monkeypatch):
    repo, inputs, _, root, pin, batch = prepared
    raw = (root / "prespecified/receipt.json").read_bytes()
    before = flow.Receipt.model_validate_json(raw)
    monkeypatch.setattr(flow, "_now", lambda: before.observed_at_utc - timedelta(seconds=1))
    with pytest.raises(flow.CaseRefused, match="system clock"):
        flow.seal(root, pin, batch, inputs, repo)
    monkeypatch.undo()
    receipt = root / "prespecified/receipt.json"
    receipt.write_bytes(raw.replace(b'"observed_at_utc":', b'"changed_clock":'))
    with pytest.raises(flow.CaseRefused, match="external pin"):
        flow.seal(root, pin, batch, inputs, repo)


@pytest.mark.parametrize("kind", ["permissions", "symlink", "hardlink"])
def test_private_input_storage_refusals(prepared, kind):
    repo, inputs, _, root, pin, batch = prepared
    path = inputs / "model.json"
    if kind == "permissions":
        path.chmod(0o644)
    elif kind == "hardlink":
        os.link(path, inputs / "linked.json")
    else:
        path.rename(inputs / "original.json")
        path.symlink_to("original.json")
    with pytest.raises(flow.CaseRefused):
        flow.seal(root, pin, batch, inputs, repo)


def test_specification_refuses_posthoc_cutoffs_and_missing_consent_evidence(prepared):
    _, _, spec, _, _, _ = prepared
    values = spec.model_dump(mode="json")
    values["cutoffs"][0]["as_of_utc"] = "2026-01-07T12:00:01Z"
    with pytest.raises(ValidationError, match="sealed lower"):
        Prespecification.model_validate_json(json.dumps(values))
    with pytest.raises(ValidationError, match="separately recorded"):
        Consent(status="granted", evidence=None, recorded_at_utc=None)


def test_generated_raw_parser_and_pre_transform_seam(tmp_path):
    proof = parser_seam(tmp_path / "generated")
    assert proof["records_seen"] == 6
    assert proof["visible_at_cutoff"] == 2
    assert proof["hourly_prefix_unchanged_after_tail"] is True


def test_actual_cli_generated_lifecycle_and_sanitized_refusal(prepared, monkeypatch, capsys):
    _, inputs, _, root, _, _ = prepared
    repo = Path(__file__).resolve().parents[3]
    output = root.parent / "cli-proof"
    monkeypatch.setattr(
        "sys.argv", ["receipt", "synthetic-proof", "--repo", str(repo), "--output", str(output)]
    )
    assert main() == 0
    proof = json.loads(capsys.readouterr().out)
    assert proof == json.loads((output / "synthetic-proof.json").read_bytes())
    assert len(proof["refusals_verified"]) == 6
    assert main() == 2  # exclusive output; no overwrite even through the caller
    assert (
        capsys.readouterr().out == '{"status": "refused", "clinical_case_status": "unavailable"}\n'
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "receipt",
            "preregister",
            "--repo",
            str(repo),
            "--inputs",
            str(inputs),
            "--receipts",
            str(root.parent / "bad"),
            "--specification",
            "missing.json",
        ],
    )
    assert main() == 2
    assert str(inputs) not in capsys.readouterr().out
