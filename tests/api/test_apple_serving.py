"""Apple Health imports reach hourly-feature models only through an explicit admission."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from hachi.api.artifacts import (
    ArtifactRefused,
    ServingSpec,
    SourceAdmission,
    load_served_artifact,
    stage_artifact,
)
from hachi.api.sources import SubjectData
from hachi.contracts.api import Coverage, ReportJob
from hachi.contracts.manifests import TimeWindow
from hachi.data.apple_health.hourly import AVAILABILITY_RULE, apple_hourly_features
from hachi.evaluation import ForecastInput
from hachi.evaluation.features import hourly_features
from hachi.models.baselines import BaselineConfig
from hachi.models.density.rule import AppleMinuteThinning, ThinningRule

from .conftest import HR_POLICY, export_xml, heart_rate_record, make_packet, upload, wait

APPLE_POLICY = HR_POLICY.model_copy(update={"availability_rule": AVAILABILITY_RULE})
RATIONALE = "Synthetic transfer test: PMData-evaluated baseline applied to Apple Watch HR."
START = datetime(2026, 9, 1, tzinfo=UTC)
AS_OF = "2026-09-03T12:00:00Z"


def apple_hr_export(hours: int, every_minutes: int = 1) -> bytes:
    """Heart rate every `every_minutes`, created 30 s after each sample (sealed in its hour)."""
    records = []
    for minute in range(0, hours * 60, every_minutes):
        moment = START + timedelta(minutes=minute)
        value = 60 + (minute // 60) % 7 + (minute % 10) / 10
        stamp = moment.strftime("%Y-%m-%d %H:%M:%S +0000")
        created = (moment + timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S +0000")
        records.append(heart_rate_record(stamp, f"{value:.1f}", creationDate=created))
    return export_xml(records)


def admitting_serving(**changes) -> ServingSpec:
    return ServingSpec(
        format_version="hachi-serving-1",
        task="physiology_forecast",
        resolution="hour",
        entry_point="hachi.models.baselines.load_artifact",
        input="hourly_features",
        feature_policy=HR_POLICY,
        accepted_sources=[
            SourceAdmission(source="apple_health", feature_policy=APPLE_POLICY, rationale=RATIONALE)
        ],
    ).model_copy(update=changes)


@pytest.fixture
def apple_client(tmp_path, data_root, snapshot_id, open_client, make_settings):
    packet = make_packet(
        tmp_path / "apple-packet",
        data_root / "derived" / snapshot_id,
        serving=admitting_serving(),
        artifact_id="synthetic-last-valid-hr-apple",
    )
    root = tmp_path / "apple-artifacts"
    root.mkdir()
    pin = stage_artifact(root, packet.model_dir, packet.packet_dir, packet.serving, packet.protocol)
    client = open_client(make_settings(artifact_root=root, served_artifacts=(pin,)))
    return client, pin


def forecast(client, subject: str) -> ReportJob:
    body = {
        "schema_version": "0.1",
        "subject_id": subject,
        "as_of": AS_OF,
        "task": "physiology_forecast",
        "resolution": "hour",
        "horizon_hours": 24,
        "metrics": ["heart_rate"],
    }
    response = client.post("/v1/reports", json=body)
    assert response.status_code in (200, 202), response.text
    wait(client)
    return ReportJob.model_validate_json(
        client.get(f"/v1/reports/{response.json()['report_id']}").content
    )


def test_an_admitted_apple_import_is_forecast_end_to_end(apple_client):
    client, pin = apple_client
    imported = upload(client, apple_hr_export(72), subject="synthetic-apple-dense")
    assert imported.status_code == 202
    wait(client)
    assert client.get(f"/v1/imports/{imported.json()['import_id']}").json()["state"] == "succeeded"

    coverage = Coverage.model_validate_json(
        client.get("/v1/subjects/synthetic-apple-dense/coverage").content
    )
    assert coverage.history == "sufficient"
    support = {t.task: t for t in coverage.task_support}
    assert support["physiology_forecast"].supported

    job = forecast(client, "synthetic-apple-dense")
    result = job.result.root
    assert result.status == "ok", result
    assert result.provenance.artifact == pin
    assert result.provenance.dataset_snapshot.dataset_id == "synthetic-apple-health-export"
    shift = next(w for w in result.warnings if w.code == "DEVICE_SHIFT")
    assert "unvalidated transfer" in shift.message and RATIONALE in shift.message
    series = result.forecast.series[0]
    assert series.interval_calibration == "none"  # the baseline is point-only
    # last-valid repeats the sealed 11:00-12:00 Apple bin: 60 + (59 // 1 hour index) % 7 + 0.45
    assert series.points[0].median == pytest.approx(60 + (59 % 7) + 0.45)

    # The same input built directly from #78's sealed bins gives the same forecast.
    service = client.app.state.service
    served = service.catalog.artifacts[0]
    subject = service.catalog.subject("synthetic-apple-dense", service.metadata, service.workspace)
    cutoff = result.as_of
    history = apple_hourly_features(
        subject.path, APPLE_POLICY, cutoff, cutoff - timedelta(hours=48)
    ).features
    targets = tuple(
        TimeWindow(start_utc=cutoff + timedelta(hours=i), end_utc=cutoff + timedelta(hours=i + 1))
        for i in range(24)
    )
    direct = served.model.predict(ForecastInput("synthetic-apple-dense", cutoff, targets, history))
    assert [p.median for p in series.points] == [e.median for e in direct]


def test_a_model_that_does_not_admit_apple_says_so(client):
    upload(client, apple_hr_export(72), subject="synthetic-apple-dense")
    wait(client)
    result = forecast(client, "synthetic-apple-dense").result.root
    assert (result.status, result.reason_code) == ("unavailable", "NO_ARTIFACT_FOR_TASK")
    assert "admits Apple Health input" in result.requirements[0]
    assert "pmdata" in result.requirements[0]
    coverage = client.get("/v1/subjects/synthetic-apple-dense/coverage").json()
    forecast_support = next(
        t for t in coverage["task_support"] if t["task"] == "physiology_forecast"
    )
    assert forecast_support["reason_code"] == "NO_ARTIFACT_FOR_TASK"


def test_typical_watch_sampling_abstains_at_the_models_density_gates(apple_client):
    client, _ = apple_client
    upload(client, apple_hr_export(72, every_minutes=5), subject="synthetic-apple-sparse")
    wait(client)
    result = forecast(client, "synthetic-apple-sparse").result.root
    # 12 samples/hour fall below the artifact's 0.5 minute-density and 30-sample gates.
    assert (result.status, result.reason_code) == ("unavailable", "INSUFFICIENT_HISTORY")


def test_admissions_keep_the_model_target_and_their_own_readiness():
    with pytest.raises(ValidationError, match="sealed availability rule"):
        SourceAdmission(source="apple_health", feature_policy=HR_POLICY, rationale=RATIONALE)
    weaker = [
        APPLE_POLICY.model_copy(update={"metric": "steps", "aggregation": "sum"}),
        APPLE_POLICY.model_copy(update={"min_coverage": 0.0}),
        APPLE_POLICY.model_copy(update={"min_observed_count": 2}),  # any difference refused
    ]
    for policy in weaker:
        with pytest.raises(ValidationError, match="keeps the model's feature policy"):
            ServingSpec(
                format_version="hachi-serving-1",
                task="physiology_forecast",
                resolution="hour",
                entry_point="hachi.models.baselines.load_artifact",
                input="hourly_features",
                feature_policy=HR_POLICY,
                accepted_sources=[
                    SourceAdmission(
                        source="apple_health", feature_policy=policy, rationale=RATIONALE
                    )
                ],
            )
    assert admitting_serving().accepted_sources[0].feature_policy == APPLE_POLICY  # allowed
    steps = APPLE_POLICY.model_copy(update={"metric": "steps", "aggregation": "sum"})
    with pytest.raises(ValidationError, match="keeps the model's feature policy"):
        ServingSpec(
            format_version="hachi-serving-1",
            task="physiology_forecast",
            resolution="hour",
            entry_point="hachi.models.baselines.load_artifact",
            input="hourly_features",
            feature_policy=HR_POLICY,
            accepted_sources=[
                SourceAdmission(source="apple_health", feature_policy=steps, rationale=RATIONALE)
            ],
        )


def test_staging_records_an_explicit_apple_admission(tmp_path, data_root, snapshot_id):
    from hachi.api.__main__ import serving_from_protocol

    packet = make_packet(tmp_path / "p", data_root / "derived" / snapshot_id)
    protocol = tmp_path / "protocol.json"
    protocol.write_text(json.dumps({"feature_policy": HR_POLICY.model_dump()}))
    plain = serving_from_protocol(protocol, packet.model_dir)
    assert plain.accepted_sources == []
    admitted = serving_from_protocol(protocol, packet.model_dir, RATIONALE)
    (admission,) = admitted.accepted_sources
    assert admission.feature_policy == APPLE_POLICY and admission.rationale == RATIONALE


# A density-variant artifact (#102): history thinned to one sample per UTC 5-minute slot,
# coverage in sampled minutes / 60, gate >= 0.10 and >= 6. Every source is thinned the same way.
THIN = AppleMinuteThinning(
    slot_seconds=300,
    pipeline_suffix="thin300s-applemin",
    coverage="distinct_sampled_minutes_per_60",
)
THIN_POLICY = HR_POLICY.model_copy(update={"min_coverage": 0.1, "min_observed_count": 6})
THIN_RATIONALE = "Synthetic: validated for 5-minute cadence on PMData only; not on Apple devices."


def thinned_serving() -> ServingSpec:
    serving = admitting_serving(
        feature_policy=THIN_POLICY,
        history_thinning=THIN,
        accepted_sources=[
            SourceAdmission(
                source="apple_health",
                feature_policy=THIN_POLICY.model_copy(
                    update={"availability_rule": AVAILABILITY_RULE}
                ),
                rationale=THIN_RATIONALE,
            )
        ],
    )
    return ServingSpec.model_validate(serving.model_dump())  # re-validated as staged


def plain_serving(policy=THIN_POLICY) -> ServingSpec:
    return admitting_serving(feature_policy=policy, accepted_sources=[])


@pytest.fixture
def thinned_client(tmp_path, data_root, snapshot_id, open_client, make_settings):
    # A thinned packet: its protocol is the variant and its run_id carries the runner's label.
    packet = make_packet(
        tmp_path / "thin-packet",
        data_root / "derived" / snapshot_id,
        serving=thinned_serving(),
        artifact_id="synthetic-last-valid-hr-thin300s",
    )
    root = tmp_path / "thin-artifacts"
    root.mkdir()
    pin = stage_artifact(root, packet.model_dir, packet.packet_dir, packet.serving, packet.protocol)
    return open_client(make_settings(artifact_root=root, served_artifacts=(pin,))), pin


def test_five_minute_apple_history_is_forecast_by_a_density_validated_artifact(thinned_client):
    client, pin = thinned_client
    upload(client, apple_hr_export(72, every_minutes=5), subject="synthetic-apple-watch")
    wait(client)
    result = forecast(client, "synthetic-apple-watch").result.root
    assert result.status == "ok", result  # the same export abstains at native density gates
    assert result.provenance.artifact == pin
    shift = next(w for w in result.warnings if w.code == "DEVICE_SHIFT")
    assert THIN_RATIONALE in shift.message

    # Direct predict on #78's sealed bins, thinned by the artifact's rule, gives the same output.
    service = client.app.state.service
    served = service.catalog.artifacts[0]
    subject = service.catalog.subject("synthetic-apple-watch", service.metadata, service.workspace)
    cutoff = result.as_of
    view = apple_hourly_features(
        subject.path,
        THIN_POLICY.model_copy(update={"availability_rule": AVAILABILITY_RULE}),
        cutoff,
        cutoff - timedelta(hours=48),
        thin_slot_seconds=300,
    )
    assert {f.aggregate.observed_count for f in view.features} == {12}
    targets = tuple(
        TimeWindow(start_utc=cutoff + timedelta(hours=i), end_utc=cutoff + timedelta(hours=i + 1))
        for i in range(24)
    )
    direct = served.model.predict(
        ForecastInput("synthetic-apple-watch", cutoff, targets, view.features)
    )
    assert [p.median for p in result.forecast.series[0].points] == [e.median for e in direct]


def test_snapshot_history_is_thinned_per_subject_exactly_as_in_evaluation(data_root, snapshot_id):
    pytest.importorskip("numpy", reason="thinning snapshot history needs the baselines extra")
    from hachi.api.sources import open_dataset_snapshot
    from hachi.data.pmdata import iter_aggregates
    from hachi.models.density.thinning import thinned_bins

    snapshot = open_dataset_snapshot(data_root, snapshot_id, allow_unadmitted=True)
    every, _ = thinned_bins(snapshot.path, THIN)
    subject = sorted(snapshot.subjects)[0]
    data = SubjectData(
        subject_id=subject,
        kind="dataset_snapshot",
        data_mode=snapshot.data_mode,
        snapshot=snapshot.ref,
        tz_name=snapshot.tz_name,
        path=snapshot.path,
        dataset_source_kind=snapshot.source_kind,
    )
    last = max(b.aggregate.interval_end_utc for b in iter_aggregates(snapshot.path, "hour"))
    for as_of in (last - timedelta(days=1), last):
        served = data.hourly_features(THIN_POLICY, as_of, thinning=THIN)
        expected = hourly_features(
            [
                b
                for b in every
                if b.aggregate.subject_id == subject
                and b.aggregate.interval_end_utc <= as_of
                and b.available_at_utc <= as_of
            ],
            THIN_POLICY,
        ).features
        assert served == list(expected)
        assert all(f.aggregate.pipeline_version.endswith("+thin300s-applemin") for f in served)


def test_thinning_is_declared_with_a_gate_thinned_hours_can_meet():
    too_strict = HR_POLICY.model_copy(update={"min_observed_count": 13}).model_dump()
    with pytest.raises(ValidationError, match="fits the hour's slots"):
        ServingSpec.model_validate(
            admitting_serving().model_dump()
            | {"feature_policy": too_strict, "accepted_sources": [], "history_thinning": THIN}
        )
    slot_coverage = ThinningRule(slot_seconds=300, pipeline_suffix="thin300s").model_dump()
    with pytest.raises(ValidationError):  # #97's slot-coverage rule: not a served construction
        ServingSpec.model_validate(
            admitting_serving().model_dump()
            | {"feature_policy": THIN_POLICY.model_dump(), "accepted_sources": [],
               "history_thinning": slot_coverage}
        )  # fmt: skip
    with pytest.raises(ValidationError, match="thinned metric"):
        ServingSpec(
            format_version="hachi-serving-1",
            task="physiology_forecast",
            resolution="hour",
            entry_point="hachi.models.baselines.load_artifact",
            input="observations",
            feature_policy=None,
            history_thinning=THIN,
        )


def test_staging_a_density_variant_records_its_thinning_and_exact_gate(
    tmp_path, data_root, snapshot_id
):
    from hachi.api.__main__ import serving_from_protocol
    from hachi.models.density.config import REPO

    variant = REPO / "configs/evaluation/pmdata-hourly-validation-apple-minute-density.json"
    packet = make_packet(tmp_path / "p", data_root / "derived" / snapshot_id)
    serving = serving_from_protocol(variant, packet.model_dir, THIN_RATIONALE)
    assert serving.history_thinning == THIN
    assert serving.feature_policy.min_observed_count == 6
    assert serving.feature_policy.min_coverage == 0.1
    # #97's slot-coverage variant is not served: the Apple helper keeps minute coverage.
    original = REPO / "configs/evaluation/pmdata-hourly-validation-apple-density.json"
    with pytest.raises(ValueError, match="sampled-minute thinning"):
        serving_from_protocol(original, packet.model_dir, THIN_RATIONALE)
    (admission,) = serving.accepted_sources
    assert admission.feature_policy == serving.feature_policy.model_copy(
        update={"availability_rule": AVAILABILITY_RULE}
    )
    assert serving.protocol_sha256 == hashlib.sha256(variant.read_bytes()).hexdigest()


SUFFIX = THIN.pipeline_suffix


@pytest.mark.parametrize(
    ("serving", "options", "refusal"),
    [
        # A full-density packet (no run_id label) is never served thinned at the looser gate,
        pytest.param(thinned_serving, {"evaluated_thinning": THIN, "run_label": None},
                     "history label", id="full-packet-variant-protocol-served-thinned"),
        pytest.param(thinned_serving, {"evaluated_thinning": None, "run_label": None},
                     "history thinning", id="full-packet-served-thinned"),
        # and a thinned packet is never served unthinned.
        pytest.param(plain_serving, {"evaluated_thinning": None, "run_label": SUFFIX},
                     "history label", id="thinned-packet-base-protocol-served-unthinned"),
        pytest.param(plain_serving, {"evaluated_thinning": THIN, "run_label": SUFFIX},
                     "history thinning", id="thinned-packet-served-unthinned"),
        # The served gate is the evaluated one, never one written into serving.json.
        pytest.param(lambda: plain_serving(HR_POLICY), {"evaluated_policy": THIN_POLICY},
                     "feature gate", id="gate-not-evaluated"),
        # A hand-written protocol is not evidence, whatever gate it names,
        pytest.param(thinned_serving, {"predeclared": False}, "committed, predeclared",
                     id="protocol-not-predeclared"),
        # and the protocol must have evaluated this very model, at the model's own count gate.
        pytest.param(thinned_serving, {"comparators": [BaselineConfig(
                         method="seasonal_naive", metric="heart_rate", aggregation="mean",
                         min_samples_per_hour=6)]},
                     "not one of the protocol's comparators", id="model-not-evaluated"),
        pytest.param(thinned_serving, {"config": BaselineConfig(
                         method="last_valid", metric="heart_rate", aggregation="mean",
                         min_samples_per_hour=1)},
                     "count gate", id="count-gate-not-the-models"),
    ],
)  # fmt: skip
def test_served_thinning_and_gate_are_bound_to_the_evaluated_protocol(
    tmp_path, data_root, snapshot_id, serving, options, refusal
):
    packet = make_packet(
        tmp_path / "packet", data_root / "derived" / snapshot_id, serving=serving(), **options
    )
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ArtifactRefused, match=refusal) as refused:
        stage_artifact(root, packet.model_dir, packet.packet_dir, packet.serving, packet.protocol)
    assert refused.value.code == "ARTIFACT_INCOMPATIBLE"
    assert list(root.iterdir()) == []  # nothing staged


def test_a_staged_artifact_is_checked_again_at_load(tmp_path, data_root, snapshot_id):
    import shutil

    from hachi.evaluation.serialization import document_bytes

    packet = make_packet(
        tmp_path / "p", data_root / "derived" / snapshot_id, serving=thinned_serving()
    )
    root = tmp_path / "root"
    root.mkdir()
    pin = stage_artifact(root, packet.model_dir, packet.packet_dir, packet.serving, packet.protocol)
    assert load_served_artifact(root, pin).serving.history_thinning == THIN

    def edited(name, edit):
        copy = tmp_path / name
        shutil.copytree(root, copy)
        for path in [copy, *copy.rglob("*")]:
            path.chmod(0o700)
        edit(copy / pin.artifact_id)
        return copy

    unthinned = thinned_serving().model_copy(
        update={"history_thinning": None, "protocol_sha256": packet.serving.protocol_sha256}
    )
    cases = {
        "history thinning": lambda d: (d / "serving.json").write_bytes(document_bytes(unthinned)),
        "carries the protocol": lambda d: (d / "protocol.json").unlink(),
        "another protocol": lambda d: (d / "protocol.json").write_bytes(b'{"swapped": true}'),
    }
    for refusal, edit in cases.items():
        with pytest.raises(ArtifactRefused, match=refusal):
            load_served_artifact(edited(refusal.replace(" ", "-"), edit), pin)


def test_dataset_subjects_without_numpy_get_a_clear_unavailable(thinned_client, monkeypatch):
    import importlib.util

    client, _ = thinned_client
    upload(client, apple_hr_export(72, every_minutes=5), subject="synthetic-apple-watch")
    wait(client)
    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name, *a: None if name == "numpy" else real(name, *a)
    )
    snapshot = forecast(client, "p01").result.root
    assert (snapshot.status, snapshot.reason_code) == ("unavailable", "NO_ARTIFACT_FOR_TASK")
    assert "baselines extra" in snapshot.requirements[0]
    assert forecast(client, "synthetic-apple-watch").result.root.status == "ok"  # pure Python


def test_a_variant_is_bound_whole_so_its_recipe_cannot_change_under_its_label(
    tmp_path, data_root, snapshot_id
):
    # SnowyFortress's counterexample: from a matched thinned control, change only the slot
    # (300 s -> 60 s) in the staged variant and in serving.json, rehash, keep the label.
    import hashlib

    packet = make_packet(
        tmp_path / "p", data_root / "derived" / snapshot_id, serving=thinned_serving()
    )
    document = json.loads(packet.protocol.read_bytes())
    document["thinning"]["slot_seconds"] = 60
    changed = tmp_path / "changed-protocol.json"
    changed.write_bytes(json.dumps(document, sort_keys=True).encode())
    serving = packet.serving.model_copy(
        update={
            "history_thinning": THIN.model_copy(update={"slot_seconds": 60}),
            "protocol_sha256": hashlib.sha256(changed.read_bytes()).hexdigest(),
        }
    )
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ArtifactRefused, match="committed, predeclared"):
        stage_artifact(root, packet.model_dir, packet.packet_dir, serving, changed)
    assert stage_artifact(
        root, packet.model_dir, packet.packet_dir, packet.serving, packet.protocol
    )


def test_committed_density_variants_are_registered_whole():
    from hachi.api.artifacts import FROZEN_PROTOCOL_DIR, frozen_protocols, protocol_key

    committed = json.loads(
        (FROZEN_PROTOCOL_DIR / "pmdata-hourly-validation-apple-minute-density.json").read_bytes()
    )
    assert protocol_key(committed) in frozen_protocols()
    assert protocol_key(committed["protocol"]) not in frozen_protocols()  # never unwrapped
    committed["thinning"]["slot_seconds"] = 60
    assert protocol_key(committed) not in frozen_protocols()


def test_two_committed_variants_may_not_share_a_label(tmp_path):
    from hachi.api.artifacts import FROZEN_PROTOCOL_DIR, committed_protocols

    for name in (
        "pmdata-hourly-validation.json",
        "pmdata-hourly-validation-apple-minute-density.json",
    ):
        (tmp_path / name).write_bytes((FROZEN_PROTOCOL_DIR / name).read_bytes())
    assert committed_protocols(tmp_path)  # one variant per label is fine
    twin = json.loads((tmp_path / "pmdata-hourly-validation-apple-minute-density.json").read_text())
    twin["thinning"]["slot_seconds"] = 60  # another recipe under the same label
    (tmp_path / "twin.json").write_text(json.dumps(twin))
    with pytest.raises(ValueError, match="share the label"):
        committed_protocols(tmp_path)
