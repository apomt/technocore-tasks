# tclk pilot offer #2 plan

## Decision state

This is a public, unsigned planning artifact. It authorizes no signature, POST, accept, lock,
reveal, refund, wallet connection, or value movement. The exact offer ID and absolute deadlines do
not exist until a human approves a fresh build.

The offer uses released tclk `v0.1.0` at commit
`54e5caf03da76cd6c3d412ab840f543be018734b`. Newer unreleased `main`, open pull requests, and
issues are not live protocol authority.

## Fixed job

The real job is the bounded Technocore Tasks v0.2.11 Phase 1 independent regression check at:

<https://github.com/apomt/technocore-tasks/blob/63681bbe959b80f05d12a84f32c49a2e5ab26cc5/docs/tclk-pilot/phase1-worker-brief.md>

It uses a newly generated 25,000-task, 100,500-observation synthetic fixture and exercises actual
migration, projection, bounded 200-event evidence pagination, persistence, cursor invariants,
HTTP reads, `PRAGMA quick_check`, latency, and process-tree RSS. Reference execution was about
25.5 seconds; the 30–60 minute allowance includes setup, review, reporting, and publishing.
A reproducible negative result is valid.

## Interoperability choice

A bounded retained-room sample of 200 current records contained 21 valid offers. Nineteen named
asset `FLOP`, all 21 included rail `paper`, 14 used `proto=a2a`, and amount `200` was the most common
FLOP amount (11 of 19). At least one comparable `FLOP / 200 / paper / a2a` offer had a matched
accept in the retained sample. The sample was bursty and right-censored, so these observations are
directional, not guarantees.

Offer #2 therefore fixes:

- asset: `FLOP`
- amount: `200`
- rail: `paper`
- proto: `a2a`
- role: `payer`
- lock: `hash`

`FLOP 200` here is a symbolic PaperRail rehearsal amount. It is **not real FLOP payment**. No
token transfer occurs, no monetary payment is promised, and no airdrop entitlement is implied.
The amount is chosen for observed wire-format interoperability only.

## Relative windows

- offer expiry: 18 hours after creation
- work claim deadline: 42 hours after creation
- refund opening: 48 hours after creation

The 18-hour publication window spans time zones without leaving an obsolete offer open for days.
The worker then has at least 24 hours after the last possible accept to finish a job expected to
take 30–60 minutes. The six-hour gap between claim deadline and refund opening preserves ordering.
Absolute timestamps must be generated only at the approved signing session.

## Tracking order and candidates

The FLOP Testnet Ops read-only tracker must be running, current, and gap-free after initial sync
before the packet is built. It must then bind the exact unsigned offer without resetting its room
cursor. Signing and POST remain later human actions.

Every independently valid accept referencing the exact offer is retained through expiry for human
review. No candidate is selected automatically, and no first-seen candidate receives preference.
The tracker has no remote write or LOCK path. Do not self-accept or use another DID controlled by
the builder.
