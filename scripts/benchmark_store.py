"""Measure bounded store migration and read paths against a SQLite copy."""

from __future__ import annotations

import argparse
import json
import os
import time

import psutil

from technocore_tasks.board import Board
from technocore_tasks.storage import Store


def sample(label: str, started: float, rss_before: int, **extra) -> dict:
    rss = psutil.Process(os.getpid()).memory_info().rss
    return {"operation": label, "seconds": round(time.perf_counter() - started, 3),
            "rss_mib": round(rss / 1024 / 1024, 1),
            "rss_delta_mib": round((rss - rss_before) / 1024 / 1024, 1), **extra}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    parser.add_argument("--task-id")
    parser.add_argument("--migrate", action="store_true")
    parser.add_argument("--batch-size", type=int, default=5000)
    args = parser.parse_args()
    process = psutil.Process(os.getpid())
    started, before = time.perf_counter(), process.memory_info().rss
    store = Store(args.database)
    results = [sample("startup", started, before, maintenance=store.maintenance_status())]
    if args.migrate:
        started, before = time.perf_counter(), process.memory_info().rss
        status = store.run_maintenance(args.batch_size)
        results.append(sample("migration", started, before, maintenance=status))
    board = Board(store)
    for label, operation in (
        ("list_page_200", lambda: board.search_page(page_size=200)[0]),
        ("stats", board.stats),
        ("detail_page_200", lambda: board.task(args.task_id, page_size=200) if args.task_id else None),
    ):
        started, before = time.perf_counter(), process.memory_info().rss
        result = operation()
        results.append(sample(label, started, before, returned=len(result) if isinstance(result, list) else bool(result)))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
