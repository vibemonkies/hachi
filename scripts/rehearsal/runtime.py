"""Private, isolated #22 API rehearsal; stdout contains aggregate evidence only.

Run with the checkout's locked api+baselines environment. See README.md here.
No participant rows, requests, saved results or predictions are published.
"""

import argparse
import hashlib
import json
import logging
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hachi.api.__main__ import serving_from_protocol
from hachi.api.artifacts import load_served_artifact, stage_artifact
from hachi.api.catalog import Catalog
from hachi.api.handoff import direct_inference, expected_points, load_packet
from hachi.api.settings import Settings, git_dirty, git_sha, parse_pin
from hachi.contracts.api import Coverage, HealthStatus, ImportStatus, ReportJob, SelfReportHistory
from hachi.contracts.base import SCHEMA_VERSION, Contract, Identifier
from hachi.contracts.manifests import SplitManifest
from hachi.contracts.results import PhysiologyForecastResult, ReportResult
from hachi.evaluation import ForecastEstimate
from hachi.storage import private_directory

REPO = Path(__file__).resolve().parents[2]


class RehearsalFailure(Exception):
    """Only deliberately sanitized messages cross the command boundary."""


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RehearsalFailure(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_medians(cutoff: datetime, estimates) -> dict:
    """Medians only, as handoff returned them before #76 widened its points to tuples."""
    return {start: point[0] for start, point in expected_points(cutoff, estimates).items()}


def write_private(path: Path, value: object) -> None:
    private_directory(path.parent)
    with path.open("x", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        stream.write(json.dumps(value, indent=2) + "\n")


class Operator(Contract):
    format_version: str
    owner: Identifier
    runtime_root: str
    data_root: str
    snapshot_id: str
    packet: str
    packet_index: str
    packet_index_sha256: str
    artifact_pin: str
    api_port: int
    web_port: int
    git_sha: str
    protocol_sha256: str

    def settings(self) -> Settings:
        root = Path(self.runtime_root)
        return Settings.from_environment(
            environ={
                "HACHI_OWNER": self.owner,
                "HACHI_WORKSPACES": str(root / "workspaces"),
                "HACHI_DB_PATH": str(root / "state" / "metadata.sqlite3"),
                "HACHI_DATA_ROOT": self.data_root,
                "HACHI_DATASET_SNAPSHOTS": self.snapshot_id,
                "HACHI_ARTIFACT_ROOT": str(root / "artifacts"),
                "HACHI_SERVE_ARTIFACTS": self.artifact_pin,
                "HACHI_API_CORS_ORIGINS": f"http://127.0.0.1:{self.web_port}",
                "HACHI_GIT_SHA": self.git_sha,
            }
        )


def load_operator(root: Path) -> Operator:
    operator = Operator.model_validate_json((root / "operator.json").read_bytes())
    require(operator.format_version == "hachi-rehearsal-2", "Unknown operator format")
    require(Path(operator.runtime_root).resolve() == root.resolve(), "Runtime root moved")
    require(operator.git_sha == git_sha(REPO), "Checkout changed; prepare a fresh runtime")
    require(git_dirty(REPO) is False, "Rehearsal requires a clean committed checkout")
    require(1 <= operator.api_port <= 65535, "Invalid API port")
    require(1 <= operator.web_port <= 65535, "Invalid web port")
    return operator


def validation_packet(packet: Path, packet_index: Path):
    published = json.loads(packet_index.read_bytes())
    key = "/".join(packet.parts[-3:])
    require(key in published["packets"], "Packet is not in the published frozen index")
    for name, sha in published["packets"][key].items():
        require(digest(packet / name) == sha, "Packet differs from published frozen evidence")
    run, evaluation = load_packet(packet)
    split = SplitManifest.model_validate_json((packet / "split.json").read_bytes())
    require(run.split_manifest_sha256 == digest(packet / "split.json"), "Split hash mismatch")
    require(split.test_opened_at_utc is None, "Outer test must remain sealed")
    require(bool(evaluation["predictions"]), "Packet has no origins")
    validation = set(split.validation_subjects)
    require(not validation.intersection(split.test_subjects), "Split overlap")
    require(
        all(p["origin"]["subject_id"] in validation for p in evaluation["predictions"]),
        "Only inner-validation origins may be rehearsed",
    )
    return run, evaluation


def prepare(args) -> dict:
    require(git_dirty(REPO) is False, "Commit scoped work before preparing a runtime")
    require(not args.runtime_root.exists(), "Runtime root exists; use a fresh owned directory")
    require(
        not args.runtime_root.resolve().is_relative_to(REPO), "Keep private runtime outside Git"
    )
    require(args.api_port != args.web_port, "API and web ports must differ")
    run, _ = validation_packet(args.packet, args.packet_index)
    published = json.loads(args.packet_index.read_bytes())
    require(digest(args.protocol) == published["protocol_sha256"], "Protocol is not frozen")
    root = private_directory(args.runtime_root.resolve())
    spec = serving_from_protocol(args.protocol, args.model)
    pin = stage_artifact(private_directory(root / "artifacts"), args.model, args.packet, spec)
    require(pin == run.artifact, "Staged pin differs from frozen packet")
    operator = Operator(
        format_version="hachi-rehearsal-2",
        owner=args.owner,
        runtime_root=str(root),
        data_root=str(args.data_root.resolve()),
        snapshot_id=args.snapshot_id,
        packet=str(args.packet.resolve()),
        packet_index=str(args.packet_index.resolve()),
        packet_index_sha256=digest(args.packet_index),
        artifact_pin=f"{pin.artifact_id}@{pin.artifact_sha256}",
        api_port=args.api_port,
        web_port=args.web_port,
        git_sha=git_sha(REPO),
        protocol_sha256=digest(args.protocol),
    )
    catalog = Catalog.load(operator.settings())
    require(not catalog.problems, "Configured snapshot or artifact refused")
    require(len(catalog.datasets) == len(catalog.artifacts) == 1, "Expected one dataset/artifact")
    require(catalog.datasets[0].ref == run.dataset_snapshot, "Snapshot differs from packet")
    require(catalog.datasets[0].data_mode == "real", "Requires an admitted real snapshot")
    write_private(root / "operator.json", operator.model_dump())
    return {"prepared": True, "git_sha": operator.git_sha, "artifact": pin.model_dump()}


def serve(operator: Operator) -> None:
    import uvicorn

    from hachi.api.app import create_app

    # Fail before creating mutable state if another worker owns this listener.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", operator.api_port))
    uvicorn.run(
        create_app(operator.settings()),
        host="127.0.0.1",
        port=operator.api_port,
        access_log=False,
        log_level="warning",
    )


class Client:
    def __init__(self, port: int):
        self.base = f"http://127.0.0.1:{port}"
        # Private loopback requests must never inherit an operator's HTTP proxy.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, method: str, path: str, body: object = None, *, raw: bytes | None = None):
        data = raw if raw is not None else None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            request.add_header(
                "Content-Type", "application/xml" if raw is not None else "application/json"
            )
        try:
            with self.opener.open(request, timeout=60) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def report(self, body: dict) -> ReportJob:
        status, payload = self.call("POST", "/v1/reports", body)
        require(status in (200, 202), "Report submission failed")
        job = ReportJob.model_validate_json(payload)
        deadline = time.monotonic() + 60
        while job.state != "completed":
            require(time.monotonic() < deadline, "Report timed out")
            time.sleep(0.05)
            status, payload = self.call("GET", f"/v1/reports/{job.report_id}")
            require(status == 200, "Report poll failed")
            job = ReportJob.model_validate_json(payload)
        return job


def agreement(shown: dict, expected: dict) -> dict:
    common = shown.keys() & expected.keys()
    differences = [abs(shown[k] - expected[k]) for k in common]
    return {
        "points_compared": len(common),
        "points_mismatched": sum(d != 0 for d in differences),
        "missing_api_points": len(expected.keys() - shown.keys()),
        "extra_api_points": len(shown.keys() - expected.keys()),
        "max_abs_difference": max(differences, default=0.0),
    }


def forecast_request(origin: dict, metric: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "subject_id": origin["subject_id"],
        "as_of": origin["cutoff"],
        "task": "physiology_forecast",
        "resolution": "hour",
        "horizon_hours": len(origin["targets"]),
        "metrics": [metric],
    }


def check(operator: Operator) -> dict:
    settings = operator.settings()
    catalog = Catalog.load(settings)
    require(not catalog.problems, "Local inputs refused")
    served = load_served_artifact(settings.artifact_root, parse_pin(operator.artifact_pin))
    require(
        digest(Path(operator.packet_index)) == operator.packet_index_sha256,
        "Published packet index changed",
    )
    run, evaluation = validation_packet(Path(operator.packet), Path(operator.packet_index))
    require(served.ref == run.artifact, "Packet/artifact disagreement")
    require(
        served.serving.input == "hourly_features" and served.serving.feature_policy is not None,
        "This rehearsal checks hourly-feature artifacts",
    )
    client = Client(operator.api_port)
    status, payload = client.call("GET", "/healthz")
    require(status == 200, "Health request failed")
    health = HealthStatus.model_validate_json(payload)
    require(health.git_sha == operator.git_sha, "Different runtime commit answered")
    require(health.status == "ok", "API is degraded")
    require(health.artifacts == [served.ref], "Different artifacts served")
    tallies = {name: Counter() for name in ("packet", "direct")}
    outcomes: Counter = Counter()
    warnings: Counter = Counter()
    durations = []
    first_request = None
    first_job = None
    for prediction in evaluation["predictions"]:
        origin = prediction["origin"]
        subject = catalog.dataset_subject(origin["subject_id"])
        require(subject is not None and subject.data_mode == "real", "Real subject not available")
        cutoff = datetime.fromisoformat(origin["cutoff"])
        request = forecast_request(origin, served.metric)
        started = time.monotonic()
        job = client.report(request)
        durations.append(time.monotonic() - started)
        if first_request is None:
            first_request, first_job = request, job
        result = job.result.root
        outcomes[result.status] += 1
        require(
            result.subject_id == origin["subject_id"]
            and result.as_of == cutoff
            and result.report_id == job.report_id,
            "Result subject, cutoff or job identity differs",
        )
        require(result.git_sha == health.git_sha, "Result code identity differs")
        require(
            result.data_mode == "real" and result.replay is None, "Result is not a real live run"
        )
        estimates = tuple(
            None if e is None else ForecastEstimate.model_validate(e)
            for e in prediction["estimates"]
        )
        expected = expected_medians(cutoff, estimates)
        direct = expected_medians(
            cutoff, direct_inference(served, subject, cutoff, len(origin["targets"]))
        )
        shown = {}
        if isinstance(result, PhysiologyForecastResult):
            require(result.provenance.artifact == served.ref, "Result artifact differs")
            require(
                result.provenance.dataset_snapshot == run.dataset_snapshot,
                "Result snapshot differs",
            )
            require(len(result.forecast.series) == 1, "Unexpected forecast series count")
            series = result.forecast.series[0]
            require(series.metric == served.metric and series.unit == "bpm", "Metric/unit differs")
            require(
                series.interval_calibration == "none" and series.nominal_coverage is None,
                "Point forecast claims intervals",
            )
            require(
                all(p.lower is None and p.upper is None for p in series.points),
                "Point forecast has bounds",
            )
            require(
                all(0 <= f.coverage <= 1 for f in result.provenance.feature_coverage),
                "Invalid quality coverage",
            )
            history = subject.hourly_features(
                served.serving.feature_policy,
                cutoff,
                start=cutoff - timedelta(hours=served.split.lookback_hours),
            )
            observed = {f.start_utc for f in history if f.value is not None}
            require(
                len(result.provenance.feature_coverage) == 1
                and result.provenance.feature_coverage[0].metric == served.metric
                and result.provenance.feature_coverage[0].coverage
                == len(observed) / served.split.lookback_hours,
                "Feature coverage differs from source history",
            )
            warnings.update(w.code for w in result.warnings)
            require(
                "UNCALIBRATED_INTERVALS" not in warnings, "Point forecast carries interval warning"
            )
            shown = {p.interval_start_utc: p.median for p in series.points}
        else:
            require(
                result.status == "unavailable" and not expected and not direct,
                "Unexpected forecast failure/abstention",
            )
        for name, reference in (("packet", expected), ("direct", direct)):
            summary = agreement(shown, reference)
            for key, value in summary.items():
                if key == "max_abs_difference":
                    tallies[name][key] = max(tallies[name][key], value)
                else:
                    tallies[name][key] += value
    require(
        all(
            t["points_compared"] > 0
            and not any(
                t[k] for k in ("points_mismatched", "missing_api_points", "extra_api_points")
            )
            for t in tallies.values()
        ),
        "Numeric equality failed",
    )
    require(
        client.report(first_request).report_id == first_job.report_id,
        "Report retry is not idempotent",
    )
    origin = evaluation["predictions"][0]["origin"]
    status, payload = client.call(
        "GET",
        f"/v1/subjects/{origin['subject_id']}/coverage?"
        + urllib.parse.urlencode({"as_of": origin["cutoff"]}),
    )
    require(status == 200, "Coverage failed")
    coverage = Coverage.model_validate_json(payload)
    require(
        coverage.data_mode == "real" and coverage.dataset_snapshot == run.dataset_snapshot,
        "Coverage provenance differs",
    )
    require(
        coverage.span_end_utc <= datetime.fromisoformat(origin["cutoff"]), "Coverage exceeds cutoff"
    )
    unavailable = {}
    for task, fields in (
        ("anomaly", {}),
        ("illness_onset", {"horizon_hours": 24}),
        ("recovery", {"episode_id": "rehearsal-no-episode"}),
    ):
        job = client.report(
            {
                "schema_version": SCHEMA_VERSION,
                "subject_id": origin["subject_id"],
                "as_of": origin["cutoff"],
                "task": task,
                **fields,
            }
        )
        result = job.result.root
        require(result.status == "unavailable", "Unsupported task unexpectedly available")
        unavailable[task] = result.reason_code
    synthetic = synthetic_checks(client)
    # A saved live response is private. It is not an implemented offline replay.
    saved = Path(operator.runtime_root) / "private-results" / "live-report.json"
    if not saved.exists():
        write_private(saved, first_job.model_dump(mode="json"))
    return {
        "format_version": "hachi-rehearsal-evidence-1",
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "git_sha": operator.git_sha,
        "owner": operator.owner,
        "script_sha256": digest(Path(__file__)),
        "uv_lock_sha256": digest(REPO / "uv.lock"),
        "python": sys.version.split()[0],
        "artifact": served.ref.model_dump(),
        "dataset_snapshot": run.dataset_snapshot.model_dump(),
        "protocol_sha256": operator.protocol_sha256,
        "packet_sha256": digest(Path(operator.packet) / "sha256.json"),
        "published_packet_index_sha256": operator.packet_index_sha256,
        "published_packet_key": "/".join(Path(operator.packet).parts[-3:]),
        "published_packet_digests": json.loads(Path(operator.packet_index).read_bytes())["packets"][
            "/".join(Path(operator.packet).parts[-3:])
        ],
        "api_port": operator.api_port,
        "web_port": operator.web_port,
        "real": {
            "origins": len(evaluation["predictions"]),
            "outcomes": dict(outcomes),
            "comparison": {k: dict(v) for k, v in tallies.items()},
            "warnings": dict(warnings),
            "point_only": True,
            "report_retry_idempotent": True,
            "latency_seconds": {
                "min": min(durations),
                "max": max(durations),
                "mean": sum(durations) / len(durations),
            },
            "unavailable": unavailable,
            "outer_test_opened": False,
        },
        "synthetic_api_lifecycle": synthetic,
        "gates": {
            "real_import_to_chart": "pending #17",
            "offline_replay": "saved response only; not rendered",
            "full_issue_22": "blocked #17/#18/#19/#20/#21",
        },
    }


def synthetic_checks(client: Client) -> dict:
    """Exercise import and check-in transport using invented, visibly synthetic data."""
    subject = "synthetic-rehearsal-safe"
    path = "/v1/imports?" + urllib.parse.urlencode(
        {
            "subject_id": subject,
            "tz_name": "Etc/UTC",
            "source_format": "apple_health_export_xml",
            "data_mode": "synthetic",
        }
    )
    xml = (
        b'<HealthData><Record type="HKQuantityTypeIdentifierHeartRate" '
        b'sourceName="Synthetic rehearsal" unit="count/min" value="70" '
        b'startDate="2026-09-01 00:00:00 +0000" endDate="2026-09-01 00:00:00 +0000" '
        b'creationDate="2026-09-01 00:00:00 +0000"/></HealthData>'
    )
    status, payload = client.call("POST", path, raw=xml)
    require(status in (200, 202), "Synthetic upload failed")
    imported = ImportStatus.model_validate_json(payload)
    deadline = time.monotonic() + 60
    while imported.state in ("pending", "running"):
        require(time.monotonic() < deadline, "Synthetic import timed out")
        time.sleep(0.05)
        _, payload = client.call("GET", f"/v1/imports/{imported.import_id}")
        imported = ImportStatus.model_validate_json(payload)
    require(
        imported.state == "succeeded" and imported.data_mode == "synthetic",
        "Synthetic import not successful",
    )
    status, payload = client.call("GET", f"/v1/subjects/{subject}/coverage")
    coverage = Coverage.model_validate_json(payload)
    require(status == 200 and coverage.history == "insufficient", "Sparse fixture not insufficient")
    body = {
        "schema_version": SCHEMA_VERSION,
        "entries": [
            {
                "kind": "symptom_checkin",
                "entry_id": "synthetic-checkin",
                "entered_at_utc": "2026-09-02T00:00:00Z",
                "period_start_utc": "2026-09-01T00:00:00Z",
                "period_end_utc": "2026-09-02T00:00:00Z",
                "symptoms_present": False,
                "symptoms": [],
                "severity": None,
            }
        ],
    }
    status, _ = client.call("POST", f"/v1/subjects/{subject}/observations", body)
    require(status in (200, 201), "Synthetic check-in failed")
    _, payload = client.call("GET", f"/v1/subjects/{subject}/observations")
    history = SelfReportHistory.model_validate_json(payload)
    require(len(history.entries) == 1, "Synthetic history did not persist")
    malformed_path = path.replace(subject, "synthetic-rehearsal-malformed")
    _, payload = client.call("POST", malformed_path, raw=b"<HealthData><Record")
    malformed = ImportStatus.model_validate_json(payload)
    deadline = time.monotonic() + 60
    while malformed.state in ("pending", "running"):
        require(time.monotonic() < deadline, "Malformed import timed out")
        time.sleep(0.05)
        _, payload = client.call("GET", f"/v1/imports/{malformed.import_id}")
        malformed = ImportStatus.model_validate_json(payload)
    require(
        malformed.state == "failed" and malformed.failure.error_code == "MALFORMED_XML",
        "Malformed import not actionable",
    )
    scenario = {
        "schema_version": SCHEMA_VERSION,
        "subject_id": subject,
        "tz_name": "Etc/UTC",
        "schedules": [
            {
                "schedule_id": "synthetic-schedule",
                "bedtime_local": "2026-09-02T22:00:00",
                "wake_time_local": "2026-09-03T06:00:00",
            }
        ],
        "assumptions": {
            "prior_sleep_hours": 8.0,
            "caffeine": "none",
            "light_exposure": "not_modeled",
        },
    }
    status, payload = client.call("POST", "/v1/scenarios", scenario)
    result = ReportResult.model_validate_json(payload).root
    require(
        status == 200 and result.status == "unavailable", "Scenario state changed; coordinate #15"
    )
    return {
        "data_mode": "synthetic",
        "import": "succeeded",
        "coverage": "insufficient",
        "checkin_readback_entries": 1,
        "malformed_import": "MALFORMED_XML",
        "scenario": result.reason_code,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--owner", required=True)
    p.add_argument("--runtime-root", type=Path, required=True)
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--snapshot-id", required=True)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--packet", type=Path, required=True)
    p.add_argument(
        "--packet-index",
        type=Path,
        default=REPO / "reports/evaluation/pmdata-hourly-validation/packet-index.json",
    )
    p.add_argument("--protocol", type=Path, required=True)
    p.add_argument("--api-port", type=int, default=8720)
    p.add_argument("--web-port", type=int, default=5180)
    for command in ("serve", "check"):
        p = sub.add_parser(command)
        p.add_argument("--runtime-root", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    logging.disable(logging.CRITICAL)  # third-party logs can contain private paths/ids
    try:
        if args.command == "prepare":
            result = prepare(args)
        else:
            operator = load_operator(args.runtime_root)
            if args.command == "serve":
                serve(operator)
                return 0
            result = check(operator)
        print(json.dumps(result, indent=2))
        return 0
    except RehearsalFailure as error:
        print(json.dumps({"ok": False, "error": str(error)}))
    except Exception as error:
        # Pydantic errors and private reader exceptions can include raw values.
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_type": type(error).__name__,
                    "action": "Inspect inputs privately; no exception values emitted",
                }
            )
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
