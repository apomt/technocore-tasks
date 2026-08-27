from technocore_tasks.board import Board
from technocore_tasks.events import build_event

from conftest import add_create, add_event


def test_create_multiple_claims_valid_assign_complete_close(store, dids):
    task_id = add_create(store, dids[0], description="Test edges", reward="100 FLOP?")
    add_event(store, 2, dids[1], 101, "CLAIM", {"task": task_id})
    add_event(store, 3, dids[2], 102, "CLAIM", {"task": task_id, "note": "I can help"})
    add_event(store, 4, dids[0], 103, "ASSIGN", {"task": task_id, "assignee": dids[2]})
    add_event(store, 5, dids[2], 104, "COMPLETE", {"task": task_id, "result": "https://example.invalid/result"})
    add_event(store, 6, dids[0], 105, "CLOSE", {"task": task_id})

    task = Board(store).task(task_id)
    assert task.state == "closed"
    assert [c["signer_did"] for c in task.claims] == dids[1:3]
    assert task.assignee_did == dids[2]
    assert task.completion["fields"]["result"] == "https://example.invalid/result"
    assert task.advertised == {"reward": "100 FLOP?"}
    assert task.to_dict()["advertised_unverified"]["reward"] == "100 FLOP?"
    assert task.events[0]["original_message"].startswith("TC-TASK/1 CREATE")
    assert task.events[0]["signer_did"] == dids[0]
    assert task.events[0]["room"] == "technocore-tasks"
    assert task.events[0]["seq"] == 1
    assert task.events[0]["nonce"] == 100
    assert task.events[0]["timestamp"].endswith("Z")


def test_invalid_non_creator_assign_is_preserved(store, dids):
    task_id = add_create(store, dids[0])
    add_event(store, 2, dids[1], 101, "CLAIM", {"task": task_id})
    add_event(store, 3, dids[3], 102, "ASSIGN", {"task": task_id, "assignee": dids[1]})
    task = Board(store).task(task_id)
    assert task.state == "claimed"
    assert task.assignment is None
    assert task.conflicted
    assert "not the original creator" in task.events[-1]["reason"]


def test_conflicting_creator_assign_latest_valid_wins(store, dids):
    task_id = add_create(store, dids[0])
    add_event(store, 2, dids[1], 101, "CLAIM", {"task": task_id})
    add_event(store, 3, dids[2], 102, "CLAIM", {"task": task_id})
    add_event(store, 4, dids[0], 103, "ASSIGN", {"task": task_id, "assignee": dids[1]})
    add_event(store, 5, dids[0], 104, "ASSIGN", {"task": task_id, "assignee": dids[2]})
    task = Board(store).task(task_id)
    assert task.assignee_did == dids[2]
    assert task.assignment["seq"] == 5
    assert any("latest valid event wins" in c["reason"] for c in task.conflicts)


def test_complete_must_be_latest_assignee(store, dids):
    task_id = add_create(store, dids[0])
    add_event(store, 2, dids[1], 101, "CLAIM", {"task": task_id})
    add_event(store, 3, dids[0], 102, "ASSIGN", {"task": task_id, "assignee": dids[1]})
    add_event(store, 4, dids[2], 103, "COMPLETE", {"task": task_id})
    assert Board(store).task(task_id).state == "assigned"
    add_event(store, 5, dids[1], 104, "COMPLETE", {"task": task_id})
    assert Board(store).task(task_id).state == "completed"


def test_cancel_only_creator_and_is_terminal(store, dids):
    task_id = add_create(store, dids[0])
    add_event(store, 2, dids[1], 101, "CANCEL", {"task": task_id})
    add_event(store, 3, dids[0], 102, "CANCEL", {"task": task_id, "reason": "stale"})
    add_event(store, 4, dids[2], 103, "CLAIM", {"task": task_id})
    task = Board(store).task(task_id)
    assert task.state == "cancelled"
    assert task.cancel_event["fields"]["reason"] == "stale"
    assert len(task.conflicts) == 2


def test_partial_history_later_events_do_not_create_authority(store, dids):
    task_id = "task-a83fd2c9"
    add_event(store, 200, dids[1], 500, "CLAIM", {"task": task_id})
    add_event(store, 201, dids[1], 501, "COMPLETE", {"task": task_id, "result": "x"})
    store.record_gap("technocore-tasks", 1, 199)
    task = Board(store).task(task_id)
    assert task.state == "partial"
    assert task.partial_history
    assert task.creator_did is None
    assert all(not event["valid_transition"] for event in task.events)


def test_malicious_reused_id_cannot_overwrite(store, dids):
    task_id = add_create(store, dids[0], title="Original")
    forged = build_event("CREATE", {"task": task_id, "title": "Overwrite"})
    store.insert_message("technocore-tasks", {"seq": 2, "ts": "2026-08-27T00:00:02Z", "from": dids[1], "nonce": 101, "text": forged})
    task = Board(store).task(task_id)
    assert task.creator_did == dids[0]
    assert task.title == "Original"
    assert "mismatch" in task.events[1]["reason"]


def test_unsigned_event_is_not_authoritative(store, dids):
    task_id = add_create(store, dids[0])
    add_event(store, 2, dids[1], 101, "CLAIM", {"task": task_id}, signed=False)
    task = Board(store).task(task_id)
    assert task.claims == []
    assert task.conflicted

