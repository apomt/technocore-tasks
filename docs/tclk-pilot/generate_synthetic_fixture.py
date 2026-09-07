"""Generate a local-only Technocore Tasks scaling fixture with no production data."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

SYNTHETIC_PUBLIC_DID = "did:key:z6MkimcfTzAFj18jNxxYEWenqwr59AEPCWYhvG4qC5WdzrXY"


def event(seq: int, task_id: str, kind: str) -> tuple:
    timestamp = (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=seq)).isoformat().replace("+00:00", "Z")
    if kind == "JOB":
        text = f"JOB v1 | {task_id} | synthetic | Synthetic task {task_id} | Local benchmark evidence only"
        fields = {"job": task_id, "category": "synthetic", "title": f"Synthetic task {task_id}",
                  "body": "Local benchmark evidence only"}
    elif kind == "CLAIM":
        text = f"CLAIM v1 | {task_id} | Synthetic claim"
        fields = {"job": task_id, "claim": "Synthetic claim"}
    elif kind == "RESULT":
        text = f"RESULT v1 | {task_id} | Synthetic result"
        fields = {"job": task_id, "result": "Synthetic result"}
    else:
        text = f"ATTEST v1 | {task_id} | useful | Synthetic attestation"
        fields = {"job": task_id, "verdict": "useful", "reason": "Synthetic attestation"}
    return ("kibble", seq, timestamp, SYNTHETIC_PUBLIC_DID, seq, text, 1, "KIBBLE", "1", kind,
            task_id, json.dumps(fields, separators=(",", ":")), None)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--jobs", type=int, default=100_000)
    parser.add_argument("--hot-extra-events", type=int, default=500)
    args = parser.parse_args()
    if args.jobs < 1 or args.jobs > 1_000_000 or args.hot_extra_events < 0:
        raise SystemExit("jobs must be 1..1,000,000 and hot-extra-events must be non-negative")
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite {args.output}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(args.output)
    try:
        db.executescript("""
            PRAGMA journal_mode=DELETE;
            PRAGMA synchronous=NORMAL;
            CREATE TABLE observations (
                room TEXT NOT NULL, seq INTEGER NOT NULL, timestamp TEXT NOT NULL,
                signer_did TEXT, nonce INTEGER, original_message TEXT NOT NULL,
                signed INTEGER NOT NULL, protocol_name TEXT, protocol_version TEXT,
                event_kind TEXT, task_id TEXT, fields_json TEXT, parse_error TEXT,
                PRIMARY KEY (room, seq));
            CREATE INDEX observations_task ON observations(task_id, seq);
            CREATE TABLE collector_state (
                room TEXT PRIMARY KEY, cursor INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE retention_gaps (
                id INTEGER PRIMARY KEY, room TEXT NOT NULL, missing_from INTEGER NOT NULL,
                missing_to INTEGER NOT NULL, observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(room, missing_from, missing_to));
            CREATE TABLE service_metadata (
                key TEXT PRIMARY KEY, value_json TEXT NOT NULL,
                observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        """)
        insert = "INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)"
        batch, seq = [], 0
        for number in range(args.jobs):
            task_id = f"k{number:010x}"
            for kind in ("JOB", "CLAIM", "RESULT", "ATTEST"):
                seq += 1
                batch.append(event(seq, task_id, kind))
            if len(batch) >= 10_000:
                db.executemany(insert, batch)
                db.commit()
                batch.clear()
        hot_task = "k0000000000"
        for _ in range(args.hot_extra_events):
            seq += 1
            batch.append(event(seq, hot_task, "CLAIM"))
        if batch:
            db.executemany(insert, batch)
        db.execute("INSERT INTO collector_state(room,cursor) VALUES('kibble',?)", (seq,))
        db.commit()
    finally:
        db.close()

    manifest = {
        "fixture": args.output.name,
        "synthetic_only": True,
        "jobs": args.jobs,
        "observations": seq,
        "cursor": seq,
        "hot_task_id": hot_task,
        "hot_task_events": 4 + args.hot_extra_events,
        "sha256": sha256(args.output),
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
