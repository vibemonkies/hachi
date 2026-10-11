"""Generated owner-format exports; no checkpoint, GPU or private data is used."""

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from hachi.contracts.base import ArtifactRef
from hachi.contracts.manifests import RunManifest, SplitManifest
from hachi.evaluation.finalization.development import validate_development
from hachi.evaluation.finalization.integrity import EvidenceRefused, digest
from hachi.evaluation.pmdata_run import PMDataProtocol
from hachi.evaluation.serialization import document_bytes, document_sha256
from hachi.models.chronos import ChronosConfig, ChronosModelPin
from hachi.models.chronos.artifacts import ChronosArtifact, save_artifact

from ..conftest import BASE
from .test_development import generated_bundle as generated_bundle
from .test_development import reindex


@pytest.fixture(params=["chronos", "encoder"])
def generated_export(generated_bundle, request):
    root, _, repo, packet, result = generated_bundle
    import hachi.models.chronos.artifacts as implementation

    package = Path(implementation.__file__).parents[2]
    shutil.copytree(
        package,
        repo / "src/hachi",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    split = SplitManifest.model_validate_json((packet / "split.json").read_bytes())
    split = split.model_copy(
        update={
            "dataset_snapshot": split.dataset_snapshot.model_copy(update={"dataset_id": "pmdata"}),
            "fold": 0,
            "n_folds": 4,
        }
    )
    actual_repo = Path(__file__).resolve().parents[3]
    protocol = PMDataProtocol.model_validate_json(
        (actual_repo / "configs/evaluation/pmdata-hourly-validation.json").read_bytes()
    )
    protocol = protocol.model_copy(
        update={
            "expected_snapshot": split.dataset_snapshot,
            "evaluation": result.config,
            **{
                k: getattr(split, k)
                for k in (PMDataProtocol.model_fields.keys() & SplitManifest.model_fields.keys())
            },
        }
    )
    (root / "protocol.json").write_bytes(document_bytes(protocol))
    original = repo / "configs/generated-protocol.json"
    original.parent.mkdir()
    original.write_text(json.dumps(json.loads(document_bytes(protocol)), indent=2) + "\n")
    subprocess.run(["git", "add", "src", "configs"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Generated Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "Generated export source",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    model_root = root / "fold/models/generated-export"
    run = RunManifest.model_validate_json((packet / "run.json").read_bytes())
    if request.param == "chronos":
        pin = ChronosModelPin(
            model_id="amazon/chronos-2",
            revision="a" * 40,
            weights_sha256="b" * 64,
            license="Apache-2.0",
            runtime_lock_sha256="c" * 64,
        )
        model = ChronosArtifact(
            model_id="chronos-2-zero-shot",
            protocol_sha256=document_sha256(protocol),
            harness_lookback_hours=split.lookback_hours,
            chronos=ChronosConfig(
                model=pin,
                metric="heart_rate",
                aggregation="mean",
                context_hours=split.lookback_hours,
            ),
        )
        ref = save_artifact(model_root, model, artifact_id=model_root.name)
        descriptor = run.model.model_copy(
            update={
                "model_id": model.model_id,
                "checkpoint_source": pin.model_id,
                "checkpoint_revision": pin.revision,
                "license": pin.license,
            }
        )
        env = pin.runtime_lock_sha256
        feature_order = ["heart_rate"]
    else:
        pytest.importorskip("numpy")
        from hachi.models.baselines.tree import FEATURES, TreeConfig
        from hachi.models.encoders.config import Candidate, EncoderExperiment, ProtocolRef
        from hachi.models.encoders.head import HeadConfig, RidgeHeadArtifact
        from hachi.models.encoders.run import save_head
        from hachi.models.encoders.windows import WindowConfig

        head_config = HeadConfig(
            tree=TreeConfig(metric="heart_rate", aggregation="mean"),
            ridge_alpha=10.0,
            pca_components=1,
            phase_interactions=False,
            max_staleness_hours=48,
        )
        candidates = (
            Candidate(
                name="generated-head",
                blocks=("handcrafted",),
                role="primary",
                pretrained_cohort_overlap="not_applicable",
            ),
            Candidate(
                name="generated-embedding",
                blocks=("meanpool",),
                role="primary",
                pretrained_cohort_overlap="unknown",
            ),
        )
        experiment = EncoderExperiment(
            protocol=ProtocolRef(
                path="configs/generated-protocol.json", sha256=digest(original.read_bytes())
            ),
            window=WindowConfig(as_of_delay_hours=16, local_timezone="Europe/Oslo"),
            head=head_config,
            tables=("meanpool",),
            baseline="generated-head",
            candidates=candidates,
            overlap_notes={"unknown": "Generated checkpoint disclosure"},
        )
        (root / "experiment.json").write_bytes(document_bytes(experiment))
        (root / "tables.json").write_bytes(document_bytes({"meanpool": {"sha256": "a" * 64}}))
        width = len(FEATURES)
        model = RidgeHeadArtifact(
            model_id="generated-head",
            config=head_config,
            blocks=("handcrafted",),
            support=("meanpool",),
            embedding_sha256={"meanpool": "a" * 64},
            fit_as_of=BASE,
            training_prefix_sha256="d" * 64,
            training_examples=1,
            training_subjects=1,
            projections={},
            feature_mean=(0.0,) * width,
            feature_scale=(1.0,) * width,
            column_mean=(0.0,) * width,
            coefficients=(0.0,) * width,
            intercept=60.0,
            label_min=40.0,
            label_max=100.0,
        )
        ref = save_head(model_root, model)
        descriptor = run.model.model_copy(update={"model_id": model.model_id})
        env = run.environment_sha256
        feature_order = list(FEATURES)
    run = run.model_copy(
        update={
            "git_sha": sha,
            "artifact": ref,
            "model": descriptor,
            "environment_sha256": env,
            "feature_order": feature_order,
            "dataset_snapshot": split.dataset_snapshot,
            "split_manifest_sha256": document_sha256(split),
        }
    )
    (packet / "run.json").write_bytes(document_bytes(run))
    (packet / "split.json").write_bytes(document_bytes(split))
    (packet / "evaluation.json").write_bytes(
        document_bytes(replace(result, split_manifest_sha256=document_sha256(split)))
    )
    return root, reindex(root), repo, packet, model_root, request.param


def test_accepts_owner_formats_without_loading_predictors(generated_export):
    root, pin, repo, _, _, _ = generated_export
    receipt = validate_development(root, pin, repo)
    assert len(receipt.evaluations) == 1 and receipt.evaluations[0].artifact is not None
    assert not receipt.final_test_authorized


@pytest.mark.parametrize(
    "mutation", ["source_omission", "runtime_or_table", "protocol_or_config", "evaluator"]
)
def test_export_bindings_cannot_be_changed_even_after_rehash(generated_export, mutation):
    root, _, repo, packet, model_root, kind = generated_export
    if mutation == "source_omission":
        path = model_root / "source-sha256.json"
        doc = json.loads(path.read_bytes())
        del doc["evaluation/features.py"]
    elif mutation == "runtime_or_table":
        path = packet / "run.json" if kind == "chronos" else root / "tables.json"
        doc = json.loads(path.read_bytes())
        if kind == "chronos":
            doc["environment_sha256"] = "0" * 64
        else:
            doc["meanpool"]["sha256"] = "0" * 64
    elif mutation == "evaluator":
        path = packet / "config.json"
        doc = json.loads(path.read_bytes())
        doc["history_policy"] = "population_only"
        evaluation = json.loads((packet / "evaluation.json").read_bytes())
        evaluation["config"] = doc
        (packet / "evaluation.json").write_bytes(document_bytes(evaluation))
        run_doc = json.loads((packet / "run.json").read_bytes())
        run_doc["config_sha256"] = document_sha256(doc)
        (packet / "run.json").write_bytes(document_bytes(run_doc))
    else:
        path = model_root / "model.json"
        doc = json.loads(path.read_bytes())
        if kind == "chronos":
            doc["protocol_sha256"] = "0" * 64
        else:
            doc["config"]["ridge_alpha"] += 1.0
    path.write_bytes(document_bytes(doc))
    receipt_path = model_root / "artifact.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["files"] = {name: digest((model_root / name).read_bytes()) for name in receipt["files"]}
    receipt_path.write_bytes(document_bytes(receipt))
    run = RunManifest.model_validate_json((packet / "run.json").read_bytes())
    run = run.model_copy(
        update={
            "artifact": ArtifactRef(
                artifact_id=receipt["artifact_id"], artifact_sha256=document_sha256(receipt)
            )
        }
    )
    (packet / "run.json").write_bytes(document_bytes(run))
    with pytest.raises(EvidenceRefused):
        validate_development(root, reindex(root), repo)
