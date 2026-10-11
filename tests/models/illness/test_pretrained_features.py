"""Exercise real Chronos receipt transport and private repeated-role joins with synthetic data."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from hachi.evaluation.serialization import document_bytes, document_sha256
from hachi.models.chronos.inference import check_request, request_id, write_run
from hachi.models.illness.data import external_at
from hachi.models.illness.pretrained_features import load_chronos_features, sha
from hachi.models.illness.pretrained_protocol import load_pretrained_protocol

COMPARISON = load_pretrained_protocol(Path("configs/experiments/illness/pretrained.json"))


@pytest.fixture
def feature_packet(tmp_path, monkeypatch):
    packet, inference = tmp_path / "contexts", tmp_path / "inference"
    packet.mkdir()
    inference.mkdir()
    row = {
        "request_id": request_id([60.0] * 168, 24),
        "context": [60.0] * 168,
        "prediction_length": 24,
    }
    (packet / "requests.jsonl").write_bytes(document_bytes(row))
    cutoff = datetime(2020, 1, 10, tzinfo=UTC)
    joins = []
    for inner in range(3):
        for offset, rid in ((0, row["request_id"]), (1, None)):
            instant = cutoff + timedelta(days=offset)
            joins.append(
                dict(
                    outer_fold=0,
                    inner_fold=inner,
                    subject_id="synthetic-person",
                    cutoff_floating=instant,
                    as_of_floating=instant,
                    role="validation" if inner == 0 else "train",
                    request_id=rid,
                    encoder_request_sha256="e" * 64 if rid else None,
                    observed_hr_hours=168 if rid else 0,
                    clock="floating_local_shifted",
                )
            )
    (packet / "joins.json").write_bytes(document_bytes(joins))
    spec = json.loads(Path("infra/gx10/model.json").read_bytes())
    write_run(
        inference,
        packet / "requests.jsonl",
        [check_request(row)],
        [{"request_id": row["request_id"], "embedding": [0.25] * 768, "loc": 60.0, "scale": 2.0}],
        [],
        0,
        {
            "model": spec,
            "weights_sha256": spec["weights_sha256"],
            "checkpoint": None,
            "embedding": "mean over all encoder tokens of the first variate",
            "environment": {"script_sha256": sha(Path("src/hachi/models/chronos/inference.py"))},
        },
        kind="embed",
    )
    monkeypatch.setattr(
        "hachi.models.illness.pretrained_features.verify_packet",
        lambda *args: {
            "protocol_sha256": COMPARISON.context_protocol.sha256,
            "shared_protocol_sha256": COMPARISON.clinical_protocol.sha256,
        },
    )
    return packet, inference, cutoff


def test_actual_chronos_receipt_width_auxiliary_and_null_prevent_stale_vector(feature_packet):
    packet, inference, cutoff = feature_packet
    features = load_chronos_features(packet, packet, inference, COMPARISON)
    assert set(features.by_inner) == {0, 1, 2}
    assert features.by_inner[0].feature_names[-2:] == ("loc_bpm", "scale_bpm")
    for inner in range(3):
        assert features.supported_by_inner[inner] == {("synthetic-person", cutoff)}
        points = features.by_inner[inner].points
        assert external_at(points, cutoff, 24)[-2:] == (60.0, 2.0)
        assert external_at(points, cutoff + timedelta(days=1), 24) == (None,) * 770
        assert features.by_inner[inner].fit_subjects == ()
    assert features.by_inner[0].provenance_sha256 == document_sha256(features.provenance)


@pytest.mark.parametrize("mutation", ["requests", "weights", "checkpoint", "script", "model"])
def test_receipt_rejects_changed_inputs_and_checkpoint(feature_packet, mutation):
    packet, inference, _ = feature_packet
    receipt = json.loads((inference / "inference.json").read_bytes())
    if mutation == "requests":
        receipt["requests_sha256"] = "b" * 64
    elif mutation == "weights":
        receipt["weights_sha256"] = "b" * 64
    elif mutation == "checkpoint":
        receipt["checkpoint"] = "fine-tuned"
    elif mutation == "script":
        receipt["environment"]["script_sha256"] = "b" * 64
    else:
        receipt["model"]["revision"] = "b" * 40
    (inference / "inference.json").write_bytes(document_bytes(receipt))
    with pytest.raises(ValueError, match="receipt differs"):
        load_chronos_features(packet, packet, inference, COMPARISON)


@pytest.mark.parametrize(
    "mutation", ["width", "nonfinite", "scale", "extra-id", "duplicate", "bytes"]
)
def test_output_boundary_rejects_bad_vectors_even_with_updated_checksum(feature_packet, mutation):
    packet, inference, _ = feature_packet
    output = inference / "embeddings.jsonl"
    row = json.loads(output.read_bytes())
    if mutation == "width":
        row["embedding"].pop()
    elif mutation == "nonfinite":
        row["embedding"][0] = None
    elif mutation == "scale":
        row["scale"] = 0.0
    elif mutation == "extra-id":
        row["request_id"] = "c" * 64
    output.write_bytes(document_bytes(row) * (2 if mutation == "duplicate" else 1))
    receipt = json.loads((inference / "inference.json").read_bytes())
    if mutation != "bytes":
        receipt["embeddings_sha256"] = sha(output)
    else:
        output.write_bytes(output.read_bytes() + b"\n")
    (inference / "inference.json").write_bytes(document_bytes(receipt))
    with pytest.raises((ValueError, ValidationError)):
        load_chronos_features(packet, packet, inference, COMPARISON)


def test_direct_loader_cannot_substitute_changed_spec_even_with_matching_receipt(
    feature_packet, tmp_path, monkeypatch
):
    packet, inference, _ = feature_packet
    spec_path = tmp_path / "infra/gx10/model.json"
    spec_path.parent.mkdir(parents=True)
    spec = json.loads(Path("infra/gx10/model.json").read_bytes())
    spec["revision"] = "b" * 40
    spec_path.write_bytes(document_bytes(spec))
    monkeypatch.setattr("hachi.models.illness.pretrained_features.REPO", tmp_path)
    with pytest.raises(ValueError, match="frozen file pin"):
        load_chronos_features(packet, packet, inference, COMPARISON)


def test_actual_meanpool_consumer_binds_summary_width_and_private_encoder_joins(feature_packet):
    pytest.importorskip("numpy", reason="MeanPool requires the optional baselines extra")
    from hachi.models.illness.pretrained_features import build_meanpool_features

    packet, _, cutoff = feature_packet
    request = dict(
        context_policy_sha256=COMPARISON.context_protocol.sha256,
        hours=168,
        first_hour_local=0,
        channels={"heart_rate": [60.0] * 168},
        units={"heart_rate": "bpm"},
    )
    request["request_sha256"] = document_sha256(request)
    (packet / "encoder-requests.jsonl").write_bytes(document_bytes(request))
    joins = json.loads((packet / "joins.json").read_bytes())
    for row in joins:
        if row["request_id"]:
            row["encoder_request_sha256"] = request["request_sha256"]
    (packet / "joins.json").write_bytes(document_bytes(joins))
    features = build_meanpool_features(packet, packet, COMPARISON)
    for inner in range(3):
        points = features.by_inner[inner].points
        assert len(features.by_inner[inner].feature_names) == 76
        assert points[0].values[5] == 1.0  # HR60bpm -> one count/s before summary.
        assert points[0].values[19 + 5] == 0.0  # HR observed mask.
        assert points[1].values == (None,) * 76
        assert features.supported_by_inner[inner] == {("synthetic-person", cutoff)}
    assert features.name == "meanpool_hr" and "weights_sha256" not in features.provenance
