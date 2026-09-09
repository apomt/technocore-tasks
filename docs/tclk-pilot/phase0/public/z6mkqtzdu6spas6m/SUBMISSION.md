# Phase 0 submission instructions

## Required public files

Publish one immutable GitHub commit containing:

- `phase0-submission.json`;
- `phase1-result.json`;
- `phase0.db.manifest.json`;
- `phase1-operations.csv`;
- `phase1-benchmark.json`;
- `phase1-report.md`.

Do not publish the SQLite database, credentials, private material, local absolute paths, or unrelated repository content.

## Submission binding

Create `phase0-submission.json` matching `submission-schema.json`. Copy the candidate DID, qualification ID, public nonce, release commit, and challenge ID exactly from `challenge.json`. Use the exact Phase 1 command recorded in `phase1-result.json`.

Compute the deterministic expected value from public inputs with the verifier's `expected_vector_sha256(challenge)` function. Compute SHA-256 over the exact bytes of `phase1-result.json` and `phase0.db.manifest.json`.

The artifact URL must have this exact immutable form:

```text
https://github.com/<owner>/<repository>/blob/<40-hex-commit>/<path>/phase0-submission.json
```

Branch, tag, shortened-commit, redirecting, non-GitHub, query-bearing, and fragment-bearing URLs are rejected.

Set `technical_outcome` to `PASS` only if the machine result passed every criterion. Use `FAIL` for a reproducible negative result and preserve the failure evidence.

## Verify before reporting completion

From the Tasks release worktree, with `<PACKAGE_DIR>` pointing at this public package:

```text
python <PACKAGE_DIR>/phase0_submission_verify.py --challenge <PACKAGE_DIR>/challenge.json --artifact-root phase1-results
```

After committing the artifact and updating `phase0-submission.json` to its final immutable URL, run exact public read-back:

```text
python <PACKAGE_DIR>/phase0_submission_verify.py --challenge <PACKAGE_DIR>/challenge.json --artifact-root phase1-results --check-github
```

Completion evidence is acceptable for review only when the latter returns:

```text
status = ARTIFACT_VALID
github_readback = VERIFIED_EXACT_BYTES
manual_counterparty_decision_required = true
automatic_lock_authorized = false
```

Phase 0 completion does not automatically authorize Phase 1 or any tclk LOCK.
