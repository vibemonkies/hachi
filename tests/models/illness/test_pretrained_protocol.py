"""A comparison cannot silently change supported encoder schemas or score-time choices."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from hachi.models.illness.pretrained_protocol import PretrainedProtocol, load_pretrained_protocol

PATH = Path("configs/experiments/illness/pretrained.json")


def test_frozen_supported_clinical_representation_pins():
    protocol = load_pretrained_protocol(PATH)
    assert [(r.name, r.vector_width) for r in protocol.representations] == [
        ("meanpool_hr", 76),
        ("wbm_hr", 256),
        ("moment_hr", 1024),
        ("chronos_hr", 768),
    ]
    assert protocol.representations[-1].auxiliary_features == ("loc_bpm", "scale_bpm")
    assert protocol.outer_test == "sealed-not-opened"
    assert protocol.prior_cpu_development_scores_seen
    assert not protocol.feature_scores_seen_at_freeze


@pytest.mark.parametrize("change", ["width", "revision", "scores-seen", "pca"])
def test_reject_changed_supported_shape_or_frozen_choices(tmp_path, change):
    document = json.loads(PATH.read_bytes())
    if change == "width":
        document["representations"][-1]["vector_width"] = 1024
    elif change == "revision":
        document["representations"][-1]["model_revision"] = "a" * 40
    elif change == "scores-seen":
        document["feature_scores_seen_at_freeze"] = True
    else:
        document["dimensionality_reduction"] = "pca"
    altered = tmp_path / "protocol.json"
    altered.write_text(json.dumps(document))
    with pytest.raises((ValueError, ValidationError)):
        load_pretrained_protocol(altered)


def test_summary_control_cannot_claim_a_learned_model_revision():
    document = json.loads(PATH.read_bytes())
    document["representations"][0]["model_revision"] = "a" * 40
    with pytest.raises(ValidationError):
        PretrainedProtocol.model_validate_json(json.dumps(document))
