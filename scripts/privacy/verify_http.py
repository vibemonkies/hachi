#!/usr/bin/env python3
"""Exercise a dedicated loopback service with generated subjects; emit sanitized evidence.

Starts only its own process on --port (default 8719), creates a disposable private
state directory, and deletes only that directory. No source data or models are loaded.
"""

import argparse
import hashlib
import io
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

# Controlled fault injection exercises the production CLI's Uvicorn traceback filter.
# Only this generated subject fails; upload/delete/report paths are unmodified.
FAULT_PROBE = """
import sys
from hachi.api.service import Service
from hachi.api.__main__ import main
original = Service.coverage
def coverage(self, subject_id, params):
    if subject_id == 'synthetic-fault':
        raise RuntimeError('SYNTHETIC-PRIVATE-SENTINEL-19')
    return original(self, subject_id, params)
Service.coverage = coverage
raise SystemExit(main(sys.argv[1:]))
"""

SENTINEL = "SYNTHETIC-PRIVATE-SENTINEL-19"
XML = (
    '<HealthData><Record type="HKQuantityTypeIdentifierHeartRate" sourceName="'
    + SENTINEL
    + '" unit="count/min" value="70" creationDate="2026-09-01 00:00:00 +0000" '
    'startDate="2026-09-01 00:00:00 +0000" endDate="2026-09-01 00:00:00 +0000"/>'
    "</HealthData>"
).encode()
ONSET = {
    "kind": "symptom_onset",
    "entry_id": SENTINEL,
    "entered_at_utc": "2026-09-02T08:00:00Z",
    "onset_earliest_utc": "2026-09-01T20:00:00Z",
    "onset_latest_utc": "2026-09-02T06:00:00Z",
    "symptoms": ["cough"],
    "severity": 2,
}


def archive(name: str, body: bytes, *, symlink: bool = False) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as file:
        info = zipfile.ZipInfo(name)
        if symlink:
            info.create_system = 3
            info.external_attr = 0o120777 << 16
        file.writestr(info, body)
    return output.getvalue()


class VerificationFailed(RuntimeError):
    pass


def verify(base: str, root: Path, git_sha: str) -> dict:
    checked = []

    def require(condition: bool, label: str) -> None:
        if not condition:
            raise VerificationFailed(label)
        checked.append(label)

    def request(method, path, body=None, headers=None):
        headers = headers or {}
        if isinstance(body, dict):
            body = json.dumps(body).encode()
            headers = {"Content-Type": "application/json", **headers}
        req = urllib.request.Request(base + path, data=body, method=method, headers=headers)
        try:
            response = urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        raw = response.read()
        return response.status, json.loads(raw) if raw else None, raw

    def upload(subject, body, fmt="xml", headers=None):
        query = urllib.parse.urlencode(
            {
                "subject_id": subject,
                "tz_name": "UTC",
                "source_format": "apple_health_export_" + fmt,
                "data_mode": "synthetic",
            }
        )
        return request(
            "POST",
            "/v1/imports?" + query,
            body,
            {"Content-Type": "application/octet-stream", **(headers or {})},
        )

    def finished(kind, identifier):
        for _ in range(100):
            status, document, raw = request("GET", f"/v1/{kind}/{identifier}")
            if status == 200 and document["state"] in {"succeeded", "failed", "completed"}:
                return document, raw
            time.sleep(0.05)
        raise RuntimeError("job did not reach terminal state")

    status, health, _ = request("GET", "/healthz")
    require(
        status == 200 and health["git_sha"] == git_sha and health["artifacts"] == [],
        "fresh_exact_checkout_no_models",
    )
    status, _, raw = request("GET", "/v1/subjects/synthetic-fault/coverage")
    require(status == 500 and SENTINEL.encode() not in raw, "unexpected_fault_safe_response")
    status, _, raw = request(
        "POST",
        "/v1/scenarios",
        {
            "schema_version": "0.1",
            "subject_id": "synthetic-fault",
            "tz_name": "UTC",
            "schedules": [
                {
                    "schedule_id": SENTINEL,
                    "bedtime_local": "2026-10-10T22:00:00",
                    "wake_time_local": "2026-10-10T21:00:00",
                }
            ],
            "assumptions": {
                "prior_sleep_hours": 7.0,
                "caffeine": "none",
                "light_exposure": "not_modeled",
            },
        },
    )
    require(status == 422 and SENTINEL.encode() not in raw, "validation_error_safe_response")
    keep_status, keep, _ = upload("synthetic-keep", XML)
    require(keep_status == 202, "second_subject_upload")
    require(
        finished("imports", keep["import_id"])[0]["state"] == "succeeded", "second_subject_import"
    )
    status, uploaded, raw = upload(
        "synthetic-delete", archive("apple_health_export/export.xml", XML), "zip"
    )
    require(status == 202 and SENTINEL.encode() not in raw, "zip_upload_accepted_no_raw_echo")
    iid = uploaded["import_id"]
    imported, raw = finished("imports", iid)
    require(
        imported["state"] == "succeeded"
        and imported["counts"]["records_accepted"] == 1
        and SENTINEL.encode() not in raw,
        "import_succeeded_one_generated_record",
    )
    status, reused, _ = upload(
        "synthetic-delete", archive("apple_health_export/export.xml", XML), "zip"
    )
    require(status == 200 and reused["import_id"] == iid, "same_subject_idempotency")
    require(
        request("GET", "/v1/subjects/synthetic-delete/coverage")[1]["data_mode"] == "synthetic",
        "coverage_generated_data",
    )
    require(
        request(
            "POST",
            "/v1/subjects/synthetic-delete/observations",
            {"schema_version": "0.1", "entries": [ONSET]},
        )[0]
        == 201,
        "personal_checkin_stored",
    )
    resolution = {
        "kind": "symptom_resolution",
        "entry_id": "synthetic-resolution",
        "entered_at_utc": "2026-09-05T08:00:00Z",
        "onset_entry_id": SENTINEL,
        "resolved_earliest_utc": "2026-09-04T00:00:00Z",
        "resolved_latest_utc": "2026-09-05T00:00:00Z",
    }
    require(
        request(
            "POST",
            "/v1/subjects/synthetic-keep/observations",
            {"schema_version": "0.1", "entries": [resolution]},
        )[0]
        == 422,
        "cross_subject_reference_rejected",
    )
    require(
        request("GET", "/v1/subjects/synthetic-keep/observations")[1]["entries"] == [],
        "other_subject_history_empty",
    )
    status, report, _ = request(
        "POST",
        "/v1/reports",
        {
            "schema_version": "0.1",
            "subject_id": "synthetic-delete",
            "as_of": "2026-09-02T12:00:00Z",
            "task": "anomaly",
        },
    )
    require(
        status == 202 and finished("reports", report["report_id"])[0]["state"] == "completed",
        "personal_report_terminal",
    )
    require(
        request("DELETE", "/v1/subjects/synthetic-delete?confirm=synthetic-keep")[0] == 422,
        "wrong_subject_confirmation_rejected",
    )
    require(
        request("DELETE", "/v1/subjects/synthetic-delete?confirm=synthetic-delete")[0] == 204,
        "delete_confirmed",
    )
    require(
        request("GET", f"/v1/imports/{iid}")[0] == 404
        and request("GET", f"/v1/reports/{report['report_id']}")[0] == 404
        and request("GET", "/v1/subjects/synthetic-delete/coverage")[0] == 404
        and request("GET", "/v1/subjects/synthetic-delete/observations")[0] == 404,
        "all_deleted_subject_api_records_absent",
    )
    state = root / "workspaces" / "privacy-http" / "state"
    require(not (state / "imports" / iid).exists(), "raw_and_derived_import_directory_absent")
    require(
        request("GET", "/v1/subjects/synthetic-keep/coverage")[0] == 200, "other_subject_preserved"
    )
    for bad_name, bad_body, fmt, code in [
        ("traversal", archive("../export.xml", XML), "zip", "ARCHIVE_UNSAFE"),
        ("symlink", archive("export.xml", b"outside", symlink=True), "zip", "ARCHIVE_UNSAFE"),
        (
            "entity",
            b'<!DOCTYPE HealthData [<!ENTITY x SYSTEM "file:///private">]><HealthData>&x;</HealthData>',
            "xml",
            "MALFORMED_XML",
        ),
        (
            "depth",
            b"<HealthData>" + b"<X>" * 40 + b"</X>" * 40 + b"</HealthData>",
            "xml",
            "MALFORMED_XML",
        ),
        ("token", b'<HealthData X="' + b"x" * 70000 + b'"></HealthData>', "xml", "MALFORMED_XML"),
        ("corrupt", b"not-a-zip-" + SENTINEL.encode(), "zip", "ARCHIVE_UNSAFE"),
    ]:
        status, job, raw = upload("synthetic-" + bad_name, bad_body, fmt)
        require(status == 202, bad_name + "_queued")
        result, raw = finished("imports", job["import_id"])
        require(
            result["state"] == "failed"
            and result["failure"]["error_code"] == code
            and SENTINEL.encode() not in raw,
            bad_name + "_safe_rejection",
        )
        require(
            request("DELETE", f"/v1/subjects/synthetic-{bad_name}?confirm=synthetic-{bad_name}")[0]
            == 204,
            bad_name + "_failed_import_deleted",
        )
    require(
        upload("synthetic-large", b"x", headers={"Content-Length": str(256 * 1024 * 1024 + 1)})[0]
        == 413,
        "declared_oversize_upload_rejected",
    )
    require(upload("synthetic-empty", b"")[0] == 422, "empty_upload_rejected")
    require(
        request("GET", "/healthz", headers={"Host": "attacker.example"})[0] == 400,
        "foreign_host_rejected",
    )
    require(
        request("POST", "/v1/reports", b"{}", {"Content-Type": "text/plain"})[0] == 415,
        "simple_form_write_rejected",
    )
    require(
        request("DELETE", "/v1/subjects/synthetic-keep?confirm=synthetic-keep")[0] == 204,
        "last_generated_subject_deleted",
    )
    with sqlite3.connect(state / "metadata.sqlite3") as db:
        require(
            all(
                db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
                for table in ("imports", "report_jobs", "self_reports")
            ),
            "all_personal_metadata_empty",
        )
    require(
        all(SENTINEL.encode() not in p.read_bytes() for p in state.glob("metadata.sqlite3*")),
        "deleted_personal_bytes_absent_from_database_and_wal",
    )
    require(
        not list((state / "uploads").iterdir()) and not list((state / "imports").iterdir()),
        "no_raw_staging_or_derived_artifacts_left",
    )
    return {
        "ok": True,
        "git_sha": git_sha,
        "checks": checked,
        "checks_passed": len(checked),
        "data_mode": "synthetic",
        "model_refs": [],
        "real_source_data_deleted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8719)
    args = parser.parse_args()
    # Refuse to contact or stop someone else's listener.
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", args.port))
    repo = Path(__file__).resolve().parents[2]
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    with tempfile.TemporaryDirectory(prefix="hachi-privacy-19-") as directory:
        root = Path(directory)
        env = {k: v for k, v in os.environ.items() if not k.startswith("HACHI_")}
        env.update(
            {
                "HACHI_OWNER": "privacy-http",
                "HACHI_WORKSPACES": str(root / "workspaces"),
                "HACHI_DB_PATH": str(root / "workspaces/privacy-http/state/metadata.sqlite3"),
                "HACHI_ARTIFACT_ROOT": str(root / "artifacts"),
                "HACHI_GIT_SHA": sha,
                "HACHI_RUN_DIR": str(root / "run"),
                "XDG_CACHE_HOME": str(root / "cache"),
            }
        )
        log_path = root / "service.log"
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    FAULT_PROBE,
                    "serve",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.port),
                ],
                cwd=repo,
                env=env,
                stdout=log,
                stderr=log,
                umask=0o077,
            )
            try:
                for _ in range(100):
                    try:
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{args.port}/healthz", timeout=0.2
                        ):
                            break
                    except (OSError, urllib.error.URLError):
                        if process.poll() is not None:
                            raise RuntimeError("own service failed to start") from None
                        time.sleep(0.05)
                result = verify(f"http://127.0.0.1:{args.port}", root, sha)
            except Exception as exc:
                # Exception class only: even HTTP exceptions can contain private URLs.
                result = {"ok": False, "git_sha": sha, "error_type": type(exc).__name__}
                if isinstance(exc, VerificationFailed):
                    result["failed_check"] = str(exc)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        result["service_log_sha256"] = hashlib.sha256(log_path.read_bytes()).hexdigest()
        result["safe_logs"] = (
            SENTINEL.encode() not in log_path.read_bytes()
            and b"synthetic-delete" not in log_path.read_bytes()
        )
        result["ok"] = result["ok"] and result["safe_logs"]
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
