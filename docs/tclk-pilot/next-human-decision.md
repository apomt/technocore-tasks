# Next human decision

Publication of the sanitized reproduction package is authorized. Publication is not authorization
to sign or post a tclk frame.

After the immutable pilot URL is recorded, the next human decision is whether to generate and
approve one current unsigned packet for isolated signing and manual publication to `tclk-offers`.
No known counterparty is required for an open offer; any accepting DID must be a genuine external
party and must be assessed only after a valid accept appears.

Before any future offer, a human must approve all of the following together:

- the immutable public job-brief URL and SHA-256;
- the selected counterparty DID and concrete evidence linking that DID to relevant work;
- exact `amount="1"`, `asset="PAPER"` non-value rehearsal terms;
- expiry, claim, and refund timestamps with an adequate review window;
- the exact canonical offer payload and derived ID;
- the quality reviewer and acceptance procedure;
- the archive destinations;
- a separate signing mechanism meeting the isolation rules below.

## Mandatory private-key boundary

Codex/AI must have no API, command, environment-variable access, file-read access, logging access,
or debugging interface capable of retrieving the DID private seed. Do not install a signer in this
runtime.

A future signer must be a separately controlled human-approved component that:

1. accepts only one bounded canonical signing payload plus an explicit public room and nonce;
2. displays those exact bytes and derived public DID for human confirmation;
3. refuses arbitrary shell commands, paths, URLs, environment reads, and file reads;
4. never returns, logs, exports, or persists the seed;
5. returns only the signature/public envelope needed for the reviewed payload;
6. requires a fresh human approval for each subsequent tclk frame.

No secret/preimage may be exposed to AI before the released protocol permits reveal. No wallet is
needed because PaperRail moves no value.
