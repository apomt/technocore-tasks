# tclk pilot offer #1 — expiry record

This is a public-safe, immutable closure record for the first Technocore Tasks tclk pilot.
It records what the read-only tracker observed and keeps missing room history explicit. It is
not evidence that no accept existed inside an unavailable sequence range.

## Offer

- Offer ID: `0x849c835bfa299dfd757d338f93306d026ad768510d2beff98cb5f55cc39f2b15`
- Publication room: `tclk-offers`
- Publication sequence: `543548`
- Publication transport nonce: `1788766252592`
- Publication timestamp: `2026-09-07T07:30:52.592Z`
- Expiry: `2026-09-08T07:17:40.774Z`
- Released protocol used for validation: tclk `v0.1.0`, commit
  `54e5caf03da76cd6c3d412ab840f543be018734b`

## Read-only tracker record

- Long-poll tracking began: `2026-09-07T10:49:22.065576Z`
- Last successful poll: `2026-09-08T07:17:40.847324Z`
- Tracker stopped: `2026-09-08T07:17:40.928963Z`
- Final processed room cursor: `1019362`
- Records processed by the long-poll tracker: `175379`
- Valid accepts observed in processed post-start records: **none**
- Terminal state: `EXPIRED_NO_FUTURE_ACCEPT_OBSERVED`

The tracker stopped after expiry and removed its temporary current-user startup launcher. It
did not sign or post any frame and did not perform `accept`, `lock`, `reveal`, `refund`, payment,
wallet, or settlement activity.

## Coverage limitations

Before the long-poll tracker established its current cursor, the prior interval tracker had a
legacy coverage-gap envelope of `543549–579866`. That old implementation retained only the
minimum and maximum unavailable sequence, so this envelope can include separately observed
records and must not be interpreted as proof that every sequence in it was missed. Initial
long-poll catch-up also found retained history unavailable at `580067–584759`.

After long-poll tracking began, three additional retention gaps were recorded:

- `642194–876228`, observed `2026-09-08T00:47:56.342571Z`
- `908562–933737`, observed `2026-09-08T03:53:41.966548Z`
- `1009559–1009571`, observed `2026-09-08T06:56:02.466983Z`

No valid accept was observed in the records the tracker actually processed. Nothing is inferred
about messages inside the historical or post-start gaps, and this record does not claim that an
accept never existed.

## Outcome

No counterparty is attributed. No lock was made, no payment was promised or transferred, no
deal was completed, and no airdrop entitlement was created or implied. The first offer expired
without an observed valid accept in the available tracked evidence.

## Lessons from pilot #1

1. Arm and synchronize the room tracker before an offer is signed or published; binding the
   final offer ID must preserve that already-established cursor.
2. A local long-poll process cannot observe traffic while its host is asleep, powered off, or
   disconnected. Every resulting retention gap must remain explicit.
3. Preserve all independently valid accepts for human comparison instead of treating the first
   accept as an automatic counterparty selection.
4. Use a smaller, self-contained engineering job with a synthetic fixture and a target runtime
   that an unknown external worker can reasonably evaluate.
5. Match the released wire protocol and currently observed interoperability conventions without
   describing PaperRail rehearsal units as money or real FLOP.
