from __future__ import annotations

import shutil
from pathlib import Path


def classify_storage(percent_used: float, warning: float, urgent: float, critical: float) -> str:
    """Classify capacity without taking any cleanup action."""
    if percent_used >= critical:
        return "critical"
    if percent_used >= urgent:
        return "urgent"
    if percent_used >= warning:
        return "warning"
    return "ok"


def _file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0
    except OSError:
        return None


def storage_metrics(
    database: str | Path,
    warning: float = 80.0,
    urgent: float = 90.0,
    critical: float = 95.0,
) -> dict:
    """Return constant-time filesystem and SQLite file metrics; never enumerate or mutate files."""
    path = Path(database)
    thresholds = {"warning": warning, "urgent": urgent, "critical": critical}
    sizes = {
        "database_bytes": _file_size(path),
        "wal_bytes": _file_size(Path(f"{path}-wal")),
        "shm_bytes": _file_size(Path(f"{path}-shm")),
    }
    try:
        usage = shutil.disk_usage(path.parent)
        percent = round((usage.used / usage.total) * 100, 2) if usage.total else 0.0
        return {
            "available": True,
            "capacity_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "percent_used": percent,
            "state": classify_storage(percent, warning, urgent, critical),
            "thresholds_percent": thresholds,
            **sizes,
        }
    except OSError:
        return {
            "available": False,
            "capacity_bytes": None,
            "used_bytes": None,
            "free_bytes": None,
            "percent_used": None,
            "state": "unavailable",
            "thresholds_percent": thresholds,
            "error": "filesystem_metrics_unavailable",
            **sizes,
        }
