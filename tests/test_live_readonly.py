from __future__ import annotations

import httpx
import pytest

from technocore_tasks.collector import Collector
from technocore_tasks.storage import Store


@pytest.mark.live
@pytest.mark.asyncio
async def test_current_technocore_read_only_compatibility(tmp_path):
    paths: list[str] = []

    async def record_request(request: httpx.Request):
        assert request.method == "GET"
        paths.append(request.url.path)

    async with httpx.AsyncClient(
        base_url="https://technocore.chat",
        timeout=20,
        follow_redirects=False,
        event_hooks={"request": [record_request]},
    ) as client:
        store = Store(tmp_path / "live-readonly.db")
        collector = Collector(store, "https://technocore.chat", "kibble", client=client)
        result = await collector.collect_once()
        restarted = await Collector(store, "https://technocore.chat", "kibble", client=client).collect_once(refresh_metadata=False)

    metadata = store.metadata()
    assert metadata["agent"]["name"] == "technocore-chat"
    assert metadata["openapi_info"]["version"]
    assert result["cursor"] > 0 and restarted["cursor"] >= result["cursor"]
    assert store.counts()["parsed_events"] > 0
    assert set(paths) == {"/.well-known/agent.json", "/openapi.json", "/r/kibble"}
    assert "/rooms" not in paths
    assert all("/say" not in path and "/kv/" not in path and "/p-" not in path for path in paths)
