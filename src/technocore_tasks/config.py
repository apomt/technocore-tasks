from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOM_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")


@dataclass(frozen=True)
class Settings:
    database: Path
    source_rooms: tuple[str, ...] = ("kibble",)
    signing_room: str = "technocore-tasks"
    base_url: str = "https://technocore.chat"
    mode: str = "hosted"
    collector_enabled: bool = True
    poll_seconds: float = 10.0

    @property
    def room(self) -> str:
        """Compatibility alias for the first read-only source room."""
        return self.source_rooms[0]

    @classmethod
    def from_env(cls) -> "Settings":
        mode = os.getenv("TASKS_MODE", "hosted").strip().lower()
        if mode not in {"hosted", "local"}:
            raise ValueError("TASKS_MODE must be 'hosted' or 'local'")
        raw_rooms = os.getenv("TASKS_SOURCE_ROOMS", os.getenv("TASKS_ROOM", "kibble"))
        rooms = tuple(dict.fromkeys(room.strip() for room in raw_rooms.split(",") if room.strip()))
        if not rooms:
            raise ValueError("TASKS_SOURCE_ROOMS must contain at least one public room")
        signing_room = os.getenv("TASKS_SIGNING_ROOM", "technocore-tasks").strip()
        if any(room.startswith("p-") or "-p-" in room for room in (*rooms, signing_room)):
            raise ValueError("private p-* rooms are forbidden")
        if any(not ROOM_RE.fullmatch(room) for room in (*rooms, signing_room)):
            raise ValueError("room names must match ^[a-z0-9][a-z0-9_-]{0,47}$")
        return cls(
            database=Path(os.getenv("TASKS_DATABASE", "technocore_tasks.db")),
            source_rooms=rooms,
            signing_room=signing_room,
            base_url=os.getenv("TECHNOCORE_BASE_URL", "https://technocore.chat").rstrip("/"),
            mode=mode,
            collector_enabled=os.getenv("TASKS_COLLECTOR_ENABLED", "1") == "1",
            poll_seconds=max(1.0, float(os.getenv("TASKS_POLL_SECONDS", "10"))),
        )
