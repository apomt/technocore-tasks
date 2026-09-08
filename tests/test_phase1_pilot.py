from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "docs" / "tclk-pilot" / "generate_synthetic_fixture.py"
VERIFIER = ROOT / "docs" / "tclk-pilot" / "phase1_verify.py"


def _load_verifier():
    spec = importlib.util.spec_from_file_location("phase1_verify", VERIFIER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase1_refuses_a_manifest_not_marked_synthetic(tmp_path):
    database = tmp_path / "phase1.db"
    subprocess.run(
        [sys.executable, str(GENERATOR), str(database), "--jobs", "2", "--hot-extra-events", "0"],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    manifest_path = database.with_suffix(".db.manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["synthetic_only"] = False
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    verifier = _load_verifier()
    try:
        verifier.load_manifest(database, manifest_path)
    except ValueError as exc:
        assert "synthetic_only=true" in str(exc)
    else:
        raise AssertionError("non-synthetic manifest was accepted")


def test_phase1_small_end_to_end_result_is_reproducible_and_path_safe(tmp_path):
    database = tmp_path / "phase1.db"
    results = tmp_path / "results"
    subprocess.run(
        [sys.executable, str(GENERATOR), str(database), "--jobs", "10", "--hot-extra-events", "200"],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    completed = subprocess.run(
        [sys.executable, str(VERIFIER), "--database", str(database), "--manifest",
         str(database.with_suffix(".db.manifest.json")), "--output-dir", str(results),
         "--memory-mib", "512", "--timeout-seconds", "60",
         "--immutable-artifact-url", "https://example.invalid/immutable/commit/report"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads((results / "phase1-result.json").read_text(encoding="utf-8"))
    report = (results / "phase1-report.md").read_text(encoding="utf-8")
    csv_text = (results / "phase1-operations.csv").read_text(encoding="utf-8")
    assert result["passed"] and not result["failures"]
    assert all(item["passed"] for item in result["acceptance_criteria"])
    assert result["fixture"]["synthetic_only"] is True
    assert result["source_before"] == result["source_after"]
    assert "Exact commands" in report and "Failures and limitations" in report
    assert "operation,outcome,wall_seconds,peak_rss_bytes" in csv_text
    combined = json.dumps(result) + report + csv_text
    assert str(tmp_path) not in combined
    assert "SIGN_SEED" not in combined and "private_key" not in combined
