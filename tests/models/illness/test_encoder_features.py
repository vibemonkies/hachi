"""Original encoder transport, runtime patch masks and null-vector joins remain bound."""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from hachi.evaluation.serialization import document_bytes, document_sha256
from hachi.models.encoders.requests import main as encoder_main
from hachi.models.encoders.requests import model_inputs, moment_patch_support, read_requests
from hachi.models.illness.encoder_features import EncoderReturnPins, load_encoder_features
from hachi.models.illness.pretrained_features import sha
from hachi.models.illness.pretrained_protocol import load_pretrained_protocol

COMPARISON = load_pretrained_protocol(Path("configs/experiments/illness/pretrained.json"))


@pytest.fixture
def returned(tmp_path, monkeypatch, capsys):
    packet, output = tmp_path / "contexts", tmp_path / "return"
    packet.mkdir()
    output.mkdir()
    gap = [60.0] * 168
    for h in range(7, 168, 8):
        gap[h] = None
    requests = []
    for values in (gap, [60.0] * 168):
        row = dict(
            context_policy_sha256=COMPARISON.context_protocol.sha256,
            hours=168,
            first_hour_local=0,
            channels={"heart_rate": values},
            units={"heart_rate": "bpm"},
        )
        row["request_sha256"] = document_sha256(row)
        requests.append(row)
    payload = b"".join(document_bytes(r) for r in requests)
    for directory in (packet, output):
        (directory / "encoder-requests.jsonl").write_bytes(payload)
    hashes, values, _ = read_requests(output / "encoder-requests.jsonl")
    norm = json.loads(Path("configs/models/encoders/wbm.json").read_bytes())["input"][
        "normalization"
    ]
    arrays = model_inputs(values, np.asarray(norm["means"]), np.asarray(norm["stds"]))
    np.savez(output / "inputs.npz", request_sha256=np.asarray(hashes), **arrays)
    np.savez(
        output / "wbm.npz", request_sha256=np.asarray(hashes), wbm_hr=np.ones((2, 256), np.float32)
    )
    np.savez(
        output / "moment.npz",
        request_sha256=np.asarray(hashes),
        moment=np.vstack([np.zeros(1024), np.ones(1024)]).astype(np.float32),
        moment_ok=moment_patch_support(arrays["moment_mask"]),
    )
    for short in ("wbm", "moment"):
        spec_path = Path(f"configs/models/encoders/{short}.json")
        spec = json.loads(spec_path.read_bytes())
        (output / f"{short}.receipt.json").write_bytes(
            document_bytes(
                {
                    "model": spec["model_id"],
                    "checkpoint": spec["checkpoint"],
                    "config_sha256": sha(spec_path),
                    "inputs_sha256": sha(output / "inputs.npz"),
                    "outputs_sha256": sha(output / f"{short}.npz"),
                }
            )
        )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "encoder",
            "features",
            "--inputs",
            str(output / "inputs.npz"),
            "--wbm",
            str(output / "wbm.npz"),
            "--moment",
            str(output / "moment.npz"),
            "--output",
            str(output / "frozen-features.parquet"),
        ],
    )
    assert encoder_main() == 0
    capsys.readouterr()
    cutoff = datetime(2020, 1, 1, tzinfo=UTC)
    joins = [
        dict(
            outer_fold=0,
            inner_fold=inner,
            subject_id="synthetic-person",
            cutoff_floating=cutoff + timedelta(days=i),
            as_of_floating=cutoff + timedelta(days=i),
            request_id="a" * 64,
            encoder_request_sha256=hashes[i],
            observed_hr_hours=147 if i == 0 else 168,
            role="validation" if inner == 0 else "train",
            clock="floating_local_shifted",
        )
        for inner in range(3)
        for i in range(2)
    ]
    (packet / "joins.json").write_bytes(document_bytes(joins))
    monkeypatch.setattr(
        "hachi.models.illness.encoder_features.verify_packet",
        lambda *args: {
            "protocol_sha256": COMPARISON.context_protocol.sha256,
            "shared_protocol_sha256": COMPARISON.clinical_protocol.sha256,
        },
    )
    pins = EncoderReturnPins(
        producer_commit="a" * 40, files={p.name: sha(p) for p in output.iterdir()}
    )
    return packet, output, pins, cutoff


def test_actual_encoder_transport_keeps_finite_zero_sentinel_unsupported(returned):
    packet, output, pins, cutoff = returned
    families = load_encoder_features(packet, packet, output, COMPARISON, pins)
    assert set(families) == {"meanpool_hr", "wbm_hr", "moment_hr"}
    moment = families["moment_hr"]
    assert moment.by_inner[0].points[0].values == (None,) * 1024
    assert moment.supported_by_inner[0] == {("synthetic-person", cutoff + timedelta(days=1))}
    assert len(families["wbm_hr"].supported_by_inner[0]) == 2
    assert len(families["meanpool_hr"].by_inner[0].feature_names) == 76


def test_runtime_flag_tamper_is_rejected_even_after_repinning_files(returned):
    packet, output, pins, _ = returned
    with np.load(output / "moment.npz", allow_pickle=False) as data:
        arrays = {k: data[k] for k in data.files}
    arrays["moment_ok"][0, 0] = True
    np.savez(output / "moment.npz", **arrays)
    receipt_path = output / "moment.receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["outputs_sha256"] = sha(output / "moment.npz")
    receipt_path.write_bytes(document_bytes(receipt))
    altered = pins.model_copy(update={"files": {p.name: sha(p) for p in output.iterdir()}})
    with pytest.raises(ValueError, match="runtime MOMENT support"):
        load_encoder_features(packet, packet, output, COMPARISON, altered)


def test_pinned_return_bytes_cannot_be_substituted(returned):
    packet, output, pins, _ = returned
    with (output / "wbm.receipt.json").open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(ValueError, match="original handed-off file pins"):
        load_encoder_features(packet, packet, output, COMPARISON, pins)
