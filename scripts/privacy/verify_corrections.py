#!/usr/bin/env python3
"""Verify new correction privacy paths in the production CLI, without models or real data.

Reuses the isolated process/log harness, not the old upload walkthrough. For deterministic
concurrency barriers, run tests/privacy/test_correction_http.py against the same checkout.
"""

import json
import sqlite3
import time
import urllib.error
import urllib.request

from verify_http import ONSET, SENTINEL, VerificationFailed, main

FAULT_PROBE = """
import sys
from hachi.api.service import Service
from hachi.api.__main__ import main
original = Service.self_report_history
def history(self, subject_id, params):
    if subject_id == 'synthetic-fault':
        raise RuntimeError('SYNTHETIC-PRIVATE-SENTINEL-19')
    return original(self, subject_id, params)
Service.self_report_history = history
raise SystemExit(main(sys.argv[1:]))
"""
SUBJECT = "synthetic-delete"
PATH = f"/v1/subjects/{SUBJECT}/observations"
CORRECTION = ONSET | {
    "entry_id": "synthetic-correction",
    "supersedes": ONSET["entry_id"],
    "entered_at_utc": "2026-09-03T09:00:00Z",
    "severity": 3,
    "onset_earliest_utc": "2026-09-01T19:47:53Z",
}


def verify(base, root, git_sha):
    checks = []

    def require(condition, label):
        if not condition:
            raise VerificationFailed(label)
        checks.append(label)

    def request(method, path, body=None):
        headers = {}
        if body is not None:
            body = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        try:
            response = urllib.request.urlopen(
                urllib.request.Request(base + path, data=body, method=method, headers=headers),
                timeout=10,
            )
        except urllib.error.HTTPError as error:
            response = error
        raw = response.read()
        return response.status, json.loads(raw) if raw else None, raw

    def post(*entries, path=PATH):
        return request("POST", path, {"schema_version": "0.1", "entries": list(entries)})

    def ids(query=""):
        status, doc, _ = request("GET", PATH + query)
        require(status == 200, "history_read_accepted")
        return [e["entry_id"] for e in doc["entries"]]

    def erase(entry):
        return request("DELETE", f"{PATH}/{entry}?confirm={entry}")[0]

    def report(subject, task="illness_onset", cutoff="2026-09-07T00:00:00Z"):
        body = {"schema_version": "0.1", "subject_id": subject, "task": task, "as_of": cutoff}
        if task == "illness_onset":
            body["horizon_hours"] = 24
        status, doc, _ = request("POST", "/v1/reports", body)
        require(status in (200, 202), "report_request_accepted")
        identifier = doc["report_id"]
        for _ in range(100):
            _, job, _ = request("GET", f"/v1/reports/{identifier}")
            if job["state"] == "completed":
                return identifier
            time.sleep(0.02)
        raise VerificationFailed("report_completion")

    status, health, _ = request("GET", "/healthz")
    require(
        status == 200 and health["git_sha"] == git_sha and health["artifacts"] == [],
        "exact_cli_checkout_empty_model_pins",
    )
    status, _, raw = request("GET", "/v1/subjects/synthetic-fault/observations")
    require(status == 500 and SENTINEL.encode() not in raw, "history_fault_safe_response")
    require(post(ONSET)[0] == 201, "onset_recorded")
    early = report(SUBJECT, cutoff="2026-09-02T10:00:00Z")
    old = report(SUBJECT)
    require(post(CORRECTION)[0] == 201, "correction_appended")
    require(ids() == [CORRECTION["entry_id"]], "current_history_latest_version")
    require(ids("?as_of=2026-09-02T08:00:00Z") == [ONSET["entry_id"]], "as_of_inclusive_original")
    require(ids("?as_of=2026-09-02T07:59:59Z") == [], "as_of_before_recording_empty")
    require(
        ids("?versions=all") == [ONSET["entry_id"], CORRECTION["entry_id"]],
        "all_history_append_only",
    )
    require(report(SUBJECT, cutoff="2026-09-02T10:00:00Z") == early, "earlier_report_key_unchanged")
    revised = report(SUBJECT)
    require(revised != old, "current_report_key_changed")
    require(post(CORRECTION)[0] == 200, "identical_correction_noop")
    unknown = CORRECTION | {
        "entry_id": "synthetic-invalid",
        "supersedes": "synthetic-unknown-" + SENTINEL,
    }
    status, _, raw = post(unknown)
    require(status == 422 and SENTINEL.encode() not in raw, "correction_error_no_submitted_value")
    keep_path = "/v1/subjects/synthetic-keep/observations"
    require(post(ONSET, path=keep_path)[0] == 201, "isolated_second_subject")
    keep = report("synthetic-keep")
    anomaly = report(SUBJECT, task="anomaly")
    require(erase(CORRECTION["entry_id"]) == 204, "erase_entire_chain_via_corrected_id")
    require(ids("?versions=all") == [], "erased_versions_not_returned")
    require(
        all(request("GET", f"/v1/reports/{r}")[0] == 404 for r in (early, old, revised)),
        "dependent_reports_invalidated",
    )
    require(
        all(request("GET", f"/v1/reports/{r}")[0] == 200 for r in (keep, anomaly)),
        "other_subject_and_independent_report_preserved",
    )
    require(post(ONSET)[0] == post(CORRECTION)[0] == 409, "tombstoned_ids_refused")
    state = root / "workspaces/privacy-http/state"
    require(
        all(b"2026-09-01T19:47:53Z" not in p.read_bytes() for p in state.glob("metadata.sqlite3*")),
        "deleted_chain_content_absent_database_wal",
    )
    require(
        request("DELETE", f"/v1/subjects/{SUBJECT}?confirm={SUBJECT}")[0] == 204,
        "whole_subject_erases_tombstones_and_reports",
    )
    require(post(ONSET)[0] == 201, "new_subject_after_whole_erasure_can_reuse_id")
    require(erase(ONSET["entry_id"]) == 204, "last_chain_erased")
    require(
        request("DELETE", f"/v1/subjects/{SUBJECT}?confirm={SUBJECT}")[0] == 204,
        "tombstone_only_subject_erasable",
    )
    require(request("GET", keep_path)[0] == 200, "other_subject_survives_whole_erasure")
    require(
        request("DELETE", "/v1/subjects/synthetic-keep?confirm=synthetic-keep")[0] == 204,
        "self_created_second_subject_cleanup",
    )
    with sqlite3.connect(state / "metadata.sqlite3") as db:
        require(
            all(
                db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0
                for t in ("imports", "report_jobs", "self_reports", "self_report_tombstones")
            ),
            "all_personal_tables_empty_including_tombstones",
        )
    return {
        "ok": True,
        "git_sha": git_sha,
        "checks": checks,
        "checks_passed": len(checks),
        "data_mode": "synthetic",
        "model_refs": [],
        "real_source_data_deleted": False,
    }


if __name__ == "__main__":
    raise SystemExit(main(verifier=verify, fault_probe=FAULT_PROBE))
