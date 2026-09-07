from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .events import DID_RE, canonical_task_id
from .protocols import detect_and_parse

PROJECTION_VERSION = 1
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class IOGate:
    """Serialize broad reads/writes and let queued reads run before background writes."""
    def __init__(self):
        self.condition = threading.Condition()
        self.active = False
        self.waiting_readers = 0

    @contextmanager
    def read(self):
        with self.condition:
            self.waiting_readers += 1
            while self.active:
                self.condition.wait()
            self.waiting_readers -= 1
            self.active = True
        try:
            yield
        finally:
            with self.condition:
                self.active = False
                self.condition.notify_all()

    @contextmanager
    def write(self):
        with self.condition:
            while self.active or self.waiting_readers:
                self.condition.wait()
            self.active = True
        try:
            yield
        finally:
            with self.condition:
                self.active = False
                self.condition.notify_all()


def normalize_protocol(value: str | None) -> str | None:
    return value.upper().replace("-V1", "").replace("/1", "") if value else None


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.io_gate = IOGate()
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, True)
        db.execute("PRAGMA busy_timeout=30000")
        try:
            yield db
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _get(db: sqlite3.Connection, name: str) -> str | None:
        row = db.execute("SELECT value FROM maintenance_state WHERE name=?", (name,)).fetchone()
        return str(row[0]) if row else None

    @staticmethod
    def _set(db: sqlite3.Connection, name: str, value: str) -> None:
        db.execute("""INSERT INTO maintenance_state(name,value) VALUES(?,?) ON CONFLICT(name)
                      DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP""", (name, value))

    def initialize(self) -> None:
        """Only initializes schema; historical work is explicitly batched and resumable."""
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS observations (
                    room TEXT NOT NULL, seq INTEGER NOT NULL, timestamp TEXT NOT NULL,
                    signer_did TEXT, nonce INTEGER, original_message TEXT NOT NULL,
                    signed INTEGER NOT NULL, protocol_name TEXT, protocol_version TEXT,
                    event_kind TEXT, task_id TEXT, fields_json TEXT, parse_error TEXT,
                    PRIMARY KEY (room, seq));
                CREATE INDEX IF NOT EXISTS observations_task
                    ON observations(task_id,seq);
                CREATE TABLE IF NOT EXISTS collector_state (
                    room TEXT PRIMARY KEY,cursor INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS retention_gaps (
                    id INTEGER PRIMARY KEY,room TEXT NOT NULL,missing_from INTEGER NOT NULL,
                    missing_to INTEGER NOT NULL,observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(room,missing_from,missing_to));
                CREATE TABLE IF NOT EXISTS service_metadata (
                    key TEXT PRIMARY KEY,value_json TEXT NOT NULL,
                    observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS maintenance_state (
                    name TEXT PRIMARY KEY,value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS task_projections (
                    protocol_name TEXT NOT NULL,protocol_version TEXT NOT NULL,room TEXT NOT NULL,task_id TEXT NOT NULL,
                    creator_did TEXT,title TEXT NOT NULL DEFAULT 'Unknown work item (origin event not observed)',
                    description TEXT NOT NULL DEFAULT '',state TEXT NOT NULL DEFAULT 'partial',normalized_state TEXT,
                    created_at TEXT,assignee_did TEXT,advertised_json TEXT NOT NULL DEFAULT '{}',
                    partial_history INTEGER NOT NULL DEFAULT 1,conflict_count INTEGER NOT NULL DEFAULT 0,
                    event_count INTEGER NOT NULL DEFAULT 0,claim_count INTEGER NOT NULL DEFAULT 0,
                    result_count INTEGER NOT NULL DEFAULT 0,attestation_count INTEGER NOT NULL DEFAULT 0,
                    event_types_json TEXT NOT NULL DEFAULT '[]',completion_seen INTEGER NOT NULL DEFAULT 0,
                    terminal INTEGER NOT NULL DEFAULT 0,last_timestamp TEXT,last_seq INTEGER NOT NULL DEFAULT 0,
                    search_text TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(protocol_name,protocol_version,room,task_id));
                CREATE INDEX IF NOT EXISTS task_projections_order
                    ON task_projections(created_at DESC,task_id DESC);
                CREATE INDEX IF NOT EXISTS task_projections_state ON task_projections(normalized_state);
                CREATE INDEX IF NOT EXISTS task_projections_lookup ON task_projections(task_id,protocol_name);
                CREATE TABLE IF NOT EXISTS task_participants (
                    protocol_name TEXT NOT NULL,protocol_version TEXT NOT NULL,room TEXT NOT NULL,task_id TEXT NOT NULL,did TEXT NOT NULL,
                    PRIMARY KEY(protocol_name,protocol_version,room,task_id,did));
                CREATE INDEX IF NOT EXISTS task_participants_did ON task_participants(did);
                CREATE TABLE IF NOT EXISTS task_projection_values (
                    protocol_name TEXT NOT NULL,protocol_version TEXT NOT NULL,room TEXT NOT NULL,task_id TEXT NOT NULL,
                    value_kind TEXT NOT NULL,value_hash TEXT NOT NULL,value TEXT NOT NULL,
                    PRIMARY KEY(protocol_name,protocol_version,room,task_id,value_kind,value_hash));
                CREATE TABLE IF NOT EXISTS task_conflicts (
                    protocol_name TEXT NOT NULL,protocol_version TEXT NOT NULL,room TEXT NOT NULL,task_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,kind TEXT NOT NULL,reason TEXT NOT NULL,
                    PRIMARY KEY(protocol_name,protocol_version,room,task_id,seq,reason));
                CREATE TABLE IF NOT EXISTS event_derivations (
                    room TEXT NOT NULL,seq INTEGER NOT NULL,valid_transition INTEGER NOT NULL,reason TEXT,
                    PRIMARY KEY(room,seq));
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(observations)")}
            for name in ("protocol_name", "protocol_version"):
                if name not in columns:
                    db.execute(f"ALTER TABLE observations ADD COLUMN {name} TEXT")
            count = int(db.execute("SELECT COUNT(*) FROM observations").fetchone()[0])
            if count and self._get(db, "projection_version") != str(PROJECTION_VERSION):
                for name, value in (("parse_status", "pending"), ("parse_cursor", "0"),
                                    ("projection_status", "pending"), ("projection_cursor", "0"),
                                    ("projection_reset", "0")):
                    self._set(db, name, value)
            elif not count and self._get(db, "projection_version") is None:
                for name, value in (("parse_status", "complete"), ("parse_cursor", "0"),
                                    ("projection_status", "complete"), ("projection_cursor", "0"),
                                    ("projection_reset", "1"), ("projection_version", str(PROJECTION_VERSION))):
                    self._set(db, name, value)

    def maintenance_status(self, db: sqlite3.Connection | None = None) -> dict:
        if db is None:
            with self.connect() as owned:
                return self.maintenance_status(owned)
        maximum = int(db.execute("SELECT COALESCE(MAX(rowid),0) FROM observations").fetchone()[0])
        parse_status = self._get(db, "parse_status") or "pending"
        projection_status = self._get(db, "projection_status") or "pending"
        projection_cursor = int(self._get(db, "projection_cursor") or 0)
        if projection_status == "complete":
            projection_cursor = maximum
        return {"ready": parse_status == projection_status == "complete",
                "parse": {"status": parse_status, "cursor": int(self._get(db, "parse_cursor") or 0), "maximum": maximum},
                "projection": {"status": projection_status, "cursor": projection_cursor,
                               "maximum": maximum, "version": PROJECTION_VERSION}}

    def maintenance_step(self, batch_size: int = 1000) -> dict:
        size = max(1, min(int(batch_size), 5000))
        with self.io_gate.write(), self.connect() as db:
            if self._get(db, "parse_status") != "complete":
                cursor = int(self._get(db, "parse_cursor") or 0)
                rows = db.execute("""SELECT rowid,room,seq,original_message FROM observations
                                  WHERE rowid>? AND protocol_name IS NULL ORDER BY rowid LIMIT ?""",
                                  (cursor, size)).fetchall()
                for row in rows:
                    adapter, parsed, error = detect_and_parse(row["original_message"])
                    db.execute("""UPDATE observations SET protocol_name=?,protocol_version=?,event_kind=?,task_id=?,
                                  fields_json=?,parse_error=? WHERE room=? AND seq=?""",
                               (adapter.protocol_name if adapter else None, adapter.protocol_version if adapter else None,
                                parsed.event_kind if parsed else None, parsed.task_id if parsed else None,
                                json.dumps(parsed.fields, ensure_ascii=False, separators=(",", ":")) if parsed else None,
                                error, row["room"], row["seq"]))
                if rows:
                    self._set(db, "parse_cursor", str(rows[-1]["rowid"]))
                    return self.maintenance_status(db)
                self._set(db, "parse_status", "complete")
            if self._get(db, "projection_status") != "complete":
                if self._get(db, "projection_reset") != "1":
                    for table in ("task_projections", "task_participants", "task_projection_values",
                                  "task_conflicts", "event_derivations"):
                        db.execute(f"DELETE FROM {table}")
                    self._set(db, "projection_cursor", "0")
                    self._set(db, "projection_reset", "1")
                cursor = int(self._get(db, "projection_cursor") or 0)
                rows = db.execute("SELECT rowid,* FROM observations WHERE rowid>? ORDER BY rowid LIMIT ?",
                                  (cursor, size)).fetchall()
                for row in rows:
                    self._apply_projection(db, row)
                if rows:
                    self._set(db, "projection_cursor", str(rows[-1]["rowid"]))
                    return self.maintenance_status(db)
                self._set(db, "projection_status", "complete")
                self._set(db, "projection_version", str(PROJECTION_VERSION))
            return self.maintenance_status(db)

    def run_maintenance(self, batch_size: int = 1000) -> dict:
        status = self.maintenance_status()
        while not status["ready"]:
            status = self.maintenance_step(batch_size)
        return status

    @staticmethod
    def _key(row: sqlite3.Row) -> tuple[str, str, str, str]:
        return row["protocol_name"], row["protocol_version"], row["room"], row["task_id"]

    @staticmethod
    def _value(db, key, kind, value) -> None:
        digest = hashlib.sha256(value.encode()).hexdigest()
        db.execute("INSERT OR IGNORE INTO task_projection_values VALUES(?,?,?,?,?,?,?)", (*key, kind, digest, value))

    @staticmethod
    def _value_count(db, key, kind) -> int:
        return int(db.execute("""SELECT COUNT(*) FROM task_projection_values WHERE protocol_name=? AND
                              protocol_version=? AND room=? AND task_id=? AND value_kind=?""", (*key, kind)).fetchone()[0])

    def _conflict(self, db, key, seq, kind, reason) -> None:
        cur = db.execute("INSERT OR IGNORE INTO task_conflicts VALUES(?,?,?,?,?,?,?)", (*key, seq, kind, reason))
        if cur.rowcount:
            db.execute("""UPDATE task_projections SET conflict_count=conflict_count+1 WHERE
                          protocol_name=? AND protocol_version=? AND room=? AND task_id=?""", key)

    @staticmethod
    def _derive(db, row, valid, reason) -> None:
        db.execute("INSERT OR REPLACE INTO event_derivations VALUES(?,?,?,?)",
                   (row["room"], row["seq"], int(valid), reason))

    def _apply_projection(self, db: sqlite3.Connection, row: sqlite3.Row) -> None:
        if not row["task_id"] or not row["protocol_name"] or not row["fields_json"]:
            return
        key = self._key(row)
        gap = bool(db.execute("SELECT 1 FROM retention_gaps WHERE room=? LIMIT 1", (row["room"],)).fetchone())
        db.execute("""INSERT OR IGNORE INTO task_projections
                      (protocol_name,protocol_version,room,task_id,partial_history,last_timestamp,last_seq,search_text)
                      VALUES(?,?,?,?,?,?,?,?)""",
                   (*key, int(gap or not row["signed"] or row["event_kind"] not in {"JOB", "CREATE"}),
                    row["timestamp"], row["seq"], row["task_id"]))
        p = db.execute("""SELECT * FROM task_projections WHERE protocol_name=? AND protocol_version=?
                          AND room=? AND task_id=?""", key).fetchone()
        fields, kind, signer = json.loads(row["fields_json"]), row["event_kind"], row["signer_did"]
        event_types = json.loads(p["event_types_json"])
        if kind not in event_types:
            event_types.append(kind)
        db.execute("""UPDATE task_projections SET event_count=event_count+1,event_types_json=?,last_timestamp=?,last_seq=?
                      WHERE protocol_name=? AND protocol_version=? AND room=? AND task_id=?""",
                   (json.dumps(event_types, separators=(",", ":")), row["timestamp"], row["seq"], *key))
        if signer:
            db.execute("INSERT OR IGNORE INTO task_participants VALUES(?,?,?,?,?)", (*key, signer))
        if not row["signed"] or not signer or not DID_RE.fullmatch(signer):
            reason = "unsigned or invalid-DID event is not authoritative"
            self._derive(db, row, False, reason)
            self._conflict(db, key, row["seq"], kind, reason)
        elif row["protocol_name"] == "KIBBLE":
            self._apply_kibble(db, row, key, p, fields)
        else:
            self._apply_tc(db, row, key, p, fields)

    def _apply_kibble(self, db, row, key, p, fields) -> None:
        kind, signer = row["event_kind"], row["signer_did"]
        if kind == "JOB":
            if p["creator_did"] is None:
                gap = bool(db.execute("SELECT 1 FROM retention_gaps WHERE room=? LIMIT 1", (row["room"],)).fetchone())
                search = "\n".join((row["task_id"], row["protocol_name"], row["room"], signer,
                                    fields["title"], fields["body"]))
                db.execute("""UPDATE task_projections SET creator_did=?,title=?,description=?,created_at=?,advertised_json=?,
                              partial_history=?,state='open',normalized_state='open',search_text=? WHERE
                              protocol_name=? AND protocol_version=? AND room=? AND task_id=?""",
                           (signer, fields["title"], fields["body"], row["timestamp"],
                            json.dumps({"category": fields["category"]}, ensure_ascii=False), int(gap), search, *key))
                self._derive(db, row, True, None)
            else:
                reason = "multiple signed JOB origins observed; earliest is displayed"
                self._derive(db, row, False, reason); self._conflict(db, key, row["seq"], kind, reason)
            return
        self._derive(db, row, True, None)
        if kind == "CLAIM":
            self._value(db, key, "claimant", signer)
            db.execute("""UPDATE task_projections SET claim_count=claim_count+1,
                          state=CASE WHEN creator_did IS NULL THEN 'partial' ELSE 'claimed' END,
                          normalized_state=CASE WHEN creator_did IS NULL THEN 'partial' ELSE 'claimed' END
                          WHERE protocol_name=? AND protocol_version=? AND room=? AND task_id=?""", key)
            if self._value_count(db, key, "claimant") > 1:
                self._conflict(db, key, row["seq"], kind,
                               "multiple signer DIDs claimed this job; exclusivity is unspecified and not adjudicated")
        elif kind in {"RESULT", "DELIVER"}:
            self._value(db, key, "result", fields.get("result", ""))
            db.execute("""UPDATE task_projections SET result_count=result_count+1,completion_seen=1,
                          state=CASE WHEN creator_did IS NULL THEN 'partial' ELSE 'result' END,
                          normalized_state=CASE WHEN creator_did IS NULL THEN 'partial' ELSE 'results_submitted' END
                          WHERE protocol_name=? AND protocol_version=? AND room=? AND task_id=?""", key)
            if self._value_count(db, key, "result") > 1:
                self._conflict(db, key, row["seq"], kind,
                               "different signed result texts were observed; no winner is inferred")
        elif kind == "ATTEST":
            self._value(db, key, "verdict", fields.get("verdict", ""))
            db.execute("""UPDATE task_projections SET attestation_count=attestation_count+1,
                          state=CASE WHEN creator_did IS NULL THEN 'partial' ELSE 'attested' END,
                          normalized_state=CASE WHEN creator_did IS NULL THEN 'partial' ELSE 'attested_completed' END
                          WHERE protocol_name=? AND protocol_version=? AND room=? AND task_id=?""", key)
            if self._value_count(db, key, "verdict") > 1:
                self._conflict(db, key, row["seq"], kind,
                               "both useful and not attestations were observed; no authority ranking is inferred")

    def _apply_tc(self, db, row, key, p, fields) -> None:
        kind, signer, reason = row["event_kind"], row["signer_did"], None
        if kind == "CREATE":
            expected = canonical_task_id(signer, row["nonce"], fields["title"])
            if expected != row["task_id"]:
                reason = f"CREATE task id mismatch; expected {expected}"
            elif p["creator_did"] is not None:
                reason = "duplicate CREATE preserved; earliest valid CREATE establishes the task"
            else:
                advertised = {k: fields[k] for k in ("reward", "budget", "payment") if k in fields}
                gap = bool(db.execute("SELECT 1 FROM retention_gaps WHERE room=? LIMIT 1", (row["room"],)).fetchone())
                search = "\n".join((row["task_id"], row["protocol_name"], row["room"], signer,
                                    fields["title"], fields.get("description", "")))
                db.execute("""UPDATE task_projections SET creator_did=?,title=?,description=?,created_at=?,advertised_json=?,
                              partial_history=?,state='open',normalized_state='open',search_text=? WHERE
                              protocol_name=? AND protocol_version=? AND room=? AND task_id=?""",
                           (signer, fields["title"], fields.get("description", ""), row["timestamp"],
                            json.dumps(advertised, ensure_ascii=False), int(gap), search, *key))
        elif p["creator_did"] is None:
            reason = "partial history: valid CREATE was not observed"
        elif kind == "CLAIM":
            if p["terminal"]:
                reason = "CLAIM occurred after a terminal event"
            else:
                self._value(db, key, "claimant", signer)
                db.execute("""UPDATE task_projections SET claim_count=claim_count+1,
                              state=CASE WHEN assignee_did IS NULL THEN 'claimed' ELSE state END,
                              normalized_state=CASE WHEN assignee_did IS NULL THEN 'claimed' ELSE normalized_state END
                              WHERE protocol_name=? AND protocol_version=? AND room=? AND task_id=?""", key)
        elif kind == "ASSIGN":
            assignee = fields["assignee"]
            if signer != p["creator_did"]: reason = "ASSIGN signer is not the original creator DID"
            elif p["terminal"] or p["completion_seen"]: reason = "ASSIGN occurred after completion or a terminal event"
            elif not db.execute("""SELECT 1 FROM task_projection_values WHERE protocol_name=? AND protocol_version=?
                                  AND room=? AND task_id=? AND value_kind='claimant' AND value=?""", (*key, assignee)).fetchone():
                reason = "ASSIGN target has no observed valid CLAIM"
            else:
                if p["assignee_did"] and p["assignee_did"] != assignee:
                    self._conflict(db, key, row["seq"], kind,
                                   "conflicting creator-signed ASSIGN; latest valid event wins")
                db.execute("""UPDATE task_projections SET assignee_did=?,state='assigned',normalized_state='claimed'
                              WHERE protocol_name=? AND protocol_version=? AND room=? AND task_id=?""", (assignee, *key))
        elif kind == "COMPLETE":
            if p["terminal"]: reason = "COMPLETE occurred after a terminal event"
            elif not p["assignee_did"]: reason = "COMPLETE has no valid assignment"
            elif signer != p["assignee_did"]: reason = "COMPLETE signer is not the latest valid assignee DID"
            else:
                db.execute("""UPDATE task_projections SET result_count=result_count+1,completion_seen=1,
                              state='completed',normalized_state='results_submitted' WHERE
                              protocol_name=? AND protocol_version=? AND room=? AND task_id=?""", key)
        elif kind in {"CLOSE", "CANCEL"}:
            if signer != p["creator_did"]: reason = f"{kind} signer is not the original creator DID"
            elif p["terminal"]: reason = "duplicate or conflicting terminal event"
            else:
                state, normalized = ("closed", "attested_completed") if kind == "CLOSE" else ("cancelled", None)
                db.execute("""UPDATE task_projections SET terminal=1,state=?,normalized_state=? WHERE
                              protocol_name=? AND protocol_version=? AND room=? AND task_id=?""", (state, normalized, *key))
        self._derive(db, row, reason is None, reason)
        if reason and reason != "partial history: valid CREATE was not observed":
            self._conflict(db, key, row["seq"], kind, reason)

    @staticmethod
    def _message_values(room: str, message: dict) -> tuple:
        text = str(message.get("text", "")); adapter, parsed, error = detect_and_parse(text)
        signer, nonce = message.get("from"), message.get("nonce")
        signed = bool(isinstance(signer, str) and DID_RE.fullmatch(signer) and isinstance(nonce, int))
        return (room, int(message["seq"]), str(message["ts"]), str(signer) if signer is not None else None,
                int(nonce) if isinstance(nonce, int) else None, text, int(signed),
                adapter.protocol_name if adapter else None, adapter.protocol_version if adapter else None,
                parsed.event_kind if parsed else None, parsed.task_id if parsed else None,
                json.dumps(parsed.fields, ensure_ascii=False, separators=(",", ":")) if parsed else None, error)

    def insert_messages(self, room: str, messages: list[dict]) -> int:
        inserted = 0
        with self.io_gate.write(), self.connect() as db:
            projected = self._get(db, "projection_status") == "complete"
            for message in messages:
                cur = db.execute("""INSERT OR IGNORE INTO observations
                    (room,seq,timestamp,signer_did,nonce,original_message,signed,protocol_name,protocol_version,
                     event_kind,task_id,fields_json,parse_error) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    self._message_values(room, message))
                if cur.rowcount:
                    inserted += 1
                    if projected:
                        row = db.execute("SELECT rowid,* FROM observations WHERE room=? AND seq=?",
                                         (room, int(message["seq"]))).fetchone()
                        self._apply_projection(db, row)
        return inserted

    def insert_message(self, room: str, message: dict) -> bool:
        return self.insert_messages(room, [message]) == 1

    @staticmethod
    def _page(page: int, size: int, total: int) -> dict:
        return {"page": page, "page_size": size, "total": total, "pages": (total + size - 1) // size,
                "has_previous": page > 1, "has_next": page * size < total}

    def projection_rows(self, query="", state=None, protocol=None, did=None, page=1, page_size=DEFAULT_PAGE_SIZE):
        page, size = max(1, int(page)), max(1, min(int(page_size), MAX_PAGE_SIZE))
        clauses, args = [], []
        if protocol: clauses.append("p.protocol_name=?"); args.append(normalize_protocol(protocol))
        if state == "conflicted": clauses.append("p.conflict_count>0")
        elif state: clauses.append("(p.state=? OR p.normalized_state=?)"); args.extend((state, state))
        if query.strip():
            clauses.append("""(instr(lower(p.search_text),lower(?))>0 OR EXISTS (SELECT 1 FROM task_participants x
                WHERE x.protocol_name=p.protocol_name AND x.protocol_version=p.protocol_version AND x.room=p.room
                AND x.task_id=p.task_id AND instr(lower(x.did),lower(?))>0))""")
            args.extend((query.strip(), query.strip()))
        if did:
            clauses.append("""EXISTS (SELECT 1 FROM task_participants x WHERE x.protocol_name=p.protocol_name
                AND x.protocol_version=p.protocol_version AND x.room=p.room AND x.task_id=p.task_id AND x.did=?)""")
            args.append(did)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as db:
            total = int(db.execute("SELECT COUNT(*) FROM task_projections p" + where, args).fetchone()[0])
            rows = [dict(r) for r in db.execute("SELECT p.* FROM task_projections p" + where +
                    " ORDER BY p.created_at DESC,p.task_id DESC LIMIT ? OFFSET ?",
                    (*args, size, (page - 1) * size)).fetchall()]
        return rows, self._page(page, size, total)

    def projection(self, task_id: str, protocol: str | None = None) -> dict | None:
        clauses, args = ["task_id=?"], [task_id]
        if protocol: clauses.append("protocol_name=?"); args.append(normalize_protocol(protocol))
        with self.connect() as db:
            rows = db.execute("SELECT * FROM task_projections WHERE " + " AND ".join(clauses) + " LIMIT 2", args).fetchall()
        return dict(rows[0]) if len(rows) == 1 else None

    def events(self, task_id: str, protocol=None, page=1, page_size=DEFAULT_PAGE_SIZE, room: str | None = None):
        page, size = max(1, int(page)), max(1, min(int(page_size), MAX_PAGE_SIZE))
        clauses, args = ["o.task_id=?"], [task_id]
        if protocol: clauses.append("o.protocol_name=?"); args.append(normalize_protocol(protocol))
        if room: clauses.append("o.room=?"); args.append(room)
        where = " AND ".join(clauses)
        with self.connect() as db:
            total = int(db.execute("SELECT COUNT(*) FROM observations o WHERE " + where, args).fetchone()[0])
            rows = db.execute("""SELECT o.*,d.valid_transition,d.reason FROM observations o LEFT JOIN event_derivations d
                ON d.room=o.room AND d.seq=o.seq WHERE """ + where +
                " ORDER BY o.seq LIMIT ? OFFSET ?", (*args, size, (page - 1) * size)).fetchall()
        result = []
        for row in rows:
            item = dict(row); item["fields"] = json.loads(item.pop("fields_json")); item["signed"] = bool(item["signed"])
            item["valid_transition"] = bool(item["valid_transition"]); result.append(item)
        return result, self._page(page, size, total)

    def conflicts(self, row: dict, page=1, page_size=DEFAULT_PAGE_SIZE):
        page, size = max(1, int(page)), max(1, min(int(page_size), MAX_PAGE_SIZE))
        key = row["protocol_name"], row["protocol_version"], row["room"], row["task_id"]
        with self.connect() as db:
            total = int(db.execute("""SELECT COUNT(*) FROM task_conflicts WHERE protocol_name=? AND protocol_version=?
                                   AND room=? AND task_id=?""", key).fetchone()[0])
            rows = [dict(r) for r in db.execute("""SELECT room,seq,kind,reason FROM task_conflicts WHERE
                protocol_name=? AND protocol_version=? AND room=? AND task_id=? ORDER BY seq LIMIT ? OFFSET ?""",
                (*key, size, (page - 1) * size)).fetchall()]
        return rows, self._page(page, size, total)

    def cursor(self, room: str) -> int:
        with self.connect() as db:
            row = db.execute("SELECT cursor FROM collector_state WHERE room=?", (room,)).fetchone()
        return int(row[0]) if row else 0

    def set_cursor(self, room: str, cursor: int) -> None:
        with self.connect() as db:
            db.execute("""INSERT INTO collector_state(room,cursor) VALUES(?,?) ON CONFLICT(room)
                          DO UPDATE SET cursor=excluded.cursor,updated_at=CURRENT_TIMESTAMP""", (room, int(cursor)))

    def record_gap(self, room: str, start: int, end: int) -> None:
        if end >= start:
            with self.connect() as db:
                db.execute("INSERT OR IGNORE INTO retention_gaps(room,missing_from,missing_to) VALUES(?,?,?)",
                           (room, int(start), int(end)))
                db.execute("UPDATE task_projections SET partial_history=1 WHERE room=?", (room,))

    def gaps(self, room: str | None = None, limit: int = MAX_PAGE_SIZE) -> list[dict]:
        query, args = "SELECT * FROM retention_gaps", ()
        if room is not None: query, args = query + " WHERE room=?", (room,)
        size = max(1, min(int(limit), MAX_PAGE_SIZE))
        with self.connect() as db:
            return [dict(row) for row in db.execute(query + " ORDER BY id LIMIT ?", (*args, size)).fetchall()]

    def gap_count(self, room: str | None = None) -> int:
        query, args = "SELECT COUNT(*) FROM retention_gaps", ()
        if room is not None: query, args = query + " WHERE room=?", (room,)
        with self.connect() as db:
            return int(db.execute(query, args).fetchone()[0])

    def save_metadata(self, key: str, value: object) -> None:
        with self.connect() as db:
            db.execute("""INSERT INTO service_metadata(key,value_json) VALUES(?,?) ON CONFLICT(key)
                          DO UPDATE SET value_json=excluded.value_json,observed_at=CURRENT_TIMESTAMP""",
                       (key, json.dumps(value, ensure_ascii=False)))

    def metadata(self) -> dict[str, object]:
        with self.connect() as db:
            rows = db.execute("SELECT key,value_json FROM service_metadata").fetchall()
        return {row["key"]: json.loads(row["value_json"]) for row in rows}

    def counts(self) -> dict[str, int]:
        with self.connect() as db:
            row = db.execute("""SELECT COUNT(*) observations,COUNT(task_id) parsed_events,
                COALESCE(SUM(CASE WHEN signed=1 AND task_id IS NOT NULL THEN 1 ELSE 0 END),0) signed_events,
                COUNT(DISTINCT CASE WHEN signed=1 AND task_id IS NOT NULL THEN signer_did END) distinct_signer_dids,
                COALESCE(SUM(parse_error IS NOT NULL),0) parse_failures FROM observations""").fetchone()
            gaps = int(db.execute("SELECT COUNT(*) FROM retention_gaps").fetchone()[0])
        return {**dict(row), "retention_gaps": gaps}

    def projection_stats(self) -> dict:
        with self.connect() as db:
            total = int(db.execute("SELECT COUNT(*) FROM task_projections").fetchone()[0])
            native = {r[0]: int(r[1]) for r in db.execute("SELECT state,COUNT(*) FROM task_projections GROUP BY state")}
            protocols = {f"{r[0]}-{r[1]}": int(r[2]) for r in db.execute(
                "SELECT protocol_name,protocol_version,COUNT(*) FROM task_projections GROUP BY protocol_name,protocol_version")}
            conflicted = int(db.execute("SELECT COUNT(*) FROM task_projections WHERE conflict_count>0").fetchone()[0])
            partial = int(db.execute("SELECT COUNT(*) FROM task_projections WHERE partial_history=1").fetchone()[0])
        return {"tasks": total, "native_states": native, "states": native, "protocols": protocols,
                "conflicted": conflicted, "partial_history": partial}

    def collection_summary(self) -> dict[str, int]:
        with self.connect() as db:
            row = db.execute("""SELECT COUNT(*) total_jobs,
                              COALESCE(SUM(partial_history),0) partial_jobs FROM task_projections""").fetchone()
        return {"total_jobs": int(row["total_jobs"]), "partial_jobs": int(row["partial_jobs"])}

    def database_health(self) -> dict:
        try:
            with self.connect() as db:
                db.execute("SELECT 1").fetchone(); journal_mode = db.execute("PRAGMA journal_mode").fetchone()[0]
            return {"available": True, "journal_mode": journal_mode}
        except sqlite3.Error as exc:
            return {"available": False, "error": type(exc).__name__}

    def checkpoint_wal(self) -> dict[str, int]:
        with self.connect() as db:
            busy, log_pages, checkpointed_pages = db.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        return {"busy": int(busy), "log_pages": int(log_pages),
                "checkpointed_pages": int(checkpointed_pages)}
