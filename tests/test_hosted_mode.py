import os

import pytest

from technocore_tasks.local_signing import ensure_local_mode, load_seed


def test_hosted_mode_cannot_sign(monkeypatch):
    monkeypatch.setenv("TASKS_MODE", "hosted")
    monkeypatch.setenv("SIGN_SEED", "00" * 32)
    with pytest.raises(RuntimeError, match="disabled"):
        ensure_local_mode()


def test_seed_validation_never_prints_or_persists(monkeypatch, store, capsys):
    secret = "ab" * 32
    monkeypatch.setenv("SIGN_SEED", secret)
    assert load_seed() == bytes.fromhex(secret)
    assert secret not in str(store.metadata())
    assert secret not in capsys.readouterr().out


def test_web_module_does_not_import_signing_support():
    import technocore_tasks.web as web
    assert "technocore_tasks.local_signing" not in web.__dict__

