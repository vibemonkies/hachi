import json
from pathlib import Path

import pytest

from hachi.models.recovery.protocol import Protocol

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("source", ["phase1", "cmu"])
def test_committed_protocol_has_native_predictors_and_separate_horizons(source):
    document = json.loads((ROOT / f"configs/experiments/recovery/{source}.json").read_bytes())
    protocol = Protocol.model_validate_json(json.dumps(document))
    assert protocol.outcome_scope == "active-outer-development-only"
    assert protocol.censoring == "last-observed-symptomatic-or-intermediate-day"
    document["feature_order"] = ["a-shared-severity-scale"]
    with pytest.raises(ValueError, match="native"):
        Protocol.model_validate_json(json.dumps(document))


def test_cmu_rejects_long_horizon_transfer():
    document = json.loads((ROOT / "configs/experiments/recovery/cmu.json").read_bytes())
    document.update(primary_horizon_days=7, maximum_export_days=14, calibration_days=[3, 7, 14])
    with pytest.raises(ValueError, match="short-follow-up"):
        Protocol.model_validate_json(json.dumps(document))
