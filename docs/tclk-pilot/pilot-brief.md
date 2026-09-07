# Unsigned tclk pilot brief

Status: sanitized for publication as a repository artifact; no tclk frame has been signed, posted,
offered, accepted, or executed.

Retrieved at `2026-09-07T06:38:55.7979976Z`.

## Pinned tclk reality

### RELEASED

- Latest GitHub release and npm version: [`v0.1.0`](https://github.com/flop-labs/tclk/releases/tag/v0.1.0), published 2026-09-01.
- Release commit: [`54e5caf03da76cd6c3d412ab840f543be018734b`](https://github.com/flop-labs/tclk/commit/54e5caf03da76cd6c3d412ab840f543be018734b).
- Released normative protocol: `tclk/1`, `SPEC.md` blob `91c726973d1b452f9b27edf605680f52a4eff685`.
- Published packages: `@flop-labs/tclk@0.1.0` and `@flop-labs/tclk-mcp@0.1.0`.
- The release is alpha/testnet-only. Its shipped `PaperRail` holds no value, is not escrow,
  and only records a rehearsal lifecycle in world-writable notes.

### UNRELEASED MAIN

- Current `main`: [`5cc4ab93efbc8999a3a7e1471b639deca25998ea`](https://github.com/flop-labs/tclk/commit/5cc4ab93efbc8999a3a7e1471b639deca25998ea), dated 2026-09-03.
- Current `SPEC.md`: `tclk/1`, blob `99e3e677295354b88fe49efa69f84b1b78a1036c`.
- `main` is 21 commits ahead of `v0.1.0`. Its unreleased changes include authenticated complete
  transcript records, venue-time folding, room-binding checks, heartbeat frames, a generated
  frame schema/rail registry, hosted no-custody MCP documentation, exact string nonces, and
  numerous fail-closed validation corrections.
- None of those differences is claimed to exist in the released npm packages.
- `SECURITY.md` on main still says nothing has been published and only main is supported; this
  conflicts with the official v0.1.0 GitHub release and npm metadata and should be treated as a
  documentation inconsistency, not as evidence of another release.

### OPEN PR

Open PRs are proposals only. Relevant examples at retrieval time include #126 (room-epoch spec
correction), #119 (document release-versus-main gaps), #105 (portable golden vectors), #97
(timestamp/sequence trust and gaps), and #28/#13 (Python examples). No proposed behavior is used
as a pilot requirement.

### ISSUE / COMMUNITY OBSERVATION

Issues #93 and #96 question transcript completeness and venue-time trust; #61 reports a live room-
binding mismatch; #113 reports mostly PaperRail activity and no observed point-lock exercise.
These are unverified engineering reports, not released features or protocol authority.

## The real engineering job

Title: **Independent reproduction of Technocore Tasks v0.2.10/v0.2.11 memory and
evidence-preservation fixes**

Builder public identifier: `did:key:z6MkimcfTzAFj18jNxxYEWenqwr59AEPCWYhvG4qC5WdzrXY`.

An independent counterparty will use only local synthetic fixtures to:

1. Reproduce the v0.1.0 whole-history scaling failure under a documented 3,072 MiB RSS budget.
2. Run v0.2.10 or the superseding v0.2.11 under the identical budget and dataset.
3. Record peak process-tree RSS and latency for startup, homepage, search, stats, task detail,
   and JSON task detail.
4. Verify the 200-event task-evidence bound and pagination metadata.
5. Verify deterministic task state, observation count, cursor, projection readiness, and restart
   persistence.
6. Describe the cold-cache broad-read limitation without hiding timeouts or failures.
7. Publish reproducible evidence even if it disproves or qualifies the repair.

The counterparty must not load-test public Technocore or the Railway deployment. No production
database, logs, secrets, credentials, private infrastructure data, or wallet material is supplied.

## Separation of concerns

- **Engineering work:** the independent benchmark and correctness audit described above.
- **tclk contract/transcript:** only a future signed coordination record binding the parties to an
  immutable brief and deliverable URL.
- **Settlement:** PaperRail rehearsal accounting only. No real money, escrow, guaranteed payment,
  or value transfer.
- **Quality verification:** human/independent review of commands, raw benchmark files, invariants,
  and findings. A syntactically valid tclk transcript does not establish engineering quality.
