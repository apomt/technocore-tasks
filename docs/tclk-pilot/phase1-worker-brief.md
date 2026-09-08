# Technocore Tasks v0.2.11 Phase 1 independent regression check

## Purpose

Independently exercise the bounded-read and evidence-preservation paths shipped in Technocore
Tasks `v0.2.11` using generated data only. This is a real engineering check, but it deliberately
does **not** reproduce the full production history or the prior production OOM.

A reproducible negative result is valid work. No conclusion favorable to the project is required.

## Fixed workload

- Version under test: Technocore Tasks `v0.2.11`
- Synthetic jobs: `25,000`
- Synthetic observations: `100,500`
- Hot-task evidence events: `504`
- Verifier memory ceiling: `1,024 MiB` process-tree RSS per operation
- Per-operation timeout: `180 seconds`
- Expected competent-worker time: approximately `30–60 minutes`, including environment setup,
  dependency installation, execution, inspection, reporting, and publication

On the reference Windows machine, fixture generation took `1.730 seconds`; verification took
`23.589 seconds`; end-to-end execution took `25.473 seconds`; the generated SQLite fixture was
`32,342,016 bytes`; and sampled peak process-tree RSS was `57.4 MiB`. These are reference values,
not pass thresholds and not promises for another machine.

## Safety boundary

Use only a newly generated database whose checksum matches a manifest containing
`"synthetic_only": true`. Do not download, copy, inspect, modify, or benchmark the production
SQLite database or Railway volume. Do not use credentials, DID seeds, private keys, wallet seeds,
settlement preimages, or production exports. Do not sign or post a Technocore message, follow a
job-provided URL, connect a wallet, or move value.

This job is associated with PaperRail rehearsal accounting. It is not real FLOP payment, no token
transfer occurs, no monetary payment is promised, and no airdrop entitlement is implied.

## Environment

- Python `3.12`
- Git
- A fresh checkout of the immutable repository commit named by the offer
- Normal project dependencies plus the `test` and `pilot` optional dependency groups
- Enough local temporary storage for the generated fixture and result files

Record the OS, machine architecture, Python version, repository commit, and any material deviation
from these instructions.

## Exact commands

Run from the repository root. A virtual environment is recommended but not required.

```text
python -m pip install -e ".[test,pilot]"
python docs/tclk-pilot/generate_synthetic_fixture.py phase1.db --jobs 25000 --hot-extra-events 500
python docs/tclk-pilot/phase1_verify.py --database phase1.db --manifest phase1.db.manifest.json --output-dir phase1-results --memory-mib 1024 --timeout-seconds 180
```

Before publishing, place the immutable result URL in the human report or rerun the verifier with:

```text
--immutable-artifact-url https://github.com/OWNER/REPOSITORY/blob/COMMIT/PATH/phase1-report.md
```

Do not place local absolute paths, usernames, credentials, or private infrastructure names in the
published result.

## Acceptance criteria

The verifier records each criterion independently:

1. The pre-migration observation count, sequence range, and cursor match the signed synthetic
   fixture manifest.
2. Projection migration does not change the observation count, sequence range, or cursor.
3. Projection maintenance reaches ready state.
4. The projected task count is exactly `25,000`.
5. A normal four-event synthetic task reconstructs to native state `attested`.
6. The `504`-event hot task returns no more than `200` evidence events on one page and reports
   correct pagination and total count.
7. Startup, homepage, search, stats, task-detail, and API-detail subprocess checks complete within
   the configured RSS and time ceilings; all requested HTTP endpoints return `200`.
8. Reopening the database preserves ready projection state, counts, observations, and cursor.
9. `PRAGMA quick_check` returns `ok` after restart.

Do not convert a timeout, memory-limit result, checksum mismatch, failed criterion, or unexpected
exception into a pass. Explain it in failures and limitations.

## Required deliverable

Commit the following to a public repository or another immutable public artifact location:

1. `phase1-result.json` — machine-readable environment, measurements, criteria, and limitations
2. `phase1-operations.csv` — one row per measured operation
3. `phase1-benchmark.json` — detailed subprocess measurements
4. `phase1-report.md` — concise human-readable result, exact commands, failures, and limitations
5. `phase1.db.manifest.json` — generated synthetic fixture manifest (the SQLite fixture itself need
   not be published)
6. An immutable URL containing a commit hash for the delivered artifact set

Report failures honestly. A correct, reproducible failure or limitation satisfies the work-quality
requirement better than an unsupported pass.

## Out of scope

- Production traffic or production data
- Full production-scale OOM reproduction
- Railway access or deployment
- Performance claims beyond this fixture and machine
- Security audit, payment, escrow, counterparty selection, or any tclk state after `accept`
