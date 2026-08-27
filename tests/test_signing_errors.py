from __future__ import annotations

import httpx

from technocore_tasks import cli
from technocore_tasks.local_signing import LocalSigner, TechnocoreWriteError, post_signed


def test_post_signed_preserves_exact_upstream_error_body(monkeypatch):
    expected = "400 nonce must be 1-19 digits, got 'bad'\nsecond diagnostic line"
    real_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/r/technocore-tasks"
        return httpx.Response(400, text=expected)

    def fake_client(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("technocore_tasks.local_signing.httpx.Client", fake_client)
    signer = LocalSigner(bytes([7]) * 32)

    try:
        post_signed("https://technocore.chat", "technocore-tasks", signer, 123, "safe text")
    except TechnocoreWriteError as exc:
        assert exc.status_code == 400
        assert exc.body == expected
        assert str(exc).endswith(expected)
    else:
        raise AssertionError("expected upstream refusal")


def test_cli_prints_upstream_body_without_request_material(monkeypatch, capsys):
    body = "400 exact upstream diagnostic"

    def refuse(*args, **kwargs):
        raise TechnocoreWriteError(400, "Bad Request", body)

    monkeypatch.setattr(cli, "_post", refuse)
    result = cli.main(["claim", "task-a83fd2c9"])
    captured = capsys.readouterr()

    assert result == 2
    assert body in captured.err
    assert "upstream response body:" in captured.err
    assert "sig" not in captured.err
