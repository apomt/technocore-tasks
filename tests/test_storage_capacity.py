from __future__ import annotations

import json
import os
import sqlite3
from collections import namedtuple
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from technocore_tasks.capacity import classify_storage, storage_metrics
from technocore_tasks.collector import Collector
from technocore_tasks.config import Settings
from technocore_tasks.web import create_app

from conftest import add_create


@pytest.mark.parametrize(("percent", "expected"), [
    (79.99, "ok"), (80.0, "warning"), (89.99, "warning"),
    (90.0, "urgent"), (94.99, "urgent"), (95.0, "critical"), (100.0, "critical"),
])
def test_storage_threshold_classification(percent, expected):
    assert classify_storage(percent, 80.0, 90.0, 95.0) == expected


def test_storage_metrics_report_database_wal_shm_and_no_paths(tmp_path, monkeypatch):
    database = tmp_path / "tasks.db"
    database.write_bytes(b"db")
    Path(f"{database}-wal").write_bytes(b"w" * 8_000_000)
    Path(f"{database}-shm").write_bytes(b"s" * 32_768)
    total, free = 10_000_000, 2_000_000
    DiskUsage = namedtuple("DiskUsage", "total used free")
    monkeypatch.setattr("technocore_tasks.capacity.shutil.disk_usage",
                        lambda _: DiskUsage(total, total - free, free))

    result = storage_metrics(database)

    assert result["database_bytes"] == 2
    assert result["wal_bytes"] == 8_000_000
    assert result["shm_bytes"] == 32_768
    assert result["state"] == "warning"
    assert "path" not in json.dumps(result).lower()


def test_unavailable_filesystem_metrics_are_safe(tmp_path, monkeypatch):
    database = tmp_path / "tasks.db"
    monkeypatch.setattr("technocore_tasks.capacity.shutil.disk_usage",
                        lambda _: (_ for _ in ()).throw(OSError("sensitive mount detail")))

    result = storage_metrics(database)

    assert result["available"] is False
    assert result["state"] == "unavailable"
    assert result["error"] == "filesystem_metrics_unavailable"
    assert "sensitive" not in json.dumps(result)


def test_unavailable_database_counts_do_not_break_storage_health(store, monkeypatch):
    monkeypatch.setattr(store, "fast_counts",
                        lambda: (_ for _ in ()).throw(sqlite3.OperationalError("closed")))

    result = store.storage_health()

    assert result["observation_count"] is None
    assert result["projected_task_count"] is None


def test_health_storage_is_lightweight_and_does_not_scan_history(store, dids, monkeypatch):
    add_create(store, dids[0])
    settings = Settings(database=Path(store.path), collector_enabled=False)
    app = create_app(settings)
    monkeypatch.setattr(app.state.store, "counts",
                        lambda: (_ for _ in ()).throw(AssertionError("full scan called")))
    monkeypatch.setattr(app.state.store, "projection_stats",
                        lambda: (_ for _ in ()).throw(AssertionError("projection scan called")))

    with TestClient(app) as client:
        health = client.get("/health").json()

    assert health["storage"]["observation_count"] == 1
    assert health["storage"]["projected_task_count"] == 1
    assert health["storage"]["destructive_cleanup_enabled"] is False
    assert str(store.path) not in json.dumps(health)


@pytest.mark.asyncio
async def test_critical_capacity_pauses_collection_without_network_or_cursor_change(store, monkeypatch):
    store.set_cursor("kibble", 123)
    critical = {"available": True, "state": "critical", "observation_count": 0,
                "projected_task_count": 0}
    monkeypatch.setattr(store, "storage_health", lambda *args: critical)
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://example.test") as client:
        result = await Collector(store, "https://example.test", "kibble", client=client,
                                 pause_on_critical_storage=True).collect_once()

    assert result["paused_for_storage"] is True
    assert store.cursor("kibble") == 123
    assert requests == 0


@pytest.mark.asyncio
async def test_catchup_checkpoints_large_wal_within_a_page(store, dids, monkeypatch):
    messages = [{"seq": seq, "ts": f"2026-09-07T00:00:{seq:02d}Z", "from": dids[0],
                 "nonce": seq, "text": "unparsed public evidence"} for seq in range(1, 31)]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messages": messages, "first_seq": 1,
                                         "last_seq": 30})

    checkpoints = 0
    original = store.checkpoint_wal

    def checkpoint():
        nonlocal checkpoints
        checkpoints += 1
        return original()

    monkeypatch.setattr(store, "checkpoint_wal", checkpoint)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://example.test") as client:
        result = await Collector(store, "https://example.test", "kibble", client=client).collect_once(
            refresh_metadata=False, max_pages=1)

    assert result["inserted"] == 30
    assert checkpoints == 2


def test_storage_diagnostics_never_invoke_destructive_file_operations(tmp_path, monkeypatch):
    database = tmp_path / "tasks.db"
    database.write_bytes(b"evidence")
    destructive_calls = []
    monkeypatch.setattr(Path, "unlink", lambda *args, **kwargs: destructive_calls.append(args))
    monkeypatch.setattr(os, "remove", lambda *args, **kwargs: destructive_calls.append(args))

    storage_metrics(database)

    assert database.read_bytes() == b"evidence"
    assert destructive_calls == []


def test_invalid_storage_threshold_order_is_rejected(tmp_path):
    settings = Settings(database=tmp_path / "tasks.db", storage_warning_percent=95,
                        storage_urgent_percent=90, storage_critical_percent=80)
    with pytest.raises(ValueError, match="storage thresholds"):
        create_app(settings)
