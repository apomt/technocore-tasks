"""Run isolated, RSS-limited Technocore Tasks endpoint benchmarks against a synthetic DB."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

OPERATIONS = {
    "startup": None,
    "homepage": "/",
    "search": "/?q=Synthetic",
    "stats": "/api/stats",
    "task_detail": "/task/{task_id}",
    "api_detail": "/api/tasks/{task_id}?page_size=200",
}
MARKER = "TCLK_PILOT_RESULT="


def worker(database: Path, operation: str, task_id: str, normal_task_id: str) -> int:
    os.environ.update(TASKS_DATABASE=str(database), TASKS_COLLECTOR_ENABLED="0", TASKS_MODE="local")
    started = time.perf_counter()
    try:
        from fastapi.testclient import TestClient
        from technocore_tasks.web import app

        if operation == "startup":
            payload = {"operation": operation, "seconds": time.perf_counter() - started, "status_code": None}
        else:
            path = OPERATIONS[operation].format(task_id=task_id)
            with TestClient(app) as client:
                request_started = time.perf_counter()
                response = client.get(path)
                body = response.json() if path.startswith("/api/") else None
                normal_response = None
                normal_body = None
                if operation == "api_detail":
                    normal_response = client.get(f"/api/tasks/{normal_task_id}?page_size=200")
                    normal_body = normal_response.json()
            payload = {
                "operation": operation,
                "startup_seconds": request_started - started,
                "seconds": time.perf_counter() - request_started,
                "status_code": response.status_code,
                "response_bytes": len(response.content),
            }
            if operation == "stats" and isinstance(body, dict):
                payload["reported_counts"] = {key: body.get(key) for key in ("observations", "tasks")}
            if operation == "api_detail" and isinstance(body, dict):
                payload["native_state"] = body.get("native_state")
                payload["event_timeline_count"] = len(body.get("event_timeline", []))
                payload["event_pagination"] = body.get("event_pagination")
                payload["normal_task_id"] = normal_task_id
                payload["normal_task_status_code"] = normal_response.status_code
                payload["normal_task_native_state"] = (
                    normal_body.get("native_state") if isinstance(normal_body, dict) else None
                )
        print(MARKER + json.dumps(payload, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(MARKER + json.dumps({"operation": operation, "error_type": type(exc).__name__}))
        return 2


def rss_tree(process: psutil.Process) -> int:
    total = 0
    try:
        items = [process, *process.children(recursive=True)]
    except psutil.NoSuchProcess:
        return 0
    for item in items:
        try:
            total += item.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return total


def stop_tree(process: psutil.Process) -> None:
    for item in reversed(process.children(recursive=True)):
        try:
            item.kill()
        except psutil.NoSuchProcess:
            pass
    try:
        process.kill()
    except psutil.NoSuchProcess:
        pass


def redact_stderr(stderr: str) -> str:
    redacted = stderr[-1000:]
    paths = sorted(
        {str(Path.home()), tempfile.gettempdir(), str(Path.cwd())}, key=len, reverse=True
    )
    for path in paths:
        redacted = redacted.replace(path, "<LOCAL_PATH>")
    return redacted


def run_one(script: Path, database: Path, operation: str, task_id: str, normal_task_id: str,
            memory_bytes: int, timeout_seconds: float) -> dict:
    command = [sys.executable, str(script), "--worker", "--database", str(database),
               "--operation", operation, "--task-id", task_id,
               "--normal-task-id", normal_task_id]
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    process = psutil.Process(child.pid)
    peak, started, outcome = 0, time.perf_counter(), "ok"
    while child.poll() is None:
        peak = max(peak, rss_tree(process))
        if peak > memory_bytes:
            outcome = "memory_limit"
            stop_tree(process)
            break
        if time.perf_counter() - started > timeout_seconds:
            outcome = "timeout"
            stop_tree(process)
            break
        time.sleep(0.02)
    stdout, stderr = child.communicate()
    payload = next((json.loads(line[len(MARKER):]) for line in stdout.splitlines()
                    if line.startswith(MARKER)), None)
    if outcome == "ok" and (child.returncode != 0 or payload is None):
        outcome = "error"
    return {
        "operation": operation,
        "outcome": outcome,
        "exit_code": child.returncode,
        "wall_seconds": round(time.perf_counter() - started, 3),
        "peak_rss_bytes": peak,
        "peak_rss_mib": round(peak / 1024 / 1024, 1),
        "measurement": payload,
        "stderr_tail": redact_stderr(stderr),
    }


def invariants(database: Path) -> dict:
    db = sqlite3.connect(database)
    try:
        observations, minimum, maximum = db.execute(
            "SELECT COUNT(*),COALESCE(MIN(seq),0),COALESCE(MAX(seq),0) FROM observations"
        ).fetchone()
        cursor = db.execute("SELECT cursor FROM collector_state WHERE room='kibble'").fetchone()
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        projected = (db.execute("SELECT COUNT(*) FROM task_projections").fetchone()[0]
                     if "task_projections" in tables else None)
        integrity = db.execute("PRAGMA quick_check").fetchone()[0]
        return {"observations": observations, "min_seq": minimum, "max_seq": maximum,
                "cursor": cursor[0] if cursor else None, "projected_tasks": projected,
                "quick_check": integrity}
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--task-id", default="k0000000000")
    parser.add_argument("--normal-task-id", default="k0000000001")
    parser.add_argument("--memory-mib", type=int, default=3072)
    parser.add_argument("--timeout-seconds", type=float, default=180)
    parser.add_argument("--operation", choices=OPERATIONS)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        raise SystemExit(worker(args.database, args.operation, args.task_id, args.normal_task_id))
    if args.output is None or args.output.exists():
        raise SystemExit("--output must name a new JSON file")

    before = invariants(args.database)
    results = [run_one(Path(__file__).resolve(), args.database, operation, args.task_id,
                       args.normal_task_id,
                       args.memory_mib * 1024 * 1024, args.timeout_seconds)
               for operation in OPERATIONS]
    after = invariants(args.database)
    report = {
        "schema_version": 1,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version,
        "platform": sys.platform,
        "memory_budget_mib": args.memory_mib,
        "timeout_seconds": args.timeout_seconds,
        "database": str(args.database.name),
        "before": before,
        "after": after,
        "invariants_preserved": before == after,
        "operations": results,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
