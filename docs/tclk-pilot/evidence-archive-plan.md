# Durable evidence archive plan

Technocore room history and notes are not the durable record. After a future human-approved pilot,
create one immutable public archive containing:

1. The exact signed tclk JSONL export, preserving room, sequence, venue timestamp, sender DID,
   nonce, signature, and exact frame line.
2. Contract ID, builder DID, counterparty DID, offer ID, released tclk version/commit/SPEC blob,
   and explicit PaperRail non-value status.
3. The immutable job brief and its SHA-256.
4. Synthetic generator, benchmark harness, schema, fixture manifest, and exact commands.
5. Original delivered artifact, raw benchmark JSON/CSV, Markdown findings, environment inventory,
   stdout/stderr, and checksums.
6. Independent quality-review decision and reasons, including accepted defects and unresolved
   limitations.
7. Any Technocore Tasks issue/commit/release incorporating valid feedback, or an explicit statement
   that no product change followed.
8. A top-level `SHA256SUMS` plus immutable repository commit or release-asset URLs.

Archive the original bytes before rendering or transforming them. Verify the tclk export offline
against the pinned released rules and record every invalid/ignored line rather than deleting it.
Record that venue sequence/timestamps are venue metadata, not sender-signed facts. Never archive a
private seed, signing preimage before its permitted reveal, wallet material, credentials, production
database, or private infrastructure data.

Use at least two independent durable locations after completion: an immutable public source-control
release/commit and a separately checksummed operator copy. The room transcript may be cited, but it
must not be the only copy.
