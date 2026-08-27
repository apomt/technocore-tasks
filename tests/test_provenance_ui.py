from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from technocore_tasks.config import Settings
from technocore_tasks.web import create_app

from test_kibble_protocol import insert


def client_for(store):
    return TestClient(create_app(Settings(database=Path(store.path), collector_enabled=False)))


def test_protocol_page_has_neutral_provenance_layers_and_external_links(store):
    with client_for(store) as client:
        page = client.get("/protocols")
    text = page.text
    assert page.status_code == 200
    for label in (
        "Kibble-hosted specification", "Observed signed tape",
        "Reconstructed state", "Inferred / unknown",
    ):
        assert label in text
    assert 'href="https://flop-kibble.onrender.com/llms.txt"' in text
    assert 'href="https://flop-kibble.onrender.com/"' in text
    assert "not independently proven to be official FLOP Labs or Technocore authority" in text
    assert "official FLOP Labs protocol" not in text
    assert "until $FLOP can pay" in text
    assert "payment, escrow" in text and "are not established here" in text
    assert "recomputed advisory IOU" in text
    assert "not a redeemable balance" in text


def test_protocol_page_describes_tc_as_disabled_experimental_convention(store):
    with client_for(store) as client:
        page = client.get("/protocols")
        catalog = client.get("/api/protocols").json()["protocols"]
    assert "experimental community convention" in page.text.lower()
    assert "disabled by default" in page.text
    assert "has no dedicated room" in page.text
    tc = next(item for item in catalog if item["protocol"] == "TC-TASK")
    assert tc["default_source_room"] is None
    assert "disabled by default" in tc["source_status"]


def test_default_collection_source_is_kibble_not_tc_room(monkeypatch, tmp_path):
    monkeypatch.delenv("TASKS_SOURCE_ROOMS", raising=False)
    monkeypatch.delenv("TASKS_ROOM", raising=False)
    monkeypatch.setenv("TASKS_DATABASE", str(tmp_path / "defaults.db"))
    settings = Settings.from_env()
    assert settings.source_rooms == ("kibble",)
    assert "technocore-tasks" not in settings.source_rooms


def test_homepage_summarizes_initial_unrecoverable_gap_neutrally(store, dids):
    insert(store, 100, dids[0], "JOB v1 | kabcdef0123 | explain | retained job | retained body")
    store.record_gap("kibble", 1, 99)
    with client_for(store) as client:
        page = client.get("/")
    assert "Collection history" in page.text
    assert "initial unrecoverable sequence gap" in page.text
    assert "1–99" in page.text
    assert "1 of 1 reconstructed jobs are marked partial" in page.text
    assert "not broken or malicious" in page.text
    assert "Future work whose first event is collected may have complete history" in page.text


def test_partial_detail_discloses_known_missing_job_without_inference(store, dids):
    insert(store, 100, dids[1], "RESULT v1 | kabcdef0123 | retained result")
    store.record_gap("kibble", 1, 99)
    with client_for(store) as client:
        page = client.get("/task/kabcdef0123")
        detail = client.get("/api/tasks/kabcdef0123").json()
    assert "Partial history observed" in page.text
    assert "not evidence that the job or signer is broken or malicious" in page.text
    assert "Known unobserved origin event" in page.text and "JOB" in page.text
    assert detail["missing_event_types"] == ["JOB"]
    assert detail["observed_event_types"] == ["RESULT"]


def test_partial_detail_says_event_types_unknown_when_origin_is_present(store, dids):
    insert(store, 100, dids[0], "JOB v1 | kabcdef0123 | explain | retained job | retained body")
    store.record_gap("kibble", 1, 99)
    with client_for(store) as client:
        page = client.get("/task/kabcdef0123")
    assert "The exact missing event types cannot be determined" in page.text
    assert "none are fabricated" in page.text
    assert "Observed event types" in page.text and "JOB" in page.text


def test_tc_partial_detail_names_create_as_missing(store, dids):
    from conftest import add_event
    add_event(store, 100, dids[1], 5100, "CLAIM", {"task": "task-a83fd2c9"})
    store.record_gap("technocore-tasks", 1, 99)
    with client_for(store) as client:
        detail = client.get("/api/tasks/task-a83fd2c9").json()
    assert detail["missing_event_types"] == ["CREATE"]


def test_ecosystem_positions_tasks_as_persistent_read_only_explorer(store):
    with client_for(store) as client:
        page = client.get("/ecosystem")
    assert "Persistent evidence-aware task explorer and read-only API" in page.text
