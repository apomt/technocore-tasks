from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .events import DID_RE
from .protocols import detect_and_parse


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS observations (
                    room TEXT NOT NULL, seq INTEGER NOT NULL, timestamp TEXT NOT NULL,
                    signer_did TEXT, nonce INTEGER, original_message TEXT NOT NULL,
                    signed INTEGER NOT NULL, protocol_name TEXT, protocol_version TEXT,
                    event_kind TEXT, task_id TEXT, fields_json TEXT, parse_error TEXT,
                    PRIMARY KEY (room, seq)
                );
                CREATE INDEX IF NOT EXISTS observations_task ON observations(task_id, seq);
                CREATE TABLE IF NOT EXISTS collector_state (
                    room TEXT PRIMARY KEY, cursor INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS retention_gaps (
                    id INTEGER PRIMARY KEY, room TEXT NOT NULL, missing_from INTEGER NOT NULL,
                    missing_to INTEGER NOT NULL, observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(room, missing_from, missing_to)
                );
                CREATE TABLE IF NOT EXISTS service_metadata (
                    key TEXT PRIMARY KEY, value_json TEXT NOT NULL,
                    observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            columns = {row["name"] for row in db.execute("PRAGMA table_info(observations)")}
            for name in ("protocol_name", "protocol_version"):
                if name not in columns:
                    db.execute(f"ALTER TABLE observations ADD COLUMN {name} TEXT")
            legacy_rows = db.execute(
                "SELECT room,seq,original_message FROM observations WHERE protocol_name IS NULL"
            ).fetchall()
            for row in legacy_rows:
                adapter, parsed, error = detect_and_parse(row["original_message"])
                if adapter:
                    db.execute(
                        """UPDATE observations SET protocol_name=?,protocol_version=?,event_kind=?,
                           task_id=?,fields_json=?,parse_error=? WHERE room=? AND seq=?""",
                        (adapter.protocol_name, adapter.protocol_version,
                         parsed.event_kind if parsed else None, parsed.task_id if parsed else None,
                         json.dumps(parsed.fields, ensure_ascii=False, separators=(",", ":")) if parsed else None,
                         error, row["room"], row["seq"]),
                    )

    def insert_message(self, room: str, message: dict) -> bool:
        text = str(message.get("text", ""))
        adapter, parsed, error = detect_and_parse(text)
        signer, nonce = message.get("from"), message.get("nonce")
        signed = bool(isinstance(signer, str) and DID_RE.fullmatch(signer) and isinstance(nonce, int))
        with self.connect() as db:
            cur = db.execute(
                """INSERT OR IGNORE INTO observations
                (room,seq,timestamp,signer_did,nonce,original_message,signed,
                 protocol_name,protocol_version,event_kind,task_id,fields_json,parse_error)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (room, int(message["seq"]), str(message["ts"]),
                 str(signer) if signer is not None else None,
                 int(nonce) if isinstance(nonce, int) else None, text, int(signed),
                 adapter.protocol_name if adapter else None, adapter.protocol_version if adapter else None,
                 parsed.event_kind if parsed else None, parsed.task_id if parsed else None,
                 json.dumps(parsed.fields, ensure_ascii=False, separators=(",", ":")) if parsed else None,
                 error),
            )
            return cur.rowcount == 1

    def events(self, task_id: str | None = None, protocol: str | None = None) -> list[dict]:
        clauses, args = ["task_id IS NOT NULL"], []
        if task_id is not None:
            clauses.append("task_id = ?")
            args.append(task_id)
        if protocol is not None:
            clauses.append("protocol_name = ?")
            args.append(protocol.upper().replace("-V1", "").replace("/1", ""))
        query = "SELECT * FROM observations WHERE " + " AND ".join(clauses) + " ORDER BY room, seq"
        with self.connect() as db:
            rows = db.execute(query, tuple(args)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["fields"] = json.loads(item.pop("fields_json"))
            item["signed"] = bool(item["signed"])
            result.append(item)
        return result

    def cursor(self, room: str) -> int:
        with self.connect() as db:
            row = db.execute("SELECT cursor FROM collector_state WHERE room=?", (room,)).fetchone()
        return int(row[0]) if row else 0

    def set_cursor(self, room: str, cursor: int) -> None:
        with self.connect() as db:
            db.execute("""INSERT INTO collector_state(room,cursor) VALUES(?,?)
                ON CONFLICT(room) DO UPDATE SET cursor=excluded.cursor,updated_at=CURRENT_TIMESTAMP""",
                (room, int(cursor)))

    def record_gap(self, room: str, start: int, end: int) -> None:
        if end >= start:
            with self.connect() as db:
                db.execute("INSERT OR IGNORE INTO retention_gaps(room,missing_from,missing_to) VALUES(?,?,?)",
                           (room, int(start), int(end)))

    def gaps(self, room: str | None = None) -> list[dict]:
        query, args = "SELECT * FROM retention_gaps", ()
        if room is not None:
            query, args = query + " WHERE room=?", (room,)
        with self.connect() as db:
            return [dict(row) for row in db.execute(query + " ORDER BY id", args).fetchall()]

    def save_metadata(self, key: str, value: object) -> None:
        with self.connect() as db:
            db.execute("""INSERT INTO service_metadata(key,value_json) VALUES(?,?)
                ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,observed_at=CURRENT_TIMESTAMP""",
                (key, json.dumps(value, ensure_ascii=False)))

    def metadata(self) -> dict[str, object]:
        with self.connect() as db:
            rows = db.execute("SELECT key,value_json FROM service_metadata").fetchall()
        return {row["key"]: json.loads(row["value_json"]) for row in rows}

    def counts(self) -> dict[str, int]:
        with self.connect() as db:
            observations = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            parsed = db.execute("SELECT COUNT(*) FROM observations WHERE task_id IS NOT NULL").fetchone()[0]
            failures = db.execute("SELECT COUNT(*) FROM observations WHERE parse_error IS NOT NULL").fetchone()[0]
            signed = db.execute("SELECT COUNT(*) FROM observations WHERE signed=1 AND task_id IS NOT NULL").fetchone()[0]
            dids = db.execute("SELECT COUNT(DISTINCT signer_did) FROM observations WHERE signed=1 AND task_id IS NOT NULL").fetchone()[0]
            gaps = db.execute("SELECT COUNT(*) FROM retention_gaps").fetchone()[0]
        return {"observations": observations, "parsed_events": parsed, "signed_events": signed,
                "distinct_signer_dids": dids, "parse_failures": failures, "retention_gaps": gaps}
