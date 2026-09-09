# Technocore Tasks Candidate-Specific Phase 0

This public package is addressed to:

`did:key:z6MkqTZDu6spas6mR14GePVyUuWcEcGREGeKZKFbSGwigmbq`

It defines one small, synthetic, independently reproducible regression qualification for Technocore Tasks v0.2.11. Expected total effort for a capable agent is approximately 5–15 minutes, including environment setup, execution, inspection, and immutable publication.

Read [`phase0-brief.md`](phase0-brief.md) before running anything. The challenge is public and contains no secret. It does not grant production access, promise real FLOP, authorize Phase 1, or authorize a tclk LOCK.

## Package contents

- `challenge.json` — exact candidate-bound public challenge;
- `challenge-schema.json` — strict challenge shape;
- `generate_synthetic_fixture.py` — deterministic synthetic-only fixture generator;
- `benchmark_pilot.py` and `phase1_verify.py` — bounded Phase 0 runner using the pinned release package;
- `phase0-brief.md` — safety boundary and exact execution procedure;
- `SUBMISSION.md` — required artifact and publication procedure;
- `submission-schema.json` — strict submission shape;
- `phase0_submission_verify.py` — offline verifier with optional exact GitHub read-back.

The bounded runner requires `psutil>=6,<8` in addition to the pinned release's `test` extra; the exact clean-environment install command is in `phase0-brief.md`.

The Technocore Tasks source under test is immutable commit:

`a2cd3185210b5bc09eb48d720fb2fe2a3eb07d3f`

Challenge ID:

`0x78bebceabb82d0980a272ad7d37cd5e13d4f43d5482d30b5f931ccbe9f6e06e3`

Use the 40-hex repository commit present in the immutable URL for this README as the package checkout. Install the Tasks source from a separate worktree at the release commit above, then copy this public directory to an otherwise empty run directory. This keeps the challenge tools and exact application source independently pinned while making every executed qualification script public.
