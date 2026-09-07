# Storage capacity diagnostics

`GET /health` exposes safe, constant-time storage diagnostics under `storage`. It stats only the
database, WAL, and SHM paths, reads filesystem capacity, and uses indexed row-ID maxima for the two
append-only/rebuilt counts. It does not enumerate directories, scan observation history, expose a
filesystem path, or run cleanup.

The stable field names for FLOP Testnet Ops and other monitors are:

- `storage.available`
- `storage.capacity_bytes`
- `storage.used_bytes`
- `storage.free_bytes`
- `storage.percent_used`
- `storage.state` (`ok`, `warning`, `urgent`, `critical`, or `unavailable`)
- `storage.thresholds_percent.warning`
- `storage.thresholds_percent.urgent`
- `storage.thresholds_percent.critical`
- `storage.database_bytes`
- `storage.wal_bytes`
- `storage.shm_bytes`
- `storage.last_successful_wal_checkpoint_at`
- `storage.observation_count`
- `storage.projected_task_count`
- `storage.destructive_cleanup_enabled` (always `false`)
- `collectors[].storage_state`
- `collectors[].paused_for_storage`

Defaults are warning at 80%, urgent at 90%, and critical at 95%. They can be changed with
`TASKS_STORAGE_WARNING_PERCENT`, `TASKS_STORAGE_URGENT_PERCENT`, and
`TASKS_STORAGE_CRITICAL_PERCENT`; startup rejects unordered or out-of-range values.

In hosted mode, a measured critical state pauses new collection before any network fetch or cursor
advance. The database and existing evidence remain readable, no cleanup runs, and `/health` remains
HTTP-readable with top-level `status=degraded`. Collection resumes automatically if an operator
makes sufficient capacity available. Unavailable filesystem metrics are surfaced as `unavailable`
and do not pause collection because an unknown measurement is not evidence that the volume is full.
