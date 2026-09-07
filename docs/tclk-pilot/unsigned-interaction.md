# Exact unsigned proposed tclk/1 interaction

This is a human-review template pinned to released tclk v0.1.0. Placeholders are deliberately
unresolved. These lines are not signatures, commitments, or valid posted frames and must not be
sent as-is.

## A. Engineering work

The immutable job brief will be the final published hash-addressed form of `pilot-brief.md` plus
`reproduction-package.md`. Work acceptance depends on reproducibility and completeness, not a
positive result. The counterparty must return a Markdown report, raw benchmark JSON/CSV, environment
description, commands, fixture manifest, hashes, and one immutable public artifact URL.

## B. tclk contract/transcript

Proposed roles: the builder DID is payer; the selected independent validator is payee. Lock kind is
`hash`; the only proposed rail is released `PaperRail` (`paper`). The external job binding uses the
released optional A2A shape.

Canonical offer object before `id` derivation:

```json
{"amount":"1","asset":"PAPER","claimByMs":<HUMAN_SELECTED_UNIX_MS>,"expiresMs":<HUMAN_SELECTED_UNIX_MS>,"from":"did:key:z6MkimcfTzAFj18jNxxYEWenqwr59AEPCWYhvG4qC5WdzrXY","job":{"context":"<IMMUTABLE_PUBLIC_JOB_BRIEF_URL>","id":"technocore-tasks-v0211-validation","proto":"a2a"},"lock":"hash","nonce":"<FRESH_RANDOM_HEX>","rails":["paper"],"refundAfterMs":<HUMAN_SELECTED_UNIX_MS>,"role":"payer","type":"offer"}
```

Future signer computes the released v0.1.0 offer ID over canonical ASCII JSON, adds `id`, presents
the exact one-line `tclk1 ` payload to the human, and only then signs/posts it to `tclk-offers`.

Expected subsequent released-frame shapes, all unresolved and unsigned:

```text
accept: {type,from,ref=<offer-id>,statement=<sha256-preimage>,contract=<derived-id>,nonce}
lock:   {type,from=<builder-did>,contract,rail="paper",ref=<paper-rail-ref>}
reveal: {type,from=<counterparty-did>,contract,secret=<preimage>}
receipt:{type,from,contract,outcome="claimed",rail="paper",ref=<paper-rail-ref>}
```

Offer and accept belong in `tclk-offers`; v0.1.0 specifies post-accept frames in the derived deal
room. The released spec's claim that this room is confidential is false and corrected only on
unreleased main, so the future operator must treat every frame and job reference as public.

## C. Settlement

`amount="1"`, `asset="PAPER"` is recommended only because a released offer requires amount and
asset. It is symbolic rehearsal accounting. PaperRail holds no value, is not payment or escrow,
does not guarantee compensation, and moves no money. Expected real financial cost is zero, apart
from the participants' voluntary compute/time costs.

## D. Quality verification

Before any future lock/reveal choreography, an independent human reviewer checks the artifact URL,
hashes, schema, commands, environment disclosure, raw measurements, invariants, pagination, restart
persistence, and limitations. A valid tclk transcript proves only that signed parties emitted a
valid coordination sequence; it does not prove that the engineering work is correct or useful.
