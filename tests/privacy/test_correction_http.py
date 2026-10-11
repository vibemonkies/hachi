"""Independent correction/deletion privacy checks over an actual loopback HTTP socket.

Only generated subjects and this fixture's disposable database are mutated. Barriers
pause storage boundaries to make otherwise timing-dependent races reproducible.
"""

import shutil
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest

pytest.importorskip("fastapi")
import httpx
import uvicorn

from hachi.api.app import create_app
from hachi.api.catalog import Catalog
from hachi.api.settings import Settings
from hachi.storage import Workspace

SUBJECT = "synthetic-correction-privacy"
PATH = f"/v1/subjects/{SUBJECT}/observations"
ONSET = {
    "kind": "symptom_onset",
    "entry_id": "synthetic-onset",
    "entered_at_utc": "2026-09-02T08:00:00Z",
    "onset_earliest_utc": "2026-09-01T19:47:53Z",
    "onset_latest_utc": "2026-09-02T06:00:00Z",
    "symptoms": ["cough"],
    "severity": 1,
}
CORRECTION = ONSET | {
    "entry_id": "synthetic-correction",
    "supersedes": ONSET["entry_id"],
    "entered_at_utc": "2026-09-03T09:00:00Z",
    "severity": 2,
}
RESOLUTION = {
    "kind": "symptom_resolution",
    "entry_id": "synthetic-resolution",
    "entered_at_utc": "2026-09-06T08:00:00Z",
    "onset_entry_id": ONSET["entry_id"],
    "resolved_earliest_utc": "2026-09-05T00:00:00Z",
    "resolved_latest_utc": "2026-09-06T00:00:00Z",
}


@pytest.fixture
def live_api(tmp_path):
    workspace = Workspace.for_owner("privacy-http", tmp_path / "workspaces")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    settings = Settings(
        owner="privacy-http", workspace=workspace, database=workspace.default_database, git_sha=sha
    )
    app = create_app(settings, catalog=lambda _: Catalog())
    # Bind ourselves first: never send a test request to an existing worker's service.
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 8719))
    server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        with httpx.Client(base_url="http://127.0.0.1:8719", timeout=10) as client:
            deadline = time.monotonic() + 10
            while not server.started:
                assert worker.is_alive() and time.monotonic() < deadline
                time.sleep(0.01)
            health = client.get("/healthz").json()
            assert health["git_sha"] == sha and health["artifacts"] == []
            yield client, app.state.service, settings
    finally:
        server.should_exit = True
        worker.join(10)
        listener.close()
        assert not worker.is_alive()
        # This fixture owns the entire generated root, including staged test artifacts.
        shutil.rmtree(tmp_path)


def post(client, *entries, path=PATH):
    return client.post(path, json={"schema_version": "0.1", "entries": list(entries)})


def erase(client, entry_id):
    return client.delete(f"{PATH}/{entry_id}", params={"confirm": entry_id})


def test_tombstones_only_subject_can_be_fully_erased(live_api):
    client, service, settings = live_api
    assert post(client, ONSET, CORRECTION).status_code == 201
    assert erase(client, CORRECTION["entry_id"]).status_code == 204
    assert service.metadata.self_report_tombstones(SUBJECT) == {
        ONSET["entry_id"],
        CORRECTION["entry_id"],
    }
    assert post(client, ONSET).status_code == 409
    assert client.delete(f"/v1/subjects/{SUBJECT}", params={"confirm": SUBJECT}).status_code == 204
    assert not service.metadata.self_report_tombstones(SUBJECT)
    for path in settings.database.parent.glob("metadata.sqlite3*"):
        assert SUBJECT.encode() not in path.read_bytes()
    assert post(client, ONSET).status_code == 201


def test_correction_cannot_resurrect_a_concurrently_erased_chain(live_api, monkeypatch):
    client, service, _ = live_api
    assert post(client, ONSET).status_code == 201
    entered, snapshot_read = threading.Event(), threading.Event()
    original_delete = service.metadata.delete_self_report_chain
    original_write = service._writing

    def paused_delete(*args):
        entered.set()
        assert snapshot_read.wait(5)
        return original_delete(*args)

    @contextmanager
    def observed_write(subject):
        if entered.is_set():
            snapshot_read.set()
        with original_write(subject):
            yield

    monkeypatch.setattr(service.metadata, "delete_self_report_chain", paused_delete)
    monkeypatch.setattr(service, "_writing", observed_write)
    with ThreadPoolExecutor(max_workers=1) as executor:
        deletion = executor.submit(erase, client, ONSET["entry_id"])
        assert entered.wait(5)
        response = post(client, CORRECTION)
        assert deletion.result(timeout=5).status_code == 204
    assert response.status_code in (409, 422)
    assert not service.metadata.self_reports(SUBJECT)


def test_onset_guard_uses_history_at_mutation_time(live_api, monkeypatch):
    client, service, _ = live_api
    assert post(client, ONSET).status_code == 201
    snapshot_read, appended = threading.Event(), threading.Event()
    original_read = service.metadata.self_reports
    original_write = service._writing

    def paused_read(*args):
        result = original_read(*args)
        # DELETE is a sync route in the worker pool; POST runs on the ASGI loop.
        if threading.current_thread().name == "AnyIO worker thread":
            snapshot_read.set()
            assert appended.wait(5)
        return result

    @contextmanager
    def observed_write(subject):
        if snapshot_read.is_set():
            appended.set()
        with original_write(subject):
            yield

    monkeypatch.setattr(service.metadata, "self_reports", paused_read)
    monkeypatch.setattr(service, "_writing", observed_write)
    with ThreadPoolExecutor(max_workers=1) as executor:
        deletion = executor.submit(erase, client, ONSET["entry_id"])
        assert snapshot_read.wait(5)
        resolution = post(client, RESOLUTION)
        response = deletion.result(timeout=5)
    assert (response.status_code, resolution.status_code) in ((409, 201), (204, 422))
    rows = original_read(SUBJECT)
    assert not rows or {r.entry_id for r in rows} == {ONSET["entry_id"], RESOLUTION["entry_id"]}


def history(client, **params):
    response = client.get(PATH, params=params)
    assert response.status_code == 200
    return response.json()["entries"]


def report(client, task="illness_onset", subject=SUBJECT, **fields):
    if task == "illness_onset":
        fields = {"horizon_hours": 24, **fields}
    response = client.post(
        "/v1/reports",
        json={
            "schema_version": "0.1",
            "subject_id": subject,
            "task": task,
            "as_of": "2026-09-07T00:00:00Z",
            **fields,
        },
    )
    assert response.status_code in (200, 202)
    return response.json()["report_id"]


def test_cutoff_histories_and_dependent_report_isolation(live_api):
    client, service, settings = live_api
    assert post(client, ONSET).status_code == 201
    early = report(client, as_of="2026-09-02T10:00:00Z")
    later = report(client)
    assert service.runner.wait_idle()
    assert post(client, CORRECTION).status_code == 201
    assert history(client, as_of="2026-09-02T07:59:59Z") == []
    assert [e["entry_id"] for e in history(client, as_of=ONSET["entered_at_utc"])] == [
        ONSET["entry_id"]
    ]
    assert [e["entry_id"] for e in history(client, as_of=CORRECTION["entered_at_utc"])] == [
        CORRECTION["entry_id"]
    ]
    assert [e["entry_id"] for e in history(client, versions="all")] == [
        ONSET["entry_id"],
        CORRECTION["entry_id"],
    ]
    assert report(client, as_of="2026-09-02T10:00:00Z") == early
    revised = report(client)
    assert revised != later
    assert (
        post(
            client,
            ONSET | {"onset_earliest_utc": "2026-09-01T20:00:00Z"},
            path="/v1/subjects/synthetic-isolated/observations",
        ).status_code
        == 201
    )
    other = report(client, subject="synthetic-isolated")
    anomaly = report(client, "anomaly")
    assert service.runner.wait_idle()
    assert erase(client, CORRECTION["entry_id"]).status_code == 204
    assert history(client, versions="all") == []
    for identifier in (early, later, revised):
        assert client.get(f"/v1/reports/{identifier}").status_code == 404
    for identifier in (other, anomaly):
        assert client.get(f"/v1/reports/{identifier}").status_code == 200
    assert client.get("/v1/subjects/synthetic-isolated/observations").json()["entries"]
    for path in settings.database.parent.glob("metadata.sqlite3*"):
        assert b"2026-09-01T19:47:53Z" not in path.read_bytes()
    assert post(client, CORRECTION).status_code == 409


def test_retained_superseded_resolution_protects_both_onsets(live_api):
    client, _, _ = live_api
    other = ONSET | {"entry_id": "synthetic-other-onset"}
    moved = RESOLUTION | {
        "entry_id": "synthetic-moved-resolution",
        "supersedes": RESOLUTION["entry_id"],
        "entered_at_utc": "2026-09-07T08:00:00Z",
        "onset_entry_id": other["entry_id"],
    }
    assert post(client, ONSET, other, RESOLUTION, moved).status_code == 201
    assert erase(client, ONSET["entry_id"]).status_code == 409
    assert erase(client, other["entry_id"]).status_code == 409
    assert erase(client, moved["entry_id"]).status_code == 204
    assert erase(client, ONSET["entry_id"]).status_code == 204
    assert [e["entry_id"] for e in history(client, versions="all")] == [other["entry_id"]]


def test_deleted_chain_content_absent_from_database_and_wal(live_api):
    client, service, settings = live_api
    assert post(client, ONSET, CORRECTION).status_code == 201
    assert erase(client, ONSET["entry_id"]).status_code == 204
    assert not service.metadata.self_reports(SUBJECT)
    files = list(settings.database.parent.glob("metadata.sqlite3*"))
    assert files and all(b"2026-09-01T19:47:53Z" not in path.read_bytes() for path in files)
    wal = settings.database.with_name(settings.database.name + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0
    assert post(client, ONSET).status_code == 409
    assert post(client, CORRECTION).status_code == 409


@pytest.mark.parametrize("mutation", ["identical_entry", "cached_report"])
def test_cached_writes_refused_during_whole_subject_deletion(live_api, monkeypatch, mutation):
    client, service, _ = live_api
    assert post(client, ONSET).status_code == 201
    report(client)
    assert service.runner.wait_idle()
    entered, release = threading.Event(), threading.Event()
    original_delete = service.metadata.delete_subject

    def paused_delete(subject):
        entered.set()
        assert release.wait(5)
        return original_delete(subject)

    monkeypatch.setattr(service.metadata, "delete_subject", paused_delete)
    with ThreadPoolExecutor(max_workers=1) as executor:
        deletion = executor.submit(
            client.delete, f"/v1/subjects/{SUBJECT}", params={"confirm": SUBJECT}
        )
        try:
            assert entered.wait(5)
            if mutation == "identical_entry":
                response = post(client, ONSET)
            else:
                response = client.post(
                    "/v1/reports",
                    json={
                        "schema_version": "0.1",
                        "subject_id": SUBJECT,
                        "task": "illness_onset",
                        "as_of": "2026-09-07T00:00:00Z",
                        "horizon_hours": 24,
                    },
                )
            assert response.status_code == 409
        finally:
            release.set()
        assert deletion.result(timeout=5).status_code == 204
    assert not service.metadata.subject_known(SUBJECT)


def test_correction_rejections_omit_submitted_values(live_api, caplog):
    client, _, _ = live_api
    sentinel = "SYNTHETIC-PRIVATE-CORRECTION-SENTINEL"
    assert post(client, ONSET).status_code == 201
    for entry in (
        CORRECTION | {"supersedes": sentinel},
        RESOLUTION | {"onset_entry_id": sentinel},
        CORRECTION | {sentinel: sentinel},
        CORRECTION | {"severity": sentinel},
    ):
        response = post(client, entry)
        assert response.status_code == 422 and sentinel not in response.text
    response = client.delete(f"{PATH}/{ONSET['entry_id']}", params={"confirm": sentinel})
    assert response.status_code == 422 and sentinel not in response.text
    response = client.get(PATH, params={"versions": sentinel})
    assert response.status_code == 422 and sentinel not in response.text
    assert sentinel not in caplog.text
    assert [e["entry_id"] for e in history(client)] == [ONSET["entry_id"]]


def test_report_key_uses_history_at_publication_time(live_api, monkeypatch):
    client, service, _ = live_api
    assert post(client, ONSET).status_code == 201
    entered, report_waiting = threading.Event(), threading.Event()
    original_delete = service.metadata.delete_self_report_chain
    original_write = service._writing

    def paused_delete(*args):
        entered.set()
        assert report_waiting.wait(5)
        return original_delete(*args)

    @contextmanager
    def observed_write(subject):
        if entered.is_set():
            report_waiting.set()
        with original_write(subject):
            yield

    monkeypatch.setattr(service.metadata, "delete_self_report_chain", paused_delete)
    monkeypatch.setattr(service, "_writing", observed_write)
    with ThreadPoolExecutor(max_workers=1) as executor:
        deletion = executor.submit(erase, client, ONSET["entry_id"])
        assert entered.wait(5)
        first = report(client)
        assert deletion.result(timeout=5).status_code == 204
    assert service.runner.wait_idle()
    # A completed request with no intervening history change must reuse the job.
    assert report(client) == first
