from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

from technocore_tasks.board import Board
from technocore_tasks.config import Settings
from technocore_tasks.web import create_app
from technocore_tasks.projection_store import IOGate

from conftest import add_create, add_event


def test_projection_rebuild_is_checkpointed_and_resumable(store, dids):
    task_id = add_create(store, dids[0])
    for seq in range(2, 8):
        add_event(store, seq, dids[1], 100 + seq, "CLAIM", {"task": task_id})
    with store.connect() as db:
        for table in ("task_projections", "task_participants", "task_projection_values",
                      "task_conflicts", "event_derivations"):
            db.execute(f"DELETE FROM {table}")
        store._set(db, "parse_status", "complete")
        store._set(db, "projection_status", "pending")
        store._set(db, "projection_cursor", "0")
        store._set(db, "projection_reset", "1")

    first = store.maintenance_step(batch_size=2)
    assert first["projection"]["cursor"] == 2
    reopened = type(store)(store.path)
    assert reopened.maintenance_status()["projection"]["cursor"] == 2
    assert reopened.run_maintenance(batch_size=2)["ready"] is True
    assert Board(reopened).task(task_id).projected_event_count == 7


def test_task_evidence_and_lists_are_hard_bounded(store, dids):
    task_id = add_create(store, dids[0])
    for seq in range(2, 502):
        add_event(store, seq, dids[1], 1000 + seq, "CLAIM", {"task": task_id})
    task = Board(store).task(task_id, page_size=10_000)
    assert task.projected_event_count == 501
    assert len(task.events) == 200
    assert task.event_pagination == {"page": 1, "page_size": 200, "total": 501, "pages": 3,
                                     "has_previous": False, "has_next": True}


def test_api_exposes_pagination_and_maintenance_diagnostics(store, dids):
    add_create(store, dids[0])
    settings = Settings(database=store.path, collector_enabled=False)
    with TestClient(create_app(settings)) as client:
        listing = client.get("/api/tasks?page_size=1").json()
        health = client.get("/health").json()
    assert listing["pagination"]["page_size"] == 1
    assert listing["pagination"]["total"] == 1
    assert health["database"]["available"] is True
    assert health["maintenance"]["ready"] is True
    assert health["maintenance"]["projection"]["cursor"] == health["maintenance"]["projection"]["maximum"]
    assert health["collectors"][0]["gap_count"] == 0
    assert health["signing"] is False


def test_io_gate_prioritizes_a_queued_read_over_background_write():
    gate, order = IOGate(), []
    entered, release = threading.Event(), threading.Event()

    def first_writer():
        with gate.write():
            entered.set(); release.wait(1)
    def reader():
        with gate.read(): order.append("read")
    def second_writer():
        with gate.write(): order.append("write")

    threads = [threading.Thread(target=first_writer), threading.Thread(target=reader),
               threading.Thread(target=second_writer)]
    threads[0].start(); assert entered.wait(1)
    threads[1].start()
    deadline = time.time() + 1
    while gate.waiting_readers == 0 and time.time() < deadline: time.sleep(0.001)
    threads[2].start(); release.set()
    for thread in threads: thread.join(1)
    assert order == ["read", "write"]
