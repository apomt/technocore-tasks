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
        self.page_size = 200
        self.running = False
        self.last_success_at: str | None = None
        self.last_error: str | None = None

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
        self.store.save_metadata("agent", agent)
        self.store.save_metadata("openapi_info", spec.get("info", {}))
        self.store.save_metadata("collector_page_size", self.page_size)

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

    async def collect_once(self, refresh_metadata: bool = True, max_pages: int = 100) -> dict:
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(base_url=self.base_url, timeout=20, follow_redirects=False)
        inserted = 0
        pages = 0
        try:
            if refresh_metadata:
                await self.refresh_metadata(client)
            while pages < max_pages:
                cursor = self.store.cursor(self.room)
                payload = await self._get_page(client, cursor)
                messages = payload.get("messages", [])
                first_seq = payload.get("first_seq")
                if first_seq is not None and int(first_seq) > cursor + 1:
                    self.store.record_gap(self.room, cursor + 1, int(first_seq) - 1)
                for message in messages:
                    inserted += int(self.store.insert_message(self.room, message))
                new_cursor = int(payload.get("last_seq", cursor))
                if new_cursor < cursor:
                    raise RuntimeError("Technocore cursor moved backwards")
                if messages and new_cursor != int(messages[-1]["seq"]):
                    raise RuntimeError("Technocore cursor does not match the last returned message")
                self.store.set_cursor(self.room, new_cursor)
                pages += 1
                if not messages or len(messages) < self.page_size or new_cursor == cursor:
                    break
            return {"pages": pages, "inserted": inserted, "cursor": self.store.cursor(self.room), "gaps": self.store.gaps(self.room)}
        finally:
            if owns_client:
                await client.aclose()

    async def run_forever(self, poll_seconds: float = 10.0) -> None:
        first = True
        self.running = True
        while True:
            try:
                await self.collect_once(refresh_metadata=first)
                first = False
                self.last_success_at = datetime.now(UTC).isoformat()
                self.last_error = None
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                # The next loop retries from the persisted cursor; no cursor is advanced on failure.
                self.last_error = f"{type(exc).__name__}: {exc}"
            await self.sleeper(poll_seconds)

    def diagnostics(self) -> dict:
        return {"room": self.room, "running": self.running, "cursor": self.store.cursor(self.room),
                "last_success_at": self.last_success_at, "last_error": self.last_error,
                "gaps": self.store.gaps(self.room)}
