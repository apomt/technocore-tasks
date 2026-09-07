# Future human signing checkpoint

No signing or posting is authorized by this document. Never provide a real DID seed, wallet key,
seed phrase, or settlement preimage to Codex/AI.

## Packet generation

Immediately before the human decision, run `build_open_offer.py` outside any signer and provide:

```powershell
python .\docs\tclk-pilot\build_open_offer.py `
  --context-url "<IMMUTABLE_PILOT_BRIEF_URL>" `
  --frame-nonce "<FRESH_RANDOM_LOWERCASE_HEX>" `
  --now-ms <CURRENT_UNIX_MS> `
  --transport-nonce <FRESH_MONOTONIC_ROOM_NONCE> `
  --output .\unsigned-signing-packet.json
```

The packet must name released tclk `v0.1.0`, commit
`54e5caf03da76cd6c3d412ab840f543be018734b`, room `tclk-offers`, rail `paper`, amount
`1`, asset `PAPER`, and the approved immutable brief. It includes the exact canonical frame,
UTF-8 hex bytes, derived offer ID, deadlines, and the exact transport signing payload.

## Human checks before isolated signing

1. Re-fetch the immutable brief URL and confirm HTTP 200 and its commit.
2. Confirm `from` is the builder's public DID and there is no recipient/counterparty field.
3. Confirm the offer ID independently from the canonical offer fields without `id`.
4. Decode the `tclk1 ` frame with released v0.1.0 and require exact encode/decode round-trip.
5. Confirm `now < expiresMs < claimByMs < refundAfterMs` and the intended 24h/7d/8d windows.
6. Confirm frame nonce freshness and that the transport nonce exceeds the last builder-DID nonce
   observed in `tclk-offers`.
7. Confirm the signing bytes are exactly UTF-8 of
   `tclk-offers|<transport_nonce>|<canonical tclk1 frame>`.
8. Confirm expected public effect: exactly one public offer; no acceptance, deal, lock, money, or
   entitlement follows from posting it.

## Isolation boundary

The signer must be a separate, human-controlled process with no Codex/API read path to the key. It
may accept only the displayed byte string and return only the public DID/signature envelope. It
must not expose key material, read arbitrary files/environment values, accept shell commands, or
reuse approval for a later frame. A human must separately review the resulting
`{did,sig,nonce,text}` POST body before any manual publication.
