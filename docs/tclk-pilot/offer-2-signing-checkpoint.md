# Offer #2 signing checkpoint

Stop here unless a human explicitly answers **yes** to “Do we publish offer #2?” This checklist is
not authorization to sign or POST.

## Before creating time-sensitive fields

1. Reconfirm the newest actually released tclk version is still `v0.1.0` and the pinned commit is
   `54e5caf03da76cd6c3d412ab840f543be018734b`. Stop for review if a newer release exists.
2. Confirm the immutable Phase 1 brief URL returns the intended commit and content.
3. Confirm the FLOP Testnet Ops offer #2 tracker is running in `PENDING`, has a recent successful
   poll, has remained ready at least 20 seconds, and has no future gap since arming. An initial
   catch-up gap before the tracker became current is not offer coverage loss because no offer had
   yet been posted.
4. Review the fixed terms and PaperRail notice in `offer-2-template.json`.

## Build and bind (still unsigned)

1. Outside Codex, generate a fresh random lowercase-hex frame nonce, choose the current creation
   time in milliseconds, and choose a transport nonce valid for the builder DID.
2. Run `build_offer2.py` with explicit `--frame-nonce`, `--now-ms`, `--transport-nonce`, and a new
   `--output` path. The builder refuses to overwrite a file.
3. Review the exact offer, offer ID, deadlines, immutable context URL, canonical frame, and signing
   payload. Confirm the packet says `UNSIGNED_DO_NOT_POST`.
4. Bind that exact packet to the already-running tracker. Confirm state changes to `BOUND` while
   the persisted cursor does not change.

## Human-only boundary

Only after those checks may a human independently choose whether to use an isolated signer and
POST exactly one frame. Never provide a DID seed, private key, wallet seed, wallet key, or
settlement preimage to Codex, a repository, a tracker, a shell transcript, or the public room.

After POST, record the returned room sequence and continue read-only tracking. Preserve every valid
accept candidate for human comparison; do not auto-select, LOCK, reveal, refund, connect a wallet,
or infer real value from PaperRail.
