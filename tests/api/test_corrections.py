"""#18: append-only corrections and real per-entry deletion of self-reports."""

from hachi.contracts.api import SelfReportHistory
from hachi.storage import Metadata

from .conftest import wait

SUBJECT = "synthetic-checkins"
PATH = f"/v1/subjects/{SUBJECT}/observations"
ONSET = {
    "kind": "symptom_onset",
    "entry_id": "onset-1",
    "entered_at_utc": "2026-09-02T08:00:00Z",
    "onset_earliest_utc": "2026-09-01T20:00:00Z",
    "onset_latest_utc": "2026-09-02T06:00:00Z",
    "symptoms": ["cough"],
    "severity": 1,
}
CORRECTION = ONSET | {
    "entry_id": "onset-1b",
    "supersedes": "onset-1",
    "entered_at_utc": "2026-09-03T09:00:00Z",
    "symptoms": ["cough", "fatigue"],
    "severity": 2,
}
RESOLUTION = {
    "kind": "symptom_resolution",
    "entry_id": "resolved-1",
    "entered_at_utc": "2026-09-06T08:00:00Z",
    "onset_entry_id": "onset-1",
    "resolved_earliest_utc": "2026-09-05T00:00:00Z",
    "resolved_latest_utc": "2026-09-06T00:00:00Z",
}


def post(client, *entries):
    return client.post(PATH, json={"schema_version": "0.1", "entries": list(entries)})


def history(client, **params) -> SelfReportHistory:
    response = client.get(PATH, params=params)
    assert response.status_code == 200, response.text
    return SelfReportHistory.model_validate_json(response.content)


def test_a_correction_is_appended_and_earlier_as_of_still_sees_the_original(client):
    assert post(client, ONSET).status_code == 201
    assert post(client, CORRECTION).status_code == 201
    current = history(client)
    assert [(e.entry_id, e.supersedes, e.severity) for e in current.entries] == [
        ("onset-1b", "onset-1", 2)
    ]
    before = history(client, as_of="2026-09-03T00:00:00Z")
    assert [e.entry_id for e in before.entries] == ["onset-1"]
    every = history(client, versions="all")
    assert [e.entry_id for e in every.entries] == ["onset-1", "onset-1b"]
    assert post(client, CORRECTION).status_code == 200  # identical resubmission: no-op


def test_corrections_are_refused_when_they_would_rewrite_history(client):
    post(client, ONSET, CORRECTION)
    fork = CORRECTION | {"entry_id": "onset-1c"}  # corrects the original again
    response = post(client, fork)
    assert response.status_code == 409
    assert response.json()["field_issues"][0]["path"] == "body.entries.0.supersedes"
    early = CORRECTION | {
        "entry_id": "onset-1d",
        "supersedes": "onset-1b",
        "entered_at_utc": "2026-09-02T09:00:00Z",
    }
    assert post(client, early).status_code == 422
    other_kind = {
        "kind": "confounder",
        "entry_id": "confounder-1",
        "entered_at_utc": "2026-09-04T08:00:00Z",
        "supersedes": "onset-1b",
        "factor": "travel",
        "occurred_earliest_utc": "2026-09-01T00:00:00Z",
        "occurred_latest_utc": "2026-09-01T06:00:00Z",
    }
    assert post(client, other_kind).status_code == 422
    missing = CORRECTION | {"entry_id": "onset-1e", "supersedes": "never-recorded"}
    assert post(client, missing).status_code == 422
    itself = CORRECTION | {"entry_id": "onset-1f", "supersedes": "onset-1f"}
    assert post(client, itself).status_code == 422  # the contract refuses it
    assert post(client, ONSET | {"severity": 3}).status_code == 409  # content is immutable


def test_episodes_are_named_by_their_original_onset(client):
    post(client, ONSET, CORRECTION)
    bad = RESOLUTION | {"onset_entry_id": "onset-1b"}  # a correction id is not the episode
    response = post(client, bad)
    assert response.status_code == 422
    assert response.json()["field_issues"][0]["path"] == "body.entries.0.onset_entry_id"
    base = {"schema_version": "0.1", "subject_id": SUBJECT}
    recovery = base | {"as_of": "2026-09-04T12:00:00Z", "task": "recovery", "episode_id": "onset-1"}
    job = client.post("/v1/reports", json=recovery).json()
    wait(client)
    result = client.get(f"/v1/reports/{job['report_id']}").json()["result"]
    assert result["reason_code"] == "NO_VALIDATED_RECOVERY_ARTIFACT"  # ongoing episode
    assert post(client, RESOLUTION).status_code == 201
    later = recovery | {"as_of": "2026-09-07T00:00:00Z"}
    job = client.post("/v1/reports", json=later).json()
    wait(client)
    result = client.get(f"/v1/reports/{job['report_id']}").json()["result"]
    assert result["reason_code"] == "NO_ONGOING_EPISODE"  # resolved by then


def test_deleting_one_entry_erases_every_version(client, make_settings):
    # Entries hold no free text; an unusual instant stands in for personal content.
    sentinel = "2026-09-01T19:47:53Z"
    post(client, ONSET, CORRECTION | {"onset_earliest_utc": sentinel})
    base = {"schema_version": "0.1", "subject_id": SUBJECT, "as_of": "2026-09-04T12:00:00Z"}
    illness = client.post("/v1/reports", json=base | {"task": "illness_onset", "horizon_hours": 24})
    forecast = client.post(
        "/v1/reports", json=base | {"task": "anomaly"}
    )  # a task that never reads self-reports
    wait(client)

    unconfirmed = client.delete(f"{PATH}/onset-1")
    assert unconfirmed.status_code == 422
    done = client.delete(f"{PATH}/onset-1", params={"confirm": "onset-1"})
    assert done.status_code == 204
    assert history(client, versions="all").entries == []
    # Dependent reports are invalidated; others stay.
    assert client.get(f"/v1/reports/{illness.json()['report_id']}").status_code == 404
    assert client.get(f"/v1/reports/{forecast.json()['report_id']}").status_code == 200
    # Deleted ids are never reused, and nothing of the content survives on disk.
    assert post(client, ONSET).status_code == 409
    database = make_settings().database
    for path in database.parent.glob(database.name + "*"):
        assert sentinel.encode() not in path.read_bytes()
    assert client.delete(f"{PATH}/onset-1", params={"confirm": "onset-1"}).status_code == 404


def test_an_onset_with_a_recorded_resolution_is_kept(client):
    post(client, ONSET, RESOLUTION)
    blocked = client.delete(f"{PATH}/onset-1", params={"confirm": "onset-1"})
    assert blocked.status_code == 409 and "resolution first" in blocked.json()["message"]
    assert client.delete(f"{PATH}/resolved-1", params={"confirm": "resolved-1"}).status_code == 204
    assert client.delete(f"{PATH}/onset-1", params={"confirm": "onset-1"}).status_code == 204


def test_older_databases_migrate_with_their_entries_as_chain_roots(tmp_path):
    import sqlite3

    path = tmp_path / "metadata.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE self_reports (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, subject_id TEXT NOT NULL,
            entry_id TEXT NOT NULL, kind TEXT NOT NULL, entry_json TEXT NOT NULL,
            UNIQUE (subject_id, entry_id)
        );
        CREATE TABLE imports (seq INTEGER PRIMARY KEY);
        CREATE TABLE report_jobs (seq INTEGER PRIMARY KEY);
        INSERT INTO self_reports (subject_id, entry_id, kind, entry_json)
            VALUES ('s', 'old-1', 'symptom_onset', '{}');
        PRAGMA user_version=1;
        """
    )
    connection.close()
    metadata = Metadata(path)
    (row,) = metadata.self_reports("s")
    assert (row.root, row.supersedes) == ("old-1", None)
    assert metadata.self_report_tombstones("s") == set()
    metadata.close()


def test_a_superseded_resolution_still_protects_its_onset(client):
    other = ONSET | {"entry_id": "onset-2", "entered_at_utc": "2026-09-02T09:00:00Z"}
    moved = RESOLUTION | {
        "entry_id": "resolved-1b",
        "supersedes": "resolved-1",
        "entered_at_utc": "2026-09-06T09:00:00Z",
        "onset_entry_id": "onset-2",
    }
    assert post(client, ONSET, other, RESOLUTION, moved).status_code == 201
    # The current resolution names onset-2, but the retained original still names onset-1.
    assert client.delete(f"{PATH}/onset-1", params={"confirm": "onset-1"}).status_code == 409
    assert (
        client.delete(f"{PATH}/resolved-1b", params={"confirm": "resolved-1b"}).status_code == 204
    )
    assert client.delete(f"{PATH}/onset-1", params={"confirm": "onset-1"}).status_code == 204
    assert [e.entry_id for e in history(client, versions="all").entries] == ["onset-2"]


def test_a_subject_with_only_tombstones_can_still_be_deleted(client):
    post(client, ONSET)
    assert client.delete(f"{PATH}/onset-1", params={"confirm": "onset-1"}).status_code == 204
    gone = client.delete(f"/v1/subjects/{SUBJECT}", params={"confirm": SUBJECT})
    assert gone.status_code == 204
    service = client.app.state.service
    assert service.metadata.self_report_tombstones(SUBJECT) == set()
    assert not service.metadata.subject_known(SUBJECT)


def test_cached_answers_wait_out_a_subject_deletion(client):
    post(client, ONSET)
    report = {
        "schema_version": "0.1",
        "subject_id": SUBJECT,
        "as_of": "2026-09-04T12:00:00Z",
        "task": "illness_onset",
        "horizon_hours": 24,
    }
    first = client.post("/v1/reports", json=report)
    wait(client)
    service = client.app.state.service
    service._deleting.add(SUBJECT)
    try:
        assert post(client, ONSET).status_code == 409  # identical resubmission
        assert client.post("/v1/reports", json=report).status_code == 409  # cached job
    finally:
        service._deleting.discard(SUBJECT)
    again = client.post("/v1/reports", json=report)
    assert again.status_code == 200 and again.json()["report_id"] == first.json()["report_id"]


def test_self_report_mutations_read_history_under_the_deletion_guard(client, monkeypatch):
    import threading

    service = client.app.state.service
    seen = []
    real = service.metadata.self_reports

    def watched(subject_id):
        # Report jobs read on their worker thread by design; request paths must hold the guard.
        if not threading.current_thread().name.startswith("hachi-"):
            seen.append(service._subjects.locked())
        return real(subject_id)

    monkeypatch.setattr(service.metadata, "self_reports", watched)
    report = {
        "schema_version": "0.1",
        "subject_id": SUBJECT,
        "as_of": "2026-09-04T12:00:00Z",
        "task": "recovery",
        "episode_id": "onset-1",
    }
    post(client, ONSET)  # add
    post(client, CORRECTION)  # add a correction
    post(client, ONSET)  # identical resubmission
    client.post("/v1/reports", json=report)  # report key over self-reports
    wait(client)
    client.delete(f"{PATH}/onset-1b", params={"confirm": "onset-1b"})  # chain delete
    assert len(seen) >= 5 and all(seen)
