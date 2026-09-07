# September 2026 production memory incident

## Impact

The single hosted Technocore Tasks replica repeatedly exhausted its practical memory headroom and restarted. During the incident, a request for one ordinary task did not return within three minutes. The collector and read-only API were unavailable whenever the process was down. No evidence was found that the SQLite database was deleted, reset, or had its collector cursor manually altered.

## Evidence and root cause

The deployed revision loaded every parsed observation with `fetchall()`, converted every row and `fields_json` value to Python objects, grouped the entire tape, reduced every task, and sorted the complete result for ordinary list/search/stat/detail requests. A detail lookup therefore reconstructed every task before selecting one. The homepage also repeated this work for its collection-history summary.

At incident scale the database held about 1.53 million observations and 283,699 distinct task IDs. Platform metrics showed roughly 5.3 GiB resident memory before a bounded detail probe and more than 6.1 GiB afterward; the request timed out at 180 seconds. The platform showed repeated instance restarts but did not retain an explicit Python traceback or kernel OOM line, so the exact final kill signal is unconfirmed. The allocation pattern and request reproduction establish unbounded whole-history materialization as the recurring memory-pressure mechanism; this is not described as a conventional retained-object leak.

## Repair

Version 0.2.0 replaces whole-history reconstruction with a versioned disk-backed projection:

- one scalar summary row per task;
- normalized participant, conflict, and distinct-value tables;
- per-event transition derivations stored in SQLite;
- fixed-size parsing and projection transactions with durable row-ID checkpoints;
- background, resumable historical maintenance instead of startup replay;
- hard pagination for all list, search, DID, HTML, and evidence paths (default 50, maximum 200);
- SQL aggregates for statistics and collection-history counts;
- lightweight health diagnostics for database, projection, cursor, gap, and collector state.

The raw `observations` table remains the source of truth. The migration does not reset or delete the database and does not change collector cursors.

## Backup and restore procedure

Before deploying a storage migration, create a SQLite-consistent snapshot with Python's online backup API while the service is live. Run `PRAGMA integrity_check` on the snapshot, compress it, and verify the SHA-256 of the decompressed artifact. Keep both a volume-resident recovery copy and an operator-downloaded copy until the release is accepted.

Rollback is deliberately manual:

1. Stop the exact existing service so no writer is active.
2. Preserve the current database as a second snapshot; never overwrite the only copy.
3. Decompress the accepted pre-deploy backup to a new filename.
4. Verify its recorded SHA-256 and run `PRAGMA integrity_check` again.
5. Atomically rename the current database aside and the verified restore file into the configured database path.
6. Start the same service and confirm `/health`, the persisted collector cursor, task counts, and read-only routes before removing either recovery copy.

No new service, volume, database, plan change, or externally supplied restoration tool is required.

## Prevention

Regression tests force a multi-page single-task history, assert the 200-row ceiling, and interrupt/reopen a two-row projection migration to prove checkpoint resumption. Release acceptance also includes a production-sized snapshot benchmark plus a bounded post-deploy observation window covering health, detail/list latency, instance restarts, and memory trend.
