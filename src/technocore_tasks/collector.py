from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from collections.abc import Awaitable, Callable

import httpx

from .storage import Store


class Collector:
    """Read one exact public room. It never calls /rooms or any p-* resource."""

    def __init__(
        self,
        store: Store,
        base_url: str,
        room: str,
        client: httpx.AsyncClient | None = None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        storage_thresholds: tuple[float, float, float] = (80.0, 90.0, 95.0),
        pause_on_critical_storage: bool = False,
    ):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", room):
            raise ValueError("invalid public room name")
        if room.startswith("p-") or "-p-" in room:
            raise ValueError("private room collection is forbidden")
        self.store = store
        self.base_url = base_url.rstrip("/")
        self.room = room
        self.client = client
        self.sleeper = sleeper
        self.storage_thresholds = storage_thresholds
        self.pause_on_critical_storage = pause_on_critical_storage
        self.page_size = 200
        self.catchup_pages = 5
        self.write_batch_size = 1
        self.write_pause_seconds = 0.05
        self.wal_checkpoint_interval = 25
        self.running = False
        self.last_success_at: str | None = None
        self.last_error: str | None = None
        self.last_wal_checkpoint: dict | None = None
        self.storage_state = "unknown"
        self.paused_for_storage = False

    async def refresh_metadata(self, client: httpx.AsyncClient) -> None:
        agent = (await client.get("/.well-known/agent.json")).raise_for_status().json()
        spec = (await client.get("/openapi.json")).raise_for_status().json()
        maximum = 200
        try:
            params = spec["paths"]["/r/{room}"]["get"]["parameters"]
            maximum = next(p["schema"]["maximum"] for p in params if p["name"] == "limit")
        except (KeyError, StopIteration, TypeError):
            pass
        self.page_size = max(1, min(200, int(maximum)))
        await asyncio.to_thread(self.store.save_metadata, "agent", agent)
        await asyncio.to_thread(self.store.save_metadata, "openapi_info", spec.get("info", {}))
        await asyncio.to_thread(self.store.save_metadata, "collector_page_size", self.page_size)

    @staticmethod
    def _retry_after(response: httpx.Response) -> float:
        raw = response.headers.get("Retry-After", "")
        try:
            return max(0.0, min(float(raw), 300.0))
        except ValueError:
            match = re.search(r"(?:retry|wait)\D+(\d+(?:\.\d+)?)", response.text, re.I)
            return min(float(match.group(1)), 300.0) if match else 1.0

    async def _get_page(self, client: httpx.AsyncClient, cursor: int) -> dict:
        while True:
            response = await client.get(
                f"/r/{self.room}",
                params={"since": cursor, "limit": self.page_size, "format": "json"},
            )
            if response.status_code != 429:
                response.raise_for_status()
                return response.json()
            await self.sleeper(self._retry_after(response))

    async def collect_once(self, refresh_metadata: bool = True, max_pages: int = 100,
                           write_pause_seconds: float = 0.0) -> dict:
        storage = await asyncio.to_thread(self.store.storage_health, *self.storage_thresholds)
        self.storage_state = storage["state"]
        self.paused_for_storage = bool(
            self.pause_on_critical_storage and storage["available"] and storage["state"] == "critical"
        )
        if self.paused_for_storage:
            return {"pages": 0, "inserted": 0, "cursor": await asyncio.to_thread(
                    self.store.cursor, self.room), "gaps": await asyncio.to_thread(
                    self.store.gaps, self.room), "paused_for_storage": True}
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(base_url=self.base_url, timeout=20, follow_redirects=False)
        inserted = 0
        pages = 0
        try:
            if refresh_metadata:
                await self.refresh_metadata(client)
            while pages < max_pages:
                cursor = await asyncio.to_thread(self.store.cursor, self.room)
                payload = await self._get_page(client, cursor)
                messages = payload.get("messages", [])
                first_seq = payload.get("first_seq")
                if first_seq is not None and int(first_seq) > cursor + 1:
                    await asyncio.to_thread(self.store.record_gap, self.room, cursor + 1, int(first_seq) - 1)
                processed = 0
                for start in range(0, len(messages), self.write_batch_size):
                    batch = messages[start:start + self.write_batch_size]
                    inserted += await asyncio.to_thread(self.store.insert_messages, self.room, batch)
                    processed += len(batch)
                    if processed % self.wal_checkpoint_interval == 0:
                        self.last_wal_checkpoint = await asyncio.to_thread(self.store.checkpoint_wal, True)
                        storage = await asyncio.to_thread(self.store.storage_health, *self.storage_thresholds)
                        self.storage_state = storage["state"]
                        if (self.pause_on_critical_storage and storage["available"]
                                and storage["state"] == "critical"):
                            self.paused_for_storage = True
                            return {"pages": pages, "inserted": inserted, "cursor": cursor,
                                    "gaps": await asyncio.to_thread(self.store.gaps, self.room),
                                    "paused_for_storage": True}
                    if write_pause_seconds:
                        await asyncio.sleep(write_pause_seconds)
                if messages and processed % self.wal_checkpoint_interval:
                    self.last_wal_checkpoint = await asyncio.to_thread(self.store.checkpoint_wal, True)
                new_cursor = int(payload.get("last_seq", cursor))
                if new_cursor < cursor:
                    raise RuntimeError("Technocore cursor moved backwards")
                if messages and new_cursor != int(messages[-1]["seq"]):
                    raise RuntimeError("Technocore cursor does not match the last returned message")
                await asyncio.to_thread(self.store.set_cursor, self.room, new_cursor)
                pages += 1
                if not messages or len(messages) < self.page_size or new_cursor == cursor:
                    break
            cursor = await asyncio.to_thread(self.store.cursor, self.room)
            gaps = await asyncio.to_thread(self.store.gaps, self.room)
            return {"pages": pages, "inserted": inserted, "cursor": cursor, "gaps": gaps}
        finally:
            if owns_client:
                await client.aclose()

    async def run_forever(self, poll_seconds: float = 10.0) -> None:
        first = True
        self.running = True
        while True:
            try:
                result = await self.collect_once(refresh_metadata=first, max_pages=self.catchup_pages,
                                                 write_pause_seconds=self.write_pause_seconds)
                if not result.get("paused_for_storage"):
                    self.last_wal_checkpoint = await asyncio.to_thread(self.store.checkpoint_wal)
                first = False
                if result.get("paused_for_storage"):
                    self.last_error = "storage capacity critical; collection paused without deleting evidence"
                else:
                    self.last_success_at = datetime.now(UTC).isoformat()
                    self.last_error = None
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                # The next loop retries from the persisted cursor; no cursor is advanced on failure.
                self.last_error = f"{type(exc).__name__}: {exc}"
            await self.sleeper(poll_seconds)

    def diagnostics(self) -> dict:
        gap_count = self.store.gap_count(self.room)
        return {"room": self.room, "running": self.running, "cursor": self.store.cursor(self.room),
                "last_success_at": self.last_success_at, "last_error": self.last_error,
                "catchup_page_limit": self.catchup_pages,
                "write_batch_size": self.write_batch_size,
                "write_pause_seconds": self.write_pause_seconds,
                "wal_checkpoint_interval": self.wal_checkpoint_interval,
                "last_wal_checkpoint": self.last_wal_checkpoint,
                "storage_state": self.storage_state,
                "paused_for_storage": self.paused_for_storage,
                "gap_count": gap_count, "gaps": self.store.gaps(self.room, limit=20),
                "gaps_truncated": gap_count > 20}
