"""Synthetic fixtures for the API: a PMData-layout snapshot, Apple exports and a served artifact.

Every value is generated: the snapshot comes from tests/data/pmdata's synthetic archive and
the artifact is fitted on it. Nothing here reads real data.
"""

import importlib.util
import os
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from xml.sax.saxutils import quoteattr

import pytest

from hachi.api.artifacts import ServingSpec, stage_artifact
from hachi.api.settings import Settings
from hachi.contracts.base import ArtifactRef
from hachi.contracts.manifests import ModelRef, RunManifest, SplitManifest
from hachi.data.pmdata import AGGREGATE_AVAILABILITY_RULE, build, dataset_snapshot_ref, load_config
from hachi.data.pmdata.snapshot import GitState
from hachi.evaluation import EvaluationConfig, TrainingPrefix
from hachi.evaluation.features import HourlyFeaturePolicy
from hachi.evaluation.serialization import document_bytes, document_sha256
from hachi.models.baselines import BaselineConfig, fit_baseline, save_artifact
from hachi.storage import Workspace

# The API needs the optional `api` extra; CI runs these tests with `--extra api`.
if importlib.util.find_spec("fastapi") is None:
    collect_ignore_glob = ["test_*.py"]

GIT_SHA = "a" * 40
FIT_AS_OF = datetime(2020, 3, 28, 0, tzinfo=UTC)
HR_POLICY = HourlyFeaturePolicy(
    metric="heart_rate",
    aggregation="mean",
    min_coverage=0.5,
    min_observed_count=1,
    availability_rule=AGGREGATE_AVAILABILITY_RULE,
)


def _pmdata_fixtures():
    path = Path(__file__).parents[1] / "data" / "pmdata" / "conftest.py"
    spec = importlib.util.spec_from_file_location("pmdata_synthetic_archive", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def data_root(tmp_path_factory) -> Path:
    """A data root holding one synthetic snapshot under derived/."""
    fixtures = _pmdata_fixtures()
    root = tmp_path_factory.mktemp("data-root")
    archive = root / "pmdata-synthetic.zip"
    admission = fixtures.write_archive(archive, fixtures.build_members())
    build(archive, root / "derived", load_config(), admission, GitState("0" * 40, False))
    return root


@pytest.fixture(scope="session")
def snapshot_id(data_root) -> str:
    (path,) = [p for p in (data_root / "derived").iterdir() if not p.name.startswith(".")]
    return path.name


@dataclass(frozen=True)
class Packet:
    model_dir: Path
    packet_dir: Path
    serving: ServingSpec


def make_packet(
    base: Path,
    snapshot_dir: Path,
    *,
    config: BaselineConfig | None = None,
    serving: ServingSpec | None = None,
    feature_order: list[str] | None = None,
    artifact_id: str = "synthetic-last-valid-hr",
) -> Packet:
    """Fit a baseline, save it, and write the evaluation packet files it would ship with."""
    config = config or BaselineConfig(method="last_valid", metric="heart_rate", aggregation="mean")
    model = fit_baseline(TrainingPrefix(FIT_AS_OF, ("p01",), ()), config)
    model_dir = base / "model"
    ref = save_artifact(model_dir, model, artifact_id=artifact_id)
    snapshot = dataset_snapshot_ref(snapshot_dir)
    split = SplitManifest(
        schema_version="0.1",
        manifest_id="synthetic-split",
        created_at_utc=FIT_AS_OF,
        dataset_snapshot=snapshot,
        task="physiology_forecast",
        fold=None,
        n_folds=None,
        train_subjects=["p02"],
        validation_subjects=["p01"],
        test_subjects=[],
        exclusions=[],
        lookback_hours=48,
        horizon_hours=24,
        embargo_hours=0,
        cutoff_stride_hours=24,
        min_history_hours=24,
        evaluation_window=None,
        seed=7,
        test_opened_at_utc=None,
    )
    evaluation = EvaluationConfig(
        data_mode="synthetic",
        metric=config.metric,
        aggregation=config.aggregation,
        history_policy="causal_prefix",
        pretrained_cohort_overlap="not_applicable",
        overlap_note="Synthetic API fixture.",
        bootstrap_samples=10,
        confidence=0.9,
    )
    run = RunManifest(
        schema_version="0.1",
        run_id="synthetic-run",
        created_at_utc=FIT_AS_OF,
        git_sha=GIT_SHA,
        git_dirty=False,
        config_sha256=document_sha256(evaluation),
        dataset_snapshot=snapshot,
        split_manifest_sha256=document_sha256(split),
        task="physiology_forecast",
        feature_order=feature_order or [config.metric],
        model=ModelRef(
            model_id=model.model_id, checkpoint_source=None, checkpoint_revision=None, license=None
        ),
        environment_sha256="b" * 64,
        seed=7,
        artifact=ref,
        metrics_paths=["evaluation.json"],
    )
    packet_dir = base / "packet"
    packet_dir.mkdir()
    for name, document in (("run.json", run), ("split.json", split), ("config.json", evaluation)):
        (packet_dir / name).write_bytes(document_bytes(document))
    serving = serving or ServingSpec(
        format_version="hachi-serving-1",
        task="physiology_forecast",
        resolution="hour",
        entry_point="hachi.models.baselines.load_artifact",
        input="hourly_features",
        feature_policy=HR_POLICY,
    )
    return Packet(model_dir, packet_dir, serving)


@pytest.fixture(scope="session")
def served(tmp_path_factory, data_root, snapshot_id) -> tuple[Path, ArtifactRef]:
    root = tmp_path_factory.mktemp("artifacts")
    packet = make_packet(tmp_path_factory.mktemp("packet"), data_root / "derived" / snapshot_id)
    pin = stage_artifact(root, packet.model_dir, packet.packet_dir, packet.serving)
    return root, pin


@pytest.fixture
def make_settings(tmp_path, data_root, snapshot_id, served):
    def factory(**changes) -> Settings:
        artifact_root, pin = served
        workspaces = tmp_path / "workspaces"
        workspace = Workspace.for_owner("tester", workspaces)
        values = {
            "owner": "tester",
            "workspace": workspace,
            "database": workspace.default_database,
            "git_sha": GIT_SHA,
            "data_root": data_root,
            "dataset_snapshots": (snapshot_id,),
            "artifact_root": artifact_root,
            "served_artifacts": (pin,),
            "allow_unadmitted_snapshots": True,
        }
        values.update(changes)
        return Settings(**values)

    return factory


@pytest.fixture
def open_client(make_settings):
    clients = []

    from fastapi.testclient import TestClient

    from hachi.api.app import create_app

    def factory(settings: Settings | None = None, **kwargs) -> TestClient:
        app = create_app(settings or make_settings(), extra_hosts=frozenset({"testserver"}))
        client = TestClient(app, **kwargs)
        client.__enter__()
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(open_client):
    return open_client()


def wait(client) -> None:
    assert client.app.state.service.runner.wait_idle(30)


# Apple Health exports -------------------------------------------------------------------


def heart_rate_record(start: str, value: str = "64", **changes) -> dict[str, str]:
    attrs = {
        "type": "HKQuantityTypeIdentifierHeartRate",
        "unit": "count/min",
        "value": value,
        "sourceName": "Synthetic Apple Watch",
        "device": "<HKDevice: name:Private, model:Watch>",
        "startDate": start,
        "endDate": start,
        "creationDate": start,
    }
    attrs.update(changes)
    return attrs


def export_xml(records: list[dict[str, str]]) -> bytes:
    rows = [
        "<Record " + " ".join(f"{k}={quoteattr(v)}" for k, v in r.items()) + "/>" for r in records
    ]
    return ("<HealthData>" + "".join(rows) + "</HealthData>").encode()


def hourly_export(hours: int, start_day: int = 1) -> bytes:
    """Heart rate every hour for `hours` hours, starting 2026-09-<start_day> 00:00 UTC."""
    records = []
    for h in range(hours):
        day, hour = start_day + h // 24, h % 24
        stamp = f"2026-09-{day:02d} {hour:02d}:10:00 +0000"
        records.append(heart_rate_record(stamp, str(60 + h % 7)))
    return export_xml(records)


def zipped(members: dict[str, bytes]) -> bytes:
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def upload(client, body: bytes, *, subject="synthetic-apple-001", **params):
    query = {
        "subject_id": subject,
        "tz_name": "America/Los_Angeles",
        "source_format": "apple_health_export_xml",
        "data_mode": "synthetic",
        **params,
    }
    return client.post(
        "/v1/imports", params=query, content=body, headers={"Content-Type": "application/xml"}
    )


def private_files(path: Path) -> list[str]:
    return sorted(os.listdir(path)) if path.exists() else []
