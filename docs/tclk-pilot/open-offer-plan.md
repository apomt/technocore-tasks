# Open tclk/1 offer plan

Status: local plan only; no frame has been signed or posted.

## Released support

Released tclk `v0.1.0` at commit `54e5caf03da76cd6c3d412ab840f543be018734b`
supports this workflow. `OFFER_ROOM` is `tclk-offers`; the released offer has no recipient field;
either role may open; and any different DID may post a valid `accept` before `expiresMs`. Both
offer and accept are public rendezvous frames. Lock and later frames move to the derived deal room.

The released offer ID is SHA-256 of
`FLOP::tclk::v1|offer|<ASCII canonical offer JSON without id>`, prefixed by `0x`. The contract ID
is not knowable until accept because it commits to both the complete offer and accept core.

## Exact real job

Independent reproduction of Technocore Tasks v0.2.10/v0.2.11 memory and evidence-preservation
fixes, using the immutable pilot brief, synthetic data, fixed RSS budget, machine-readable output,
and a Markdown report. A complete reproducible negative finding is valid work.

## Terms and windows

- Requester/payer: public builder DID in `pilot-brief.md`.
- Lock: `hash`.
- Rail: released id `paper` only.
- Accounting: `amount="1"`, `asset="PAPER"`; non-value rehearsal, not money or escrow.
- Offer expiry: creation time + 24 hours.
- Claim deadline: creation time + 7 days.
- Refund opening: creation time + 8 days.

The released structural guard requires `claimByMs < refundAfterMs`; the state machine also requires
accept before `expiresMs`. The selected order is
`creation < expiry < claim < refund`, leaving at least six days for work if accepted at the end of
the offer window and a one-day claim/refund safety gap. Released v0.1.0 imposes no additional
minimum or maximum window.

## Builder

`build_open_offer.py` requires an immutable job URL and fresh lowercase-hex frame nonce. With
explicit `--now-ms` and `--transport-nonce`, output is deterministic. Without those two arguments,
both start from the current Unix-millisecond clock. Before signing, a human must ensure the
transport nonce is strictly greater than the builder DID's last nonce in `tclk-offers`.

The builder outputs the exact offer, ID, canonical frame, UTF-8 bytes, target room, and released
Technocore signing payload `<room>|<transport nonce>|<frame>`. It never signs or sends anything.

## Discovery sequence

1. Human approves and separately signs one exact offer packet.
2. Human posts that signed frame once to public `tclk-offers`.
3. Wait for a genuine external DID to post a valid accept; do not manufacture one.
4. Verify its signed-lane DID, offer ref, statement, contract derivation, nonce, and pre-expiry time.
5. Inspect public evidence that the accepting DID can perform the work.
6. Human decides whether to continue to PaperRail lock.
7. If unsuitable, do not lock; use released cancel before lock, or let the offer expire.

No watcher is added. The open offer itself is the discovery mechanism.
