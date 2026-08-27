from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("TASKS_DATABASE", str(Path(tempfile.gettempdir()) / "technocore_tasks_pytest_import.db"))
os.environ.setdefault("TASKS_COLLECTOR_ENABLED", "0")

from technocore_tasks.events import build_event, canonical_task_id
from technocore_tasks.local_signing import LocalSigner
from technocore_tasks.storage import Store


@pytest.fixture
def dids():
    return [LocalSigner(bytes([number]) * 32).did for number in (1, 2, 3, 4)]


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "tasks.db")


def add_event(store, seq, did, nonce, kind, fields, room="technocore-tasks", signed=True):
    text = build_event(kind, fields)
    message = {"seq": seq, "ts": f"2026-08-27T00:00:{seq:02d}.000000Z", "from": did, "text": text}
    if signed:
        message["nonce"] = nonce
    store.insert_message(room, message)
    return message


def add_create(store, did, seq=1, nonce=100, title="Review Atlas", **extra):
    task_id = canonical_task_id(did, nonce, title)
    fields = {"task": task_id, "title": title, **extra}
    add_event(store, seq, did, nonce, "CREATE", fields)
    return task_id
