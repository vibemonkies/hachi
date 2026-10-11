"""Admit frozen feature bytes locally; identity/cutoff joins never leave this lane."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, TypeAdapter

from hachi.contracts.base import Contract, Sha256, UtcDatetime
from hachi.evaluation.serialization import document_sha256
from hachi.models.chronos.inference import EMBEDDING_FORMAT, REQUEST_FORMAT, read_requests

from .context_export import verify_packet
from .data import FeaturePoint, FeatureSet
from .pretrained_protocol import (
    REPO,
    FrozenRepresentation,
    PretrainedProtocol,
    representation_feature_names,
)
from .support import CutoffKey


class ContextJoin(Contract):
    outer_fold: Literal[0]
    inner_fold: Annotated[int, Field(ge=0, le=2)]
    subject_id: str
    cutoff_floating: UtcDatetime
    role: Literal["train", "validation"]
    request_id: Sha256 | None
    encoder_request_sha256: Sha256 | None
    observed_hr_hours: Annotated[int, Field(ge=0, le=168)]
    as_of_floating: UtcDatetime
    clock: Literal["floating_local_shifted"]


class ChronosFeature(Contract):
    request_id: Sha256
    embedding: Annotated[tuple[FiniteFloat, ...], Field(min_length=768, max_length=768)]
    loc: FiniteFloat
    scale: Annotated[FiniteFloat, Field(gt=0)]


@dataclass(frozen=True)
class FrozenFeatures:
    name: str
    by_inner: dict[int, FeatureSet]
    supported_by_inner: dict[int, frozenset[CutoffKey]]
    provenance: dict[str, str]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def context_joins(packet: Path) -> list[ContextJoin]:
    """Caller first verifies packet eligibility against its snapshot with verify_packet."""
    joins = TypeAdapter(list[ContextJoin]).validate_json((packet / "joins.json").read_bytes())
    if any(j.as_of_floating != j.cutoff_floating for j in joins):
        raise ValueError("feature join must be available at its exact cutoff")
    if len({(j.inner_fold, j.subject_id, j.cutoff_floating) for j in joins}) != len(joins):
        raise ValueError("duplicate private feature joins")
    return joins


def join_vectors(
    name: str,
    names: tuple[str, ...],
    vectors: dict[str, tuple[float, ...] | None],
    joins: list[ContextJoin],
    provenance: dict[str, str],
    *,
    encoder: bool = False,
) -> FrozenFeatures:
    """An explicit null point at every unsupported cutoff prevents carrying older vectors."""
    requested = {j.encoder_request_sha256 if encoder else j.request_id for j in joins} - {None}
    if requested != set(vectors):
        raise ValueError("returned features differ from complete private context joins")
    if any(v is not None and len(v) != len(names) for v in vectors.values()):
        raise ValueError("returned vector width differs from frozen feature order")
    by_inner, supported = {}, {}
    for inner in sorted({j.inner_fold for j in joins}):
        points = []
        keys = set()
        for join in joins:
            if join.inner_fold != inner:
                continue
            rid = join.encoder_request_sha256 if encoder else join.request_id
            values = vectors.get(rid) if rid is not None else None
            if values is not None:
                keys.add((join.subject_id, join.cutoff_floating))
            points.append(
                FeaturePoint(
                    subject_id=join.subject_id,
                    at=join.cutoff_floating,
                    available_at=join.as_of_floating,
                    values=values if values is not None else (None,) * len(names),
                )
            )
        by_inner[inner] = FeatureSet(
            feature_names=names,
            provenance_sha256=document_sha256(provenance),
            fit_subjects=(),  # Frozen public encoders have no clinical head fitting here.
            clock="floating_local_shifted",
            points=tuple(points),
        )
        supported[inner] = frozenset(keys)
    return FrozenFeatures(name, by_inner, supported, provenance)


def load_chronos_features(
    snapshot: Path, packet: Path, inference: Path, comparison: PretrainedProtocol
) -> FrozenFeatures:
    """Verify the actual #12 embed receipt, pinned checkpoint and every 768+2 output."""
    verified = verify_packet(snapshot, packet)
    if (
        verified["protocol_sha256"] != comparison.context_protocol.sha256
        or verified["shared_protocol_sha256"] != comparison.clinical_protocol.sha256
    ):
        raise ValueError("feature packet differs from frozen context/participant policy")
    representation = next(r for r in comparison.representations if r.name == "chronos_hr")
    assert isinstance(representation, FrozenRepresentation)
    spec = json.loads((REPO / representation.model_spec.path).read_bytes())
    receipt_path = inference / "inference.json"
    output = inference / "embeddings.jsonl"
    receipt = json.loads(receipt_path.read_bytes())
    requests = read_requests(packet / "requests.jsonl")
    if (
        receipt["format"] != EMBEDDING_FORMAT
        or receipt["request_format"] != REQUEST_FORMAT
        or receipt["requests_sha256"] != sha(packet / "requests.jsonl")
        or receipt["embeddings_sha256"] != sha(output)
        or type(receipt["requests"]) is not int
        or receipt["requests"] != len(requests)
        or receipt["context_lengths"] != [168]
        or receipt["prediction_lengths"] != [24]
        or receipt["past_covariates"] != []
        or receipt["model"] != spec
        or receipt["weights_sha256"] != spec["weights_sha256"]
        or receipt["checkpoint"] is not None
        or receipt["embedding"] != "mean over all encoder tokens of the first variate"
        or receipt["environment"]["script_sha256"]
        != sha(REPO / "src/hachi/models/chronos/inference.py")
    ):
        raise ValueError("Chronos feature receipt differs from frozen inputs/model/extraction")
    rows = [ChronosFeature.model_validate_json(line) for line in output.read_text().splitlines()]
    vectors = {r.request_id: (*r.embedding, r.loc, r.scale) for r in rows}
    if len(vectors) != len(rows) or set(vectors) != {r.request_id for r in requests}:
        raise ValueError("Chronos outputs repeat, omit or add request ids")
    provenance = {
        "comparison_sha256": document_sha256(comparison),
        "requests_sha256": receipt["requests_sha256"],
        "features_sha256": receipt["embeddings_sha256"],
        "receipt_sha256": sha(receipt_path),
        "model_spec_sha256": representation.model_spec.sha256,
        "weights_sha256": receipt["weights_sha256"],
        "join_file_sha256": sha(packet / "joins.json"),
    }
    names = representation_feature_names(representation)
    return join_vectors("chronos_hr", names, vectors, context_joins(packet), provenance)
