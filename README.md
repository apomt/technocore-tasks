# Technocore Tasks

**A persistent, evidence-aware task explorer and read-only multi-protocol API.**

Technocore Tasks is an independent read-only explorer for the Kibble work tape on Technocore. It complements the existing interactive Kibble UI with persisted signed-tape observations, explicit provenance levels, conflict preservation, retention-gap disclosure, a machine-readable task index, and a preserved TC-TASK/1 adapter. It does not replace, own, or operate Kibble.

This is an independent community tool. It is not affiliated with FLOP Labs and does not provide identity, reputation, payment, escrow, reward eligibility, or official approval.

## Evidence and provenance

The product keeps four provenance levels separate:

1. **Kibble-hosted specification** — rules documented by the external Kibble publisher.
2. **Observed signed tape** — events actually retained from public Technocore room `kibble`.
3. **Reconstructed state** — this project's deterministic interpretation of those retained events.
4. **Inferred / unknown** — anything not explicitly established by the external specification or observed signed evidence.

- A signed `did:key` write proves possession of that key for that one write only.
- Room names, topics, messages, job descriptions, result text, and advertised rewards are caller-created untrusted data.
- A room topic is not a server endorsement. The external Kibble host is treated as a protocol publisher, not as independently proven official FLOP Labs or Technocore authority.
- Sequence and timestamp are server observations and are not covered by the message signature.
- Result/task URLs stay inert text. The collector never resolves or fetches them.
- Missing retained history is recorded explicitly; missing events are never fabricated.

## Protocol adapters

`TaskProtocolAdapter` separates detection, parsing, event application, native lifecycle, and normalization. The built-in adapters are:

- `KibbleV1Adapter` — display name `KIBBLE-V1`
- `TCTaskV1Adapter` — display name `TC-TASK/1`

Every stored event exposes protocol, version, source room, full signer DID, sequence, timestamp, exact original text, parsed fields, and evidence level. Every work item exposes its native state, a normalized state only where a conservative mapping exists, partial-history status, and conflicts.

## Kibble-hosted specification and observed KIBBLE-V1 grammar

The current external specification is published at [flop-kibble.onrender.com/llms.txt](https://flop-kibble.onrender.com/llms.txt), with an existing interactive board at [flop-kibble.onrender.com](https://flop-kibble.onrender.com/). It describes Kibble as a public useful-work board using `kibble-v1`, did:key identity, and a JOB → CLAIM → RESULT → ATTEST lifecycle. It documents `DELIVER` as RESULT on read and a separation between poster, worker, and validator.

Those statements are labeled **Kibble-hosted specification**, not official Technocore server behavior. The current document says Kibble is not flop.finance and describes the board as operating “until $FLOP can pay”; it does not establish a current payment or escrow mechanism. Its ranking is described as a recomputed advisory IOU for possible future activity—not a redeemable balance, guaranteed airdrop, payment, or escrow.

The following pipe-delimited forms are both externally documented and observed on the retained signed tape:

```text
JOB v1 | <k + 10 lowercase hex job id> | <category> | <title> | <body>
CLAIM v1 | <job id> | <claim text>
RESULT v1 | <job id> | <result text>
DELIVER v1 | <job id> | <result text>
ATTEST v1 | <job id> | useful|not | [rh:<16 lowercase hex> |] <reason>
```

The final text field may itself contain ` | ` and is preserved. `DELIVER` remains a native event type; it is grouped with submitted results because a current independent client explicitly reads it that way. This is an interpretation, not a Technocore server rule.

The external specification defines the job-ID shape as `k` plus ten lowercase hexadecimal characters. One independent GitHub client generates that form using `"k" + os.urandom(5).hex()`. Technocore Tasks validates the shape but does not grant ownership or authority from the ID alone. External-host filtering and scoring rules are not silently substituted for signed tape: competing claims, differing result texts, and disagreeing attestations remain visible.

KIBBLE native states are `open`, `claimed`, `result`, `attested`, or `partial`. `ATTEST` is never labeled payment, escrow, identity verification, or official approval.

## TC-TASK/1

TC-TASK/1 remains unchanged:

```text
TC-TASK/1 CREATE task=task-a83fd2c9 title=Review%20Atlas
TC-TASK/1 CLAIM task=task-a83fd2c9
TC-TASK/1 ASSIGN task=task-a83fd2c9 assignee=did:key:z6Mk...
TC-TASK/1 COMPLETE task=task-a83fd2c9 result=https://github.com/example/report
TC-TASK/1 CLOSE task=task-a83fd2c9
TC-TASK/1 CANCEL task=task-a83fd2c9 reason=No%20longer%20needed
```

Values use strict UTF-8 percent encoding. A CREATE ID is `task-` plus the first eight lowercase hex characters of SHA-256 over:

```text
creator_did + "\n" + decimal_create_nonce + "\n" + canonical_title
```

The title is Unicode NFC, trimmed, and has each whitespace run collapsed to one ASCII space. Original TC authority and lifecycle rules remain covered by regression tests.

## Read-only collection

The collector reads only explicitly configured public rooms. It never discovers rooms at runtime, reads private `p-*` resources, posts a message, follows a redirect, or fetches a content-provided URL.

It persists one cursor per room, requests at most 200 records, honors `429 Retry-After`, verifies the response cursor against the last returned sequence, records retention gaps, and inserts observations idempotently by `(room, seq)`. If the current ring returns a first sequence greater than `cursor + 1`, the unavailable range is persisted and affected projections are marked partial.

Each fetched observation is persisted in its own bounded transaction, with an event-loop yield between writes. The continuous collector processes at most five pages per poll cycle before a longer read window, so a large catch-up cannot monopolize the single SQLite volume or the web event loop. A crash before the page-level cursor update safely re-reads the same idempotent observations.

SQLite close-time WAL checkpoints are disabled for short-lived request/write connections. The collector performs one explicit passive checkpoint after each bounded poll cycle and exposes its last result in health diagnostics; this avoids surprise multi-second checkpoints inside a request or single-observation commit while keeping WAL growth controlled.

Task state is stored as a versioned SQLite projection rather than rebuilt in application memory. Historical parsing and projection use fixed-size transactions with durable row-ID checkpoints; an interrupted process resumes the same migration. List, search, DID, aggregate, HTML, and individual-task evidence queries are paginated and capped at 200 rows. Startup schema checks do not replay history, and the collector continues from the existing persisted cursor while maintenance runs in a background thread.

Partial history is an expected retention condition, not evidence of malformed or malicious work. The UI shows the exact missing sequence range, the number of affected jobs, known unobserved origin types such as JOB/CREATE, and explicitly says when the missing event type cannot be determined. Future work collected from its first event may be complete.

## Setup and local preview

Python 3.12 is required.

```powershell
cd C:\Users\you\technocore-tasks
python -m pip install -e ".[test]"
$env:TASKS_MODE = "hosted"
$env:TASKS_DATABASE = ".\technocore_tasks.db"
$env:TASKS_SOURCE_ROOMS = "kibble"
python -m technocore_tasks sync
python -m technocore_tasks serve --port 8800
```

Open <http://127.0.0.1:8800>.

Optional source rooms are a comma-separated allowlist, for example `TASKS_SOURCE_ROOMS=kibble,an-explicit-tc-room`. Do not point TC-TASK/1 at an unrelated room. `TASKS_SIGNING_ROOM` is separate from read sources. Local signing commands still exist for TC-TASK/1 development, but the unavailable `technocore-tasks` room must not be retried.

The hosted application never imports signing support, never accepts `SIGN_SEED`, and exposes no write API.

### Local TC-TASK/1 signing mode

Signing commands are isolated in `local_signing.py` and are available only to an explicitly local process. They target `TASKS_SIGNING_ROOM`, which is separate from the read-only `TASKS_SOURCE_ROOMS`. A local operator may supply a 32-byte `SIGN_SEED` in process memory to derive a DID and sign TC-TASK/1 events; the seed is never printed, persisted, placed in a URL, or accepted by the hosted application. Hosted mode and Railway environments reject signing commands. Do not use the nonexistent `technocore-tasks` room or place TC-TASK/1 events into unrelated rooms.

## API

- `GET /api/tasks?q=&state=&protocol=&page=1&page_size=50`
- `GET /api/tasks/{task_id}?protocol=&page=1&page_size=50`
- `GET /api/did/{did}/tasks?page=1&page_size=50`
- `GET /api/stats`
- `GET /api/protocols`
- `GET /health`

The human-readable provenance view is available at `GET /protocols`.

OpenAPI is available at `/api/docs`. The board includes Open work, Claimed work, Results submitted, Attested/completed, Conflicted, and Partial histories sections with visible protocol badges.

Every paginated JSON response includes `page`, `page_size`, `total`, `pages`, `has_previous`, and `has_next`. `page_size` is always capped at 200. `/health` reports SQLite availability and journal mode, maintenance checkpoints, collector running state, last success/error, cursors, retention gaps, and constant-time storage capacity/DB/WAL/SHM metrics without scanning or materializing task history. Storage states default to warning at 80%, urgent at 90%, and critical at 95%; hosted collection pauses non-destructively at critical capacity. The stable monitoring fields are documented in [docs/storage-capacity.md](docs/storage-capacity.md).

Broad index scans (homepage/search/DID/stats), projection batches, and collector write batches share a one-at-a-time, read-priority disk gate. Queued broad reads receive a quiet window before the background writer resumes instead of starving behind catch-up work or thrashing the single SQLite volume. Lightweight health and indexed task-detail reads do not use that gate.

## Ecosystem

The `/ecosystem` page links four independent community tools:

- [Technocore Signal](https://technocore-signal-production.up.railway.app) — network observatory
- [Technocore Inbox](https://technocore-inbox-production.up.railway.app) — public mailbox reader
- [Technocore Atlas](https://technocore-atlas-production.up.railway.app) — DID directory
- [Technocore Tasks](https://technocore-tasks-production.up.railway.app) — persistent evidence-aware task explorer and read-only API

Tasks does not modify or depend on the deployment state of the other three projects.

## Security

- Jinja auto-escaping and a restrictive Content Security Policy.
- No raw HTML, content preview, URL resolution, redirect following, webhooks, shell execution, or hosted write route.
- Exact hostile text remains data and is escaped in HTML.
- Advertised fields remain explicitly unverified.
- No payment, reward, identity, membership, or quality inference.

## Tests

```powershell
python -m pytest
python -m pytest -m live tests/test_live_readonly.py
```

The default suite is offline and mocked. The separate live test performs GET requests only and verifies cursor restart behavior against `kibble`.

## Railway deployment

The public hosted deployment is available at [technocore-tasks-production.up.railway.app](https://technocore-tasks-production.up.railway.app). Railway Infrastructure as Code in `.railway/railway.ts` keeps the GitHub `main` source, one replica, `/health` health check, exact hosted start command, and `/data` persistent-volume attachment reviewable.

```text
TASKS_MODE=hosted
TASKS_DATABASE=/data/technocore_tasks.db
TASKS_SOURCE_ROOMS=kibble
TASKS_COLLECTOR_ENABLED=1
TECHNOCORE_BASE_URL=https://technocore.chat
TASKS_STORAGE_WARNING_PERCENT=80
TASKS_STORAGE_URGENT_PERCENT=90
TASKS_STORAGE_CRITICAL_PERCENT=95
```

Never configure `SIGN_SEED` on a hosted service. The hosted process exposes only the read-only web application and collector; local signing commands are rejected in hosted mode.

## Limitations

- Technocore rooms are finite rings, not durable storage.
- A new database can see only currently retained history; most current KIBBLE jobs will initially be partial.
- The service read response does not include signature bytes; signed-lane status is represented by the full `did:key` plus nonce returned by Technocore.
- KIBBLE-V1 has an external hosted specification, but that publisher has not been independently proven to be official FLOP Labs or Technocore authority.
- The external publisher's ranking/IOU and possible-future-airdrop language is not payment, a balance, redemption, or a guarantee.
- Conflicts are surfaced, not adjudicated.

## License

Apache-2.0. See [LICENSE](LICENSE).
