"""Run the bounded Phase 0 qualification against a manifest-marked synthetic database."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from technocore_tasks.storage import Store


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def source_state(database: Path) -> dict[str, object]:
    db = sqlite3.connect(database)
    try:
        observations, minimum, maximum = db.execute(
            "SELECT COUNT(*),COALESCE(MIN(seq),0),COALESCE(MAX(seq),0) FROM observations"
        ).fetchone()
        cursor = db.execute("SELECT cursor FROM collector_state WHERE room='kibble'").fetchone()
        return {
            "observations": observations,
            "min_seq": minimum,
            "max_seq": maximum,
            "cursor": cursor[0] if cursor else None,
            "quick_check": db.execute("PRAGMA quick_check").fetchone()[0],
        }
    finally:
        db.close()


def load_manifest(database: Path, manifest_path: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {"fixture", "synthetic_only", "jobs", "observations", "cursor", "hot_task_id",
                "hot_task_events", "sha256"}
    if not isinstance(manifest, dict) or not required.issubset(manifest):
        raise ValueError("fixture manifest is missing required fields")
    if manifest["synthetic_only"] is not True:
        raise ValueError("refusing a fixture not explicitly marked synthetic_only=true")
    if manifest["fixture"] != database.name:
        raise ValueError("fixture filename does not match its manifest")
    if manifest["sha256"] != sha256(database):
        raise ValueError("fixture checksum does not match its manifest")
    return manifest


def criterion(name: str, passed: bool, evidence: object) -> dict[str, object]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def write_csv(path: Path, operations: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("operation", "outcome", "wall_seconds", "peak_rss_bytes",
                        "peak_rss_mib", "status_code"),
        )
        writer.writeheader()
        for item in operations:
            measurement = item.get("measurement") or {}
            writer.writerow({
                "operation": item["operation"],
                "outcome": item["outcome"],
                "wall_seconds": item["wall_seconds"],
                "peak_rss_bytes": item["peak_rss_bytes"],
                "peak_rss_mib": item["peak_rss_mib"],
                "status_code": measurement.get("status_code", ""),
            })


def write_markdown(path: Path, result: dict[str, object]) -> None:
    checks = result["acceptance_criteria"]
    operations = result["benchmark"]["operations"]
    lines = [
        "# Technocore Tasks Phase 0 independent result", "",
        f"- Overall: **{'PASS' if result['passed'] else 'FAIL'}**",
        f"- Synthetic observations: `{result['fixture']['observations']}`",
        f"- Synthetic jobs: `{result['fixture']['jobs']}`",
        f"- Fixture input bytes: `{result['fixture']['input_bytes']}`",
        f"- Total wall time: `{result['measurements']['total_wall_seconds']} s`",
        f"- Peak process-tree RSS: `{result['measurements']['peak_rss_mib']} MiB`",
        f"- Immutable artifact URL: `{result['immutable_artifact_url']}`", "",
        "## Environment", "",
        f"- Python: `{result['environment']['python']}`",
        f"- Platform: `{result['environment']['platform']}`",
        f"- Machine: `{result['environment']['machine']}`", "",
        "## Acceptance criteria", "",
        "| Criterion | Result | Evidence |", "|---|---|---|",
    ]
    for item in checks:
        evidence = json.dumps(item["evidence"], ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        lines.append(f"| {item['name']} | {'PASS' if item['passed'] else 'FAIL'} | `{evidence}` |")
    lines.extend(["", "## Operations", "", "| Operation | Outcome | Wall seconds | Peak RSS MiB |",
                  "|---|---|---:|---:|"])
    for item in operations:
        lines.append(f"| {item['operation']} | {item['outcome']} | {item['wall_seconds']} | {item['peak_rss_mib']} |")
    lines.extend(["", "## Exact commands", ""])
    for command in result["commands"]:
        lines.append(f"- `{command}`")
    lines.extend(["", "## Failures and limitations", ""])
    if result["failures"]:
        lines.extend(f"- {item}" for item in result["failures"])
    else:
        lines.append("- No acceptance criterion failed in this run.")
    lines.extend([
        "- The fixture is synthetic and does not reproduce production traffic, storage latency, or the historical OOM.",
        "- Peak RSS is sampled process-tree RSS and can miss a shorter-lived peak between samples.",
        "- A passing result supports only the bounded checks listed here; it is not a general correctness or security proof.",
        "", "A reproducible negative result is valid work and must not be rewritten as a pass.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--memory-mib", type=int, default=1024)
    parser.add_argument("--timeout-seconds", type=float, default=180)
    parser.add_argument("--immutable-artifact-url", default="TO_BE_PUBLISHED")
    args = parser.parse_args()
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise SystemExit("refusing to overwrite a non-empty output directory")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    manifest = load_manifest(args.database, args.manifest)
    fixture_input_bytes = int(args.database.stat().st_size) + int(args.manifest.stat().st_size)
    before = source_state(args.database)
    benchmark_path = args.output_dir / "phase1-benchmark.json"
    benchmark_script = Path(__file__).with_name("benchmark_pilot.py")
    completed = subprocess.run(
        [sys.executable, str(benchmark_script), "--database", str(args.database),
         "--output", str(benchmark_path), "--memory-mib", str(args.memory_mib),
         "--timeout-seconds", str(args.timeout_seconds)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not benchmark_path.is_file():
        raise SystemExit(f"benchmark failed with exit code {completed.returncode}")
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    after = source_state(args.database)

    store = Store(args.database)
    maintenance = store.maintenance_status()
    counts = {**store.counts(), **store.projection_stats()}
    normal = store.projection("k0000000001", "KIBBLE") if int(manifest["jobs"]) > 1 else None
    hot_events, hot_page = store.events(str(manifest["hot_task_id"]), "KIBBLE", page=1, page_size=10_000)
    reopened = Store(args.database)
    restart_status = reopened.maintenance_status()
    restart_counts = {**reopened.counts(), **reopened.projection_stats()}

    source_expected = {
        "observations": int(manifest["observations"]), "min_seq": 1,
        "max_seq": int(manifest["cursor"]), "cursor": int(manifest["cursor"]),
        "quick_check": "ok",
    }
    api_operations = [item for item in benchmark["operations"] if item["operation"] != "startup"]
    checks = [
        criterion("source observations and cursor match manifest before migration", before == source_expected,
                  {"actual": before, "expected": source_expected}),
        criterion("source observations and cursor preserved after migration", after == before,
                  {"before": before, "after": after}),
        criterion("projection maintenance ready", maintenance["ready"], maintenance),
        criterion("projected task count matches fixture", counts["tasks"] == int(manifest["jobs"]), counts),
        criterion("normal task state is attested", normal is not None and normal["state"] == "attested",
                  {"task_id": "k0000000001", "state": normal["state"] if normal else None}),
        criterion("hot-task evidence page is capped at 200",
                  len(hot_events) == min(200, int(manifest["hot_task_events"])) and hot_page["page_size"] == 200,
                  {"returned": len(hot_events), "pagination": hot_page}),
        criterion("hot-task evidence total matches fixture", hot_page["total"] == int(manifest["hot_task_events"]),
                  {"actual": hot_page["total"], "expected": manifest["hot_task_events"]}),
        criterion("all endpoint benchmarks completed", all(item["outcome"] == "ok" for item in benchmark["operations"]),
                  {item["operation"]: item["outcome"] for item in benchmark["operations"]}),
        criterion("all requested HTTP endpoints returned 200",
                  all((item.get("measurement") or {}).get("status_code") == 200 for item in api_operations),
                  {item["operation"]: (item.get("measurement") or {}).get("status_code") for item in api_operations}),
        criterion("restart preserves ready projection and counts",
                  restart_status["ready"] and restart_counts == counts,
                  {"maintenance": restart_status, "counts": restart_counts}),
        criterion("SQLite quick_check is ok after restart", source_state(args.database)["quick_check"] == "ok",
                  source_state(args.database)["quick_check"]),
    ]
    failures = [item["name"] for item in checks if not item["passed"]]
    peak_rss = max(int(item["peak_rss_bytes"]) for item in benchmark["operations"])
    result = {
        "schema_version": 1,
        "passed": not failures,
        "environment": {
            "python": platform.python_version(), "platform": sys.platform,
            "machine": platform.machine() or "unknown",
        },
        "fixture": {
            "synthetic_only": True, "jobs": manifest["jobs"],
            "observations": manifest["observations"], "hot_task_events": manifest["hot_task_events"],
            "input_bytes": fixture_input_bytes,
            "input_sha256": manifest["sha256"],
        },
        "measurements": {
            "total_wall_seconds": round(time.perf_counter() - started, 3),
            "peak_rss_bytes": peak_rss, "peak_rss_mib": round(peak_rss / 1024 / 1024, 1),
        },
        "source_before": before,
        "source_after": after,
        "acceptance_criteria": checks,
        "benchmark": benchmark,
        "failures": failures,
        "limitations": [
            "synthetic fixture; no production data or production OOM reproduction",
            "sampled process-tree RSS may miss sub-sample peaks",
            "bounded checks are not a general correctness or security proof",
        ],
        "immutable_artifact_url": args.immutable_artifact_url,
        "commands": [
            f"python generate_synthetic_fixture.py {args.database.name} --jobs {manifest['jobs']} --hot-extra-events {int(manifest['hot_task_events']) - 4}",
            f"python phase1_verify.py --database {args.database.name} --manifest {args.manifest.name} --output-dir phase1-results --memory-mib {args.memory_mib} --timeout-seconds {args.timeout_seconds}",
        ],
    }
    result_path = args.output_dir / "phase1-result.json"
    csv_path = args.output_dir / "phase1-operations.csv"
    report_path = args.output_dir / "phase1-report.md"
    result_path.write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    write_csv(csv_path, benchmark["operations"])
    write_markdown(report_path, result)
    print(json.dumps({
        "passed": result["passed"], "total_wall_seconds": result["measurements"]["total_wall_seconds"],
        "peak_rss_mib": result["measurements"]["peak_rss_mib"],
        "observations": manifest["observations"], "jobs": manifest["jobs"],
        "outputs": [result_path.name, csv_path.name, report_path.name, benchmark_path.name],
    }, sort_keys=True))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
