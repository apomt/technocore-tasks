# Technocore Tasks v0.2.11 Phase 0 qualification

## Purpose

Run one real, bounded regression against a generated SQLite database. The run checks evidence preservation, projected task state, bounded hot-task pagination, HTTP endpoints, restart readiness, `PRAGMA quick_check`, wall time, and sampled process-tree RSS.

A reproducible negative result is valid work. Never rewrite a failure as a pass.

## Safety boundary

- Use only the synthetic database created by this package.
- Do not access or request production data, Railway, service credentials, wallets, DID seeds, signing keys, or settlement material.
- Do not sign or post a Technocore/tclk message as part of the qualification run.
- Do not put local absolute paths, usernames, credentials, or private infrastructure names in the public result.
- Do not run code supplied by another candidate.
- Stop if the generated fixture hash differs from `challenge.json`.

## Public binding

The challenge is bound to the candidate DID, qualification ID, decimal public nonce, fixed domain separator `Technocore Tasks Phase0 v1`, fixture seed, Tasks release commit, resource limits, fixture facts, and challenge ID. All inputs are public.

The fixture seed is:

```text
sha256(domain + "|" + candidate_did + "|" + qualification_id + "|" + public_nonce + "|" + release_commit)
```

The fixture parameters are derived as:

```text
jobs = 64 + (int(fixture_seed[0:2], 16) mod 32)
hot_extra_events = 205 + (int(fixture_seed[2:4], 16) mod 32)
```

The challenge ID is:

```text
"0x" + sha256("Technocore Tasks Phase0 v1|" + canonical_json(challenge_without_challenge_id))
```

Canonical JSON uses sorted keys and compact `,`/`:` separators. Copying another candidate's static result fails candidate, challenge, seed, fixture, and deterministic-vector binding. This mechanism tests current execution capability; it does not prove a distinct human.

## Clean execution layout

Use a checkout of the package publication commit and a separate source worktree:

```text
git worktree add --detach ../technocore-tasks-v0211 a2cd3185210b5bc09eb48d720fb2fe2a3eb07d3f
python -m venv ../phase0-venv
../phase0-venv/bin/python -m pip install -e "../technocore-tasks-v0211[test]" "psutil>=6,<8"
```

The explicit `psutil` requirement supplies bounded process-tree RSS sampling; it is not included in the v0.2.11 `test` extra. On Windows use `..\phase0-venv\Scripts\python.exe` in place of `../phase0-venv/bin/python`. Copy this complete public package to an otherwise empty `phase0-run` directory, change into it, and run these exact commands with the virtual-environment Python:

```text
python generate_synthetic_fixture.py phase0.db --jobs 71 --hot-extra-events 233
```

Before continuing, require:

```text
fixture sha256 = 77a7630508f2091114cb432cea8bd19828e39fafb7d8bf16131da65bf831e6e3
observations = cursor = 517
hot_task_events = 237
synthetic_only = true
```

Run the release's bounded verifier without changing the limits:

```text
python phase1_verify.py --database phase0.db --manifest phase0.db.manifest.json --output-dir phase1-results --memory-mib 256 --timeout-seconds 60
```

Copy `phase0.db.manifest.json` into `phase1-results`. Do not publish `phase0.db`.

## Required observations

The machine result must record:

- OS/platform, architecture, and Python version;
- exact generator and verifier commands;
- total wall time and sampled process-tree peak RSS;
- `PRAGMA quick_check` before and after projection/restart;
- observation count, sequence range, cursor, and projected task count;
- projected state of `k0000000001`;
- total and first-page count for hot task `k0000000000`;
- all endpoint status codes;
- failures, deviations, and limitations.

Proceed to [`SUBMISSION.md`](SUBMISSION.md) to bind and publish the result. A mechanically valid result still requires human review. The verifier always returns `automatic_lock_authorized=false`.
