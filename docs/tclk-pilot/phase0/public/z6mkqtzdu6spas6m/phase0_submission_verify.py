"""Verify a Phase 0 qualification artifact without selecting or contacting a worker.

The verifier is deliberately incapable of signing, posting, locking, revealing,
refunding, or executing candidate-supplied code.  It reads JSON/text artifacts,
checks their binding to a locally approved public challenge, and can optionally
read back the exact submission JSON from a commit-pinned GitHub URL.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit


RELEASE_COMMIT = "a2cd3185210b5bc09eb48d720fb2fe2a3eb07d3f"
CHALLENGE_KIND = "technocore-tasks-phase0-challenge"
DID_RE = re.compile(r"did:key:z6Mk[1-9A-HJ-NP-Za-km-z]{44}\Z")
HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
HEX40_RE = re.compile(r"[0-9a-f]{40}\Z")
NONCE_RE = re.compile(r"[0-9]{1,19}\Z")
QUALIFICATION_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
GITHUB_PART_RE = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
MAX_JSON_BYTES = 256 * 1024
MAX_REMOTE_BYTES = 256 * 1024


class VerificationError(ValueError):
    """A stable, path-safe artifact verification failure."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise VerificationError(f"{label}_missing") from exc
    if size < 2 or size > MAX_JSON_BYTES:
        raise VerificationError(f"{label}_size_invalid")
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"{label}_json_invalid") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{label}_must_be_object")
    return value, raw


def require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise VerificationError(f"{label}_keys_invalid")


def require_int(value: Any, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise VerificationError(f"{label}_must_be_integer")
    if value < minimum or value > maximum:
        raise VerificationError(f"{label}_out_of_range")
    return value


def validate_challenge(challenge: dict[str, Any]) -> dict[str, Any]:
    require_exact_keys(
        challenge,
        {
            "schema_version",
            "kind",
            "candidate_did",
            "qualification_id",
            "public_nonce",
            "fixture_seed",
            "release_commit",
            "limits",
            "fixture",
            "challenge_id",
        },
        "challenge",
    )
    if challenge["schema_version"] != 1 or challenge["kind"] != CHALLENGE_KIND:
        raise VerificationError("challenge_version_invalid")
    if not isinstance(challenge["candidate_did"], str) or not DID_RE.fullmatch(
        challenge["candidate_did"]
    ):
        raise VerificationError("challenge_candidate_did_invalid")
    if not isinstance(challenge["qualification_id"], str) or not QUALIFICATION_RE.fullmatch(
        challenge["qualification_id"]
    ):
        raise VerificationError("challenge_qualification_id_invalid")
    if not isinstance(challenge["public_nonce"], str) or not NONCE_RE.fullmatch(
        challenge["public_nonce"]
    ):
        raise VerificationError("challenge_public_nonce_invalid")
    if not isinstance(challenge["fixture_seed"], str) or not HEX64_RE.fullmatch(
        challenge["fixture_seed"]
    ):
        raise VerificationError("challenge_fixture_seed_invalid")
    if challenge["release_commit"] != RELEASE_COMMIT:
        raise VerificationError("challenge_release_not_pinned")

    limits = challenge["limits"]
    if not isinstance(limits, dict):
        raise VerificationError("challenge_limits_invalid")
    require_exact_keys(limits, {"memory_mib", "timeout_seconds"}, "challenge_limits")
    require_int(limits["memory_mib"], 64, 1024, "challenge_memory_mib")
    require_int(limits["timeout_seconds"], 10, 180, "challenge_timeout_seconds")

    fixture = challenge["fixture"]
    if not isinstance(fixture, dict):
        raise VerificationError("challenge_fixture_invalid")
    require_exact_keys(
        fixture,
        {
            "filename",
            "synthetic_only",
            "sha256",
            "jobs",
            "observations",
            "cursor",
            "hot_task_id",
            "hot_task_events",
            "sample_task_id",
            "sample_task_state",
        },
        "challenge_fixture",
    )
    if fixture["filename"] != "phase0.db" or fixture["synthetic_only"] is not True:
        raise VerificationError("challenge_fixture_safety_invalid")
    if not isinstance(fixture["sha256"], str) or not HEX64_RE.fullmatch(fixture["sha256"]):
        raise VerificationError("challenge_fixture_sha256_invalid")
    jobs = require_int(fixture["jobs"], 2, 500, "challenge_jobs")
    observations = require_int(fixture["observations"], 8, 5000, "challenge_observations")
    cursor = require_int(fixture["cursor"], 8, 5000, "challenge_cursor")
    hot_events = require_int(fixture["hot_task_events"], 4, 500, "challenge_hot_events")
    if observations != cursor or observations < jobs * 4 or hot_events > observations:
        raise VerificationError("challenge_fixture_counts_inconsistent")
    for field in ("hot_task_id", "sample_task_id", "sample_task_state"):
        if not isinstance(fixture[field], str) or not fixture[field] or len(fixture[field]) > 128:
            raise VerificationError(f"challenge_{field}_invalid")
    if fixture["sample_task_state"] != "attested":
        raise VerificationError("challenge_sample_state_invalid")

    supplied_id = challenge["challenge_id"]
    if not isinstance(supplied_id, str) or not re.fullmatch(r"0x[0-9a-f]{64}", supplied_id):
        raise VerificationError("challenge_id_invalid")
    unsigned = {key: value for key, value in challenge.items() if key != "challenge_id"}
    expected_id = "0x" + sha256_bytes(
        b"Technocore Tasks Phase0 v1|" + canonical_json(unsigned)
    )
    if supplied_id != expected_id:
        raise VerificationError("challenge_id_mismatch")
    return challenge


def expected_vector_sha256(challenge: dict[str, Any]) -> str:
    fixture = challenge["fixture"]
    vector = {
        "candidate_did": challenge["candidate_did"],
        "challenge_id": challenge["challenge_id"],
        "fixture_seed": challenge["fixture_seed"],
        "fixture_sha256": fixture["sha256"],
        "jobs": fixture["jobs"],
        "observations": fixture["observations"],
        "cursor": fixture["cursor"],
        "hot_task_id": fixture["hot_task_id"],
        "hot_task_events": fixture["hot_task_events"],
        "sample_task_id": fixture["sample_task_id"],
        "sample_task_state": fixture["sample_task_state"],
    }
    return sha256_bytes(b"Technocore Tasks Phase0 result vector v1|" + canonical_json(vector))


def parse_immutable_github_url(url: Any, artifact_commit: Any) -> tuple[str, str, str, str]:
    if not isinstance(url, str) or len(url) > 500:
        raise VerificationError("immutable_url_invalid")
    if not isinstance(artifact_commit, str) or not HEX40_RE.fullmatch(artifact_commit):
        raise VerificationError("artifact_commit_invalid")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.port is not None:
        raise VerificationError("immutable_url_host_invalid")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise VerificationError("immutable_url_components_invalid")
    parts = [unquote(part) for part in PurePosixPath(parsed.path).parts if part != "/"]
    if len(parts) < 5 or parts[2] != "blob":
        raise VerificationError("immutable_url_path_invalid")
    owner, repository, _, commit, *artifact_parts = parts
    if not GITHUB_PART_RE.fullmatch(owner) or not GITHUB_PART_RE.fullmatch(repository):
        raise VerificationError("immutable_url_repository_invalid")
    if commit != artifact_commit:
        raise VerificationError("immutable_url_commit_mismatch")
    if (
        not artifact_parts
        or artifact_parts[-1] != "phase0-submission.json"
        or any(not GITHUB_PART_RE.fullmatch(part) for part in artifact_parts)
    ):
        raise VerificationError("immutable_url_artifact_invalid")
    if any(part in {"", ".", ".."} for part in artifact_parts):
        raise VerificationError("immutable_url_artifact_invalid")
    return owner, repository, commit, "/".join(artifact_parts)


def safe_artifact_path(root: Path, name: Any, expected_name: str) -> Path:
    if name != expected_name or Path(name).name != name:
        raise VerificationError(f"{expected_name}_name_invalid")
    candidate = root / name
    try:
        if not candidate.is_file() or candidate.is_symlink():
            raise VerificationError(f"{expected_name}_missing")
    except OSError as exc:
        raise VerificationError(f"{expected_name}_missing") from exc
    return candidate


def candidate_result_facts(result: dict[str, Any]) -> dict[str, Any]:
    try:
        return {
            "passed": result["passed"],
            "fixture": result["fixture"],
            "measurements": result["measurements"],
            "source_before": result["source_before"],
            "source_after": result["source_after"],
            "acceptance_criteria": result["acceptance_criteria"],
            "environment": result["environment"],
            "commands": result["commands"],
        }
    except KeyError as exc:
        raise VerificationError("result_required_field_missing") from exc


def validate_result(result: dict[str, Any], challenge: dict[str, Any], outcome: str) -> None:
    facts = candidate_result_facts(result)
    fixture_expected = challenge["fixture"]
    fixture = facts["fixture"]
    if not isinstance(result.get("schema_version"), int) or result["schema_version"] != 1:
        raise VerificationError("result_version_invalid")
    if not isinstance(fixture, dict) or fixture.get("synthetic_only") is not True:
        raise VerificationError("result_not_synthetic")
    fixture_pairs = {
        "jobs": fixture_expected["jobs"],
        "observations": fixture_expected["observations"],
        "hot_task_events": fixture_expected["hot_task_events"],
        "input_sha256": fixture_expected["sha256"],
    }
    if any(fixture.get(key) != value for key, value in fixture_pairs.items()):
        raise VerificationError("result_fixture_mismatch")

    source_counts_expected = {
        "observations": fixture_expected["observations"],
        "min_seq": 1,
        "max_seq": fixture_expected["cursor"],
        "cursor": fixture_expected["cursor"],
    }
    for label in ("source_before", "source_after"):
        source = facts[label]
        if not isinstance(source, dict) or set(source) != {*source_counts_expected, "quick_check"}:
            raise VerificationError("result_source_state_invalid")
        if any(source.get(key) != value for key, value in source_counts_expected.items()):
            raise VerificationError("result_source_state_mismatch")
        if (
            not isinstance(source["quick_check"], str)
            or not source["quick_check"]
            or len(source["quick_check"]) > 256
        ):
            raise VerificationError("result_quick_check_invalid")
    if not isinstance(facts["acceptance_criteria"], list) or not facts["acceptance_criteria"]:
        raise VerificationError("result_criteria_invalid")
    if not all(
        isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and isinstance(item.get("passed"), bool)
        for item in facts["acceptance_criteria"]
    ):
        raise VerificationError("result_criteria_invalid")
    if not isinstance(facts["passed"], bool):
        raise VerificationError("result_passed_invalid")
    if (outcome == "PASS") != facts["passed"]:
        raise VerificationError("technical_outcome_mismatch")
    if outcome == "PASS" and any(
        facts[label]["quick_check"] != "ok" for label in ("source_before", "source_after")
    ):
        raise VerificationError("passing_result_quick_check_not_ok")

    measurements = facts["measurements"]
    if not isinstance(measurements, dict):
        raise VerificationError("result_measurements_invalid")
    wall = measurements.get("total_wall_seconds")
    rss = measurements.get("peak_rss_bytes")
    if isinstance(wall, bool) or not isinstance(wall, (int, float)) or wall <= 0:
        raise VerificationError("result_runtime_invalid")
    if isinstance(rss, bool) or not isinstance(rss, int) or rss <= 0:
        raise VerificationError("result_rss_invalid")
    if wall > challenge["limits"]["timeout_seconds"] * 20:
        raise VerificationError("result_runtime_implausible")
    if rss > challenge["limits"]["memory_mib"] * 1024 * 1024 * 20:
        raise VerificationError("result_rss_implausible")

    environment = facts["environment"]
    if not isinstance(environment, dict) or any(
        not isinstance(environment.get(key), str) or not environment[key].strip()
        for key in ("python", "platform", "machine")
    ):
        raise VerificationError("result_environment_invalid")
    commands = facts["commands"]
    if not isinstance(commands, list) or not commands or any(
        not isinstance(command, str)
        or not command.strip()
        or "\n" in command
        or "\r" in command
        for command in commands
    ):
        raise VerificationError("result_commands_invalid")


def scan_public_text(root: Path) -> None:
    names = (
        "phase0-submission.json",
        "phase1-result.json",
        "phase0.db.manifest.json",
        "phase1-operations.csv",
        "phase1-report.md",
    )
    forbidden = (
        re.compile(r"(?i)[A-Z]:\\(?:Users|Documents and Settings)\\"),
        re.compile(r"(?i)/(?:home|Users)/[^/\s]+/"),
        re.compile(r"(?i)BEGIN [A-Z ]*PRIVATE KEY"),
        re.compile(r"(?i)\b(?:private[_ -]?key|sign[_ -]?seed|wallet[_ -]?seed|seed phrase)\b"),
    )
    for name in names:
        path = safe_artifact_path(root, name, name)
        try:
            if path.stat().st_size > MAX_JSON_BYTES:
                raise VerificationError(f"{name}_size_invalid")
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise VerificationError(f"{name}_text_invalid") from exc
        if any(pattern.search(text) for pattern in forbidden):
            raise VerificationError(f"{name}_contains_private_material_or_path")


def github_readback(
    owner: str, repository: str, commit: str, artifact_path: str, expected: bytes
) -> str:
    remote_path = f"/{owner}/{repository}/{commit}/{artifact_path}"
    connection = http.client.HTTPSConnection("raw.githubusercontent.com", timeout=15)
    try:
        connection.request(
            "GET",
            remote_path,
            headers={"Accept": "application/octet-stream", "User-Agent": "technocore-phase0-verifier/1"},
        )
        response = connection.getresponse()
        if response.status != 200:
            raise VerificationError("github_readback_http_not_200")
        content_length = response.getheader("Content-Length")
        if content_length is not None and int(content_length) > MAX_REMOTE_BYTES:
            raise VerificationError("github_readback_too_large")
        body = response.read(MAX_REMOTE_BYTES + 1)
    except (OSError, http.client.HTTPException, ValueError) as exc:
        if isinstance(exc, VerificationError):
            raise
        raise VerificationError("github_readback_failed") from exc
    finally:
        connection.close()
    if len(body) > MAX_REMOTE_BYTES:
        raise VerificationError("github_readback_too_large")
    if body != expected:
        raise VerificationError("github_readback_content_mismatch")
    return sha256_bytes(body)


def verify(
    challenge_path: Path,
    artifact_root: Path,
    *,
    check_github: bool = False,
) -> dict[str, Any]:
    challenge, _ = load_json(challenge_path, "challenge")
    validate_challenge(challenge)

    submission_path = safe_artifact_path(
        artifact_root, "phase0-submission.json", "phase0-submission.json"
    )
    submission, submission_raw = load_json(submission_path, "submission")
    require_exact_keys(
        submission,
        {
            "schema_version",
            "candidate_did",
            "qualification_id",
            "public_nonce",
            "release_commit",
            "challenge_id",
            "command",
            "technical_outcome",
            "deterministic_expected_sha256",
            "artifact_commit",
            "immutable_artifact_url",
            "files",
        },
        "submission",
    )
    if submission["schema_version"] != 1:
        raise VerificationError("submission_version_invalid")
    for key in ("candidate_did", "qualification_id", "public_nonce", "release_commit", "challenge_id"):
        if submission[key] != challenge[key]:
            raise VerificationError(f"submission_{key}_mismatch")
    if submission["technical_outcome"] not in {"PASS", "FAIL"}:
        raise VerificationError("technical_outcome_invalid")
    if (
        not isinstance(submission["command"], str)
        or not submission["command"].strip()
        or "\n" in submission["command"]
        or "\r" in submission["command"]
    ):
        raise VerificationError("submission_command_invalid")
    if submission["deterministic_expected_sha256"] != expected_vector_sha256(challenge):
        raise VerificationError("deterministic_expected_sha256_mismatch")

    repository = parse_immutable_github_url(
        submission["immutable_artifact_url"], submission["artifact_commit"]
    )
    files = submission["files"]
    if not isinstance(files, dict):
        raise VerificationError("submission_files_invalid")
    require_exact_keys(
        files,
        {"result", "result_sha256", "manifest", "manifest_sha256"},
        "submission_files",
    )
    result_path = safe_artifact_path(artifact_root, files["result"], "phase1-result.json")
    manifest_path = safe_artifact_path(
        artifact_root, files["manifest"], "phase0.db.manifest.json"
    )
    for key in ("result_sha256", "manifest_sha256"):
        if not isinstance(files[key], str) or not HEX64_RE.fullmatch(files[key]):
            raise VerificationError(f"submission_{key}_invalid")
    if sha256_file(result_path) != files["result_sha256"]:
        raise VerificationError("result_sha256_mismatch")
    if sha256_file(manifest_path) != files["manifest_sha256"]:
        raise VerificationError("manifest_sha256_mismatch")

    manifest, _ = load_json(manifest_path, "manifest")
    fixture = challenge["fixture"]
    manifest_expected = {
        "fixture": fixture["filename"],
        "synthetic_only": True,
        "jobs": fixture["jobs"],
        "observations": fixture["observations"],
        "cursor": fixture["cursor"],
        "hot_task_id": fixture["hot_task_id"],
        "hot_task_events": fixture["hot_task_events"],
        "sha256": fixture["sha256"],
    }
    if any(manifest.get(key) != value for key, value in manifest_expected.items()):
        raise VerificationError("manifest_challenge_mismatch")

    result, _ = load_json(result_path, "result")
    validate_result(result, challenge, submission["technical_outcome"])
    if submission["command"] not in result["commands"]:
        raise VerificationError("submission_command_not_in_result")
    scan_public_text(artifact_root)

    github_status = "NOT_CHECKED"
    github_sha256 = None
    if check_github:
        github_sha256 = github_readback(*repository, submission_raw)
        github_status = "VERIFIED_EXACT_BYTES"

    return {
        "status": "ARTIFACT_VALID",
        "candidate_did": challenge["candidate_did"],
        "challenge_id": challenge["challenge_id"],
        "technical_outcome": submission["technical_outcome"],
        "github_readback": github_status,
        "github_sha256": github_sha256,
        "manual_counterparty_decision_required": True,
        "automatic_lock_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--challenge", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument(
        "--check-github",
        action="store_true",
        help="read exact bytes from a strict commit-pinned github.com blob URL",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = verify(args.challenge, args.artifact_root, check_github=args.check_github)
    except VerificationError as exc:
        report = {
            "status": "ARTIFACT_INVALID",
            "reason": str(exc),
            "manual_counterparty_decision_required": True,
            "automatic_lock_authorized": False,
        }
        return_code = 2
    else:
        return_code = 0
    encoded = json.dumps(report, ensure_ascii=True, indent=2) + "\n"
    if args.output:
        if args.output.exists():
            raise SystemExit("refusing to overwrite verifier output")
        args.output.write_text(encoded, encoding="utf-8")
    sys.stdout.write(encoded)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
