"""Verify original #11 feature files and actual runtime support before local fold joins."""

import json
from pathlib import Path
from typing import Literal

from pydantic import model_validator

from hachi.contracts.base import Contract, GitSha, Sha256
from hachi.evaluation.serialization import document_sha256

from .context_export import verify_packet
from .pretrained_features import FrozenFeatures, context_joins, join_vectors, sha
from .pretrained_protocol import REPO, PretrainedProtocol, representation_feature_names

FILES = {
    "encoder-requests.jsonl",
    "inputs.npz",
    "wbm.npz",
    "moment.npz",
    "wbm.receipt.json",
    "moment.receipt.json",
    "frozen-features.parquet",
}


class EncoderReturnPins(Contract):
    producer_commit: GitSha
    files: dict[str, Sha256]

    @model_validator(mode="after")
    def complete(self):
        if set(self.files) != FILES:
            raise ValueError("encoder handoff requires the complete original seven-file inventory")
        return self


def load_encoder_features(
    snapshot: Path,
    packet: Path,
    returned: Path,
    comparison: PretrainedProtocol,
    pins: EncoderReturnPins,
) -> dict[Literal["meanpool_hr", "wbm_hr", "moment_hr"], FrozenFeatures]:
    import numpy as np
    import pyarrow.parquet as pq

    from hachi.models.encoders.requests import (
        feature_table,
        model_inputs,
        moment_patch_support,
        read_requests,
    )

    verified = verify_packet(snapshot, packet)
    if (
        verified["protocol_sha256"] != comparison.context_protocol.sha256
        or verified["shared_protocol_sha256"] != comparison.clinical_protocol.sha256
    ):
        raise ValueError("encoder packet differs from frozen context/participant policy")
    if any(sha(returned / name) != digest for name, digest in pins.files.items()):
        raise ValueError("encoder return differs from original handed-off file pins")
    if (returned / "encoder-requests.jsonl").read_bytes() != (
        packet / "encoder-requests.jsonl"
    ).read_bytes():
        raise ValueError("encoder return uses a different request file")
    specs = {}
    for name in ("wbm_hr", "moment_hr"):
        representation = next(r for r in comparison.representations if r.name == name)
        path = REPO / representation.model_spec.path
        if sha(path) != representation.model_spec.sha256:
            raise ValueError("encoder specification differs from frozen file pin")
        specs[name] = json.loads(path.read_bytes())
    hashes, values, policy = read_requests(returned / "encoder-requests.jsonl")
    if policy != comparison.context_protocol.sha256:
        raise ValueError("encoder requests differ from frozen primary policy")
    norm = specs["wbm_hr"]["input"]["normalization"]
    expected_inputs = model_inputs(values, np.asarray(norm["means"]), np.asarray(norm["stds"]))
    with np.load(returned / "inputs.npz", allow_pickle=False) as inputs:
        if set(inputs.files) != {"request_sha256", *expected_inputs} or not np.array_equal(
            inputs["request_sha256"], np.asarray(hashes)
        ):
            raise ValueError(
                "encoder input inventory/row order differs from native request consumer"
            )
        for key, expected in expected_inputs.items():
            numeric = np.issubdtype(expected.dtype, np.number)
            if not np.array_equal(inputs[key], expected, equal_nan=numeric):
                raise ValueError("encoder inputs differ from causal native request transformation")
    arrays = {"meanpool_hr": expected_inputs["meanpool_hr"]}
    support = {}
    for short, name, width in (("wbm", "wbm_hr", 256), ("moment", "moment_hr", 1024)):
        spec = specs[name]
        receipt = json.loads((returned / f"{short}.receipt.json").read_bytes())
        if (
            receipt["model"] != spec["model_id"]
            or receipt["checkpoint"]["repository"] != spec["checkpoint"]["repository"]
            or receipt["checkpoint"]["revision"] != spec["checkpoint"]["revision"]
            or receipt["checkpoint"]["files"] != spec["checkpoint"]["files"]
            or receipt["config_sha256"]
            != next(r.model_spec.sha256 for r in comparison.representations if r.name == name)
            or receipt["inputs_sha256"] != pins.files["inputs.npz"]
            or receipt["outputs_sha256"] != pins.files[f"{short}.npz"]
        ):
            raise ValueError(
                "encoder runtime receipt differs from frozen checkpoint/input/output pins"
            )
        with np.load(returned / f"{short}.npz", allow_pickle=False) as output:
            if set(output.files) != (
                {"request_sha256", "wbm_hr"}
                if short == "wbm"
                else {"request_sha256", "moment", "moment_ok"}
            ) or not np.array_equal(output["request_sha256"], np.asarray(hashes)):
                raise ValueError("encoder output inventory/row order differs")
            matrix = output["wbm_hr" if short == "wbm" else "moment"]
            if matrix.shape != (len(hashes), width):
                raise ValueError("encoder vector width differs from frozen representation")
            arrays[name] = matrix
            if short == "moment":
                expected = moment_patch_support(expected_inputs["moment_mask"])
                if output["moment_ok"].dtype != np.bool_ or not np.array_equal(
                    output["moment_ok"], expected
                ):
                    raise ValueError("runtime MOMENT support differs from actual input patches")
                support[name] = output["moment_ok"][:, 0]
    metadata = {
        "inputs_sha256": pins.files["inputs.npz"],
        "wbm_sha256": pins.files["wbm.npz"],
        "moment_sha256": pins.files["moment.npz"],
        "wbm_checkpoint": "@".join(
            specs["wbm_hr"]["checkpoint"][k] for k in ("repository", "revision")
        ),
        "moment_checkpoint": "@".join(
            specs["moment_hr"]["checkpoint"][k] for k in ("repository", "revision")
        ),
        "encoders": "frozen; never fitted on the requesting cohort",
        "support_rule": (
            "supported = finite output and, for MOMENT, a fully observed 8-hour patch "
            "(runtime moment_ok, checked against the inputs' mask); "
            "unsupported vectors are null"
        ),
    }
    expected_table = feature_table(np.asarray(hashes), arrays, metadata, support)
    actual_table = pq.read_table(returned / "frozen-features.parquet")
    # Parquet renames the list child from "item" to "element" on round-trip.
    # Validate numerical/schema equality and the exact receipt metadata separately.
    if (
        not actual_table.equals(expected_table, check_metadata=False)
        or actual_table.schema.metadata != expected_table.schema.metadata
    ):
        raise ValueError(
            "encoder parquet differs from original outputs, transformation or support flags"
        )
    features = {}
    joins = context_joins(packet)
    for name in ("meanpool_hr", "wbm_hr", "moment_hr"):
        representation = next(r for r in comparison.representations if r.name == name)
        vectors = {
            r["request_sha256"]: tuple(r["vector"]) if r["supported"] else None
            for r in expected_table.to_pylist()
            if r["model"] == name
        }
        provenance = {
            "comparison_sha256": document_sha256(comparison),
            "producer_commit": pins.producer_commit,
            "pins_sha256": document_sha256(pins),
            "parquet_sha256": pins.files["frozen-features.parquet"],
            "join_file_sha256": sha(packet / "joins.json"),
        }
        features[name] = join_vectors(
            name,
            representation_feature_names(representation),
            vectors,
            joins,
            provenance,
            encoder=True,
        )
    return features
