# Counterparty reproduction package

This package contains no production data. `generate_synthetic_fixture.py` creates artificial
KIBBLE-shaped rows locally; `benchmark_pilot.py` runs each endpoint in an isolated subprocess,
records process-tree RSS, and terminates it if the fixed memory or time budget is exceeded.

## Included safe material

- `pilot-brief.md`
- `../../incident-2026-09-oom.md`
- `generate_synthetic_fixture.py`
- `benchmark_pilot.py`
- `benchmark-schema.json`
- this checklist and command sequence

Relevant immutable code references:

- Old whole-history release: [`Technocore Tasks v0.1.0`](https://github.com/apomt/technocore-tasks/tree/v0.1.0)
- OOM repair: [`v0.2.10 / c2821cd`](https://github.com/apomt/technocore-tasks/tree/v0.2.10)
- Storage safeguards: [`v0.2.11 / a2cd318`](https://github.com/apomt/technocore-tasks/tree/v0.2.11)

## Reference procedure (PowerShell, Python 3.12)

Run on a machine with at least 8 GiB free disk. The 3,072 MiB limit is enforced on each benchmark
subprocess; do not relax it for only one release.

```powershell
git clone https://github.com/apomt/technocore-tasks.git technocore-tasks-source
git -C .\technocore-tasks-source worktree add ..\tasks-old v0.1.0
git -C .\technocore-tasks-source worktree add ..\tasks-repaired v0.2.11

py -3.12 .\pilot-package\generate_synthetic_fixture.py .\baseline.db --jobs 400000 --hot-extra-events 500
Copy-Item -LiteralPath .\baseline.db -Destination .\old.db
Copy-Item -LiteralPath .\baseline.db -Destination .\repaired.db

py -3.12 -m venv .\.venv-old
py -3.12 -m venv .\.venv-repaired
& .\.venv-old\Scripts\python -m pip install -e ".\tasks-old[test]" psutil
& .\.venv-repaired\Scripts\python -m pip install -e ".\tasks-repaired[test]" psutil

& .\.venv-repaired\Scripts\python .\tasks-repaired\scripts\benchmark_store.py .\repaired.db --migrate --batch-size 5000 `
  --task-id k0000000000 | Tee-Object .\migration-v0.2.11.json

& .\.venv-old\Scripts\python .\pilot-package\benchmark_pilot.py --database .\old.db `
  --output .\benchmark-v0.1.0.json --memory-mib 3072 --timeout-seconds 180
& .\.venv-repaired\Scripts\python .\pilot-package\benchmark_pilot.py --database .\repaired.db `
  --output .\benchmark-v0.2.11.json --memory-mib 3072 --timeout-seconds 180

Get-FileHash -Algorithm SHA256 .\baseline.db, .\baseline.db.manifest.json, `
  .\benchmark-v0.1.0.json, .\benchmark-v0.2.11.json, .\migration-v0.2.11.json
```

Record CPU model, logical core count, RAM, OS/build, filesystem, Python version, dependency lock
or freeze, free disk before/after, and whether antivirus/indexing was active. Do not claim a true
cold-cache measurement unless the operator used and documented an OS-supported cache-isolation
method. Fresh processes and fresh database copies are required, but are only a cold-cache proxy.

## Required measurements

For both releases report outcome, latency, exit code, timeout, peak RSS bytes/MiB, HTTP status, and
response bytes for startup, homepage, search, stats, HTML task detail, and JSON task detail. Preserve
raw JSON matching `benchmark-schema.json`.

Correctness checks must show:

- `before == after` for observation count, min/max sequence, and persisted cursor;
- `PRAGMA quick_check` returns `ok`;
- repaired projection status is ready and projected task count is 400,000;
- hot task `k0000000000` has 504 evidence events but repaired JSON returns at most 200 with pagination;
- a normal synthetic task reconstructs to native state `attested`;
- closing and reopening the repaired release preserves cursor, projections, and counts.

## Acceptance checklist

- [ ] Environment specification is complete.
- [ ] Exact commands and exit codes are included.
- [ ] Synthetic dataset parameters and manifest SHA-256 are included.
- [ ] Machine-readable JSON or CSV conforms to the supplied schema.
- [ ] Markdown findings distinguish measured fact, inference, and limitation.
- [ ] Before/after RSS and latency are reported for both releases.
- [ ] Correctness, pagination, evidence preservation, and restart checks are reported.
- [ ] Cold-cache limitations and every remaining failure are disclosed.
- [ ] Raw outputs and report are at one immutable public artifact URL with hashes.

Agreement with the repair claim is not an acceptance condition. A reproducible defect report is a
successful deliverable when all evidence and completeness requirements are satisfied.
