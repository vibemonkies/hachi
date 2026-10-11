import json
from pathlib import Path

import pytest

pytest.importorskip("numpy", reason="the encoder experiment requires the optional baselines extra")

from hachi.evaluation.pmdata_run import PMDataProtocol
from hachi.models.encoders.config import REPO, EncoderExperiment

CONFIG = REPO / "configs/models/encoders"


def test_experiment_binds_the_shared_protocol_and_the_tree_feature_definition():
    experiment = EncoderExperiment.model_validate_json(
        (CONFIG / "pmdata-encoders.json").read_bytes()
    )
    protocol = PMDataProtocol.model_validate_json(experiment.protocol.resolve().read_bytes())
    assert experiment.head.tree == protocol.tree
    assert experiment.window.local_timezone == "Europe/Oslo"
    by_name = {c.name: c for c in experiment.candidates}
    assert by_name[experiment.baseline].blocks == ("handcrafted",)
    assert {"ridge-handcrafted-wbm", "ridge-handcrafted-moment"} <= set(by_name)


def test_experiment_refuses_a_changed_protocol(tmp_path: Path):
    raw = json.loads((CONFIG / "pmdata-encoders.json").read_text())
    raw["protocol"]["sha256"] = "0" * 64
    experiment = EncoderExperiment.model_validate(raw, strict=False)
    with pytest.raises(ValueError, match="binds a different protocol"):
        experiment.protocol.resolve()


def test_checkpoint_pins_record_revisions_hashes_and_license_terms():
    wbm = json.loads((CONFIG / "wbm.json").read_text())
    moment = json.loads((CONFIG / "moment.json").read_text())
    assert len(wbm["checkpoint"]["revision"]) == 40 and len(moment["checkpoint"]["revision"]) == 40
    assert all(
        len(h) == 64
        for h in [*wbm["checkpoint"]["files"].values(), *moment["checkpoint"]["files"].values()]
    )
    assert len(wbm["input"]["normalization"]["means"]) == 19
    assert "CC BY 4.0" in wbm["license"]["relied_on"] and moment["license"]["relied_on"] == "MIT"
