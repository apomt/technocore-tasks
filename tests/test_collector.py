from __future__ import annotations

import json
import asyncio
import time

import httpx
import pytest

from technocore_tasks.collector import Collector
from technocore_tasks.events import build_event, canonical_task_id
from technocore_tasks.storage import Store


def metadata_response(request):
    if request.url.path == "/.well-known/agent.json":
        return httpx.Response(200, json={"name": "technocore-chat", "version": "0.9.7", "limits": {"reads_per_minute_per_ip": 600}})
    if request.url.path == "/openapi.json":
        return httpx.Response(200, json={"info": {"version": "0.9.7"}, "paths": {"/r/{room}": {"get": {"parameters": [{"name": "limit", "schema": {"maximum": 200}}]}}}})
    return None


def message(seq, did, task_id):
    return {"seq": seq, "ts": f"2026-08-27T00:00:{seq % 60:02d}Z", "from": did, "nonce": 1000 + seq, "text": build_event("CLAIM", {"task": task_id})}


@pytest.mark.asyncio
async def test_cursor_pagination_more_than_200_and_restart_persistence(tmp_path, dids):
    task_id = "task-a83fd2c9"
    calls = []

    def handler(request):
        if response := metadata_response(request):
            return response
        assert request.url.path == "/r/technocore-tasks"
        assert request.url.params["limit"] == "200"
        cursor = int(request.url.params["since"])
        calls.append(cursor)
        end = min(cursor + 200, 425)
        messages = [message(seq, dids[1], task_id) for seq in range(cursor + 1, end + 1)]
        return httpx.Response(200, json={"room": "technocore-tasks", "count": len(messages), "first_seq": messages[0]["seq"] if messages else None, "last_seq": end, "messages": messages})

    db = tmp_path / "tasks.db"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://technocore.chat") as client:
        result = await Collector(Store(db), "https://technocore.chat", "technocore-tasks", client=client).collect_once()
        assert result["inserted"] == 425
        assert result["cursor"] == 425
        assert calls == [0, 200, 400]
        restarted = Collector(Store(db), "https://technocore.chat", "technocore-tasks", client=client)
        again = await restarted.collect_once(refresh_metadata=False)
        assert again["inserted"] == 0
        assert Store(db).counts()["observations"] == 425


@pytest.mark.asyncio
async def test_429_retry_after_resumes_same_cursor(store, dids):
    waits = []
    calls = 0
    task_id = "task-a83fd2c9"

    async def sleeper(delay):
        waits.append(delay)

    def handler(request):
        nonlocal calls
        if response := metadata_response(request):
            return response
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, text="read bucket; retry in 2 seconds")
        msg = message(1, dids[1], task_id)
        return httpx.Response(200, json={"room": "technocore-tasks", "count": 1, "first_seq": 1, "last_seq": 1, "messages": [msg]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://technocore.chat") as client:
        result = await Collector(store, "https://technocore.chat", "technocore-tasks", client=client, sleeper=sleeper).collect_once()
    assert calls == 2 and waits == [2.0]
    assert result["cursor"] == 1


@pytest.mark.asyncio
async def test_retention_gap_is_recorded_not_fabricated(store, dids):
    task_id = "task-a83fd2c9"

    def handler(request):
        if response := metadata_response(request):
            return response
        messages = [message(seq, dids[1], task_id) for seq in range(251, 451)]
        return httpx.Response(200, json={"room": "technocore-tasks", "count": 200, "first_seq": 251, "last_seq": 450, "messages": messages})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://technocore.chat") as client:
        result = await Collector(store, "https://technocore.chat", "technocore-tasks", client=client).collect_once(max_pages=1)
    assert result["gaps"][0]["missing_from"] == 1
    assert result["gaps"][0]["missing_to"] == 250
    assert store.counts()["observations"] == 200


@pytest.mark.asyncio
async def test_duplicate_insert_is_idempotent(store, dids):
    task_id = "task-a83fd2c9"
    msg = message(1, dids[1], task_id)
    assert store.insert_message("technocore-tasks", msg)
    assert not store.insert_message("technocore-tasks", msg)
    assert store.counts()["observations"] == 1


def test_page_insert_is_atomic_and_idempotent(store, dids):
    task_id = "task-a83fd2c9"
    messages = [message(seq, dids[1], task_id) for seq in range(1, 201)]
    assert store.insert_messages("technocore-tasks", messages) == 200
    assert store.insert_messages("technocore-tasks", messages) == 0
    assert store.counts()["observations"] == 200
    collector = Collector(store, "https://technocore.chat", "technocore-tasks")
    assert collector.catchup_pages == 5
    assert collector.write_batch_size == 5
    assert collector.write_pause_seconds == 0.05


@pytest.mark.asyncio
async def test_sqlite_page_write_does_not_block_event_loop(store, dids, monkeypatch):
    task_id = "task-a83fd2c9"

    def handler(request):
        msg = message(1, dids[1], task_id)
        return httpx.Response(200, json={"room": "technocore-tasks", "count": 1,
                                        "first_seq": 1, "last_seq": 1, "messages": [msg]})

    original = store.insert_messages
    def slow_insert(room, messages):
        time.sleep(0.1)
        return original(room, messages)
    monkeypatch.setattr(store, "insert_messages", slow_insert)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://technocore.chat") as client:
        collector = Collector(store, "https://technocore.chat", "technocore-tasks", client=client)
        started = time.perf_counter()
        task = asyncio.create_task(collector.collect_once(refresh_metadata=False, max_pages=1))
        await asyncio.sleep(0.02)
        assert time.perf_counter() - started < 0.08
        await task


@pytest.mark.asyncio
async def test_collector_never_enumerates_rooms_or_private_resources(store):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if response := metadata_response(request):
            return response
        return httpx.Response(200, json={"room": "technocore-tasks", "count": 0, "first_seq": None, "last_seq": 0, "messages": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://technocore.chat") as client:
        await Collector(store, "https://technocore.chat", "technocore-tasks", client=client).collect_once()
    assert "/rooms" not in paths
    assert all("/p-" not in path for path in paths)
    assert set(paths) == {"/.well-known/agent.json", "/openapi.json", "/r/technocore-tasks"}
    with pytest.raises(ValueError):
        Collector(store, "https://technocore.chat", "p-secret")
    with pytest.raises(ValueError):
        Collector(store, "https://technocore.chat", "../not-a-room")
