from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from technocore_tasks.board import Board
from technocore_tasks.collector import Collector
from technocore_tasks.config import Settings
from technocore_tasks.events import EventParseError
from technocore_tasks.protocols import KibbleV1Adapter
from technocore_tasks.storage import Store
from technocore_tasks.web import create_app

FIXTURE = Path(__file__).parent / "fixtures" / "kibble_tail_redacted.json"


def insert(store, seq, did, text, signed=True):
    message = {"seq": seq, "ts": f"2026-08-27T01:00:{seq % 60:02d}.000000Z", "from": did, "text": text}
    if signed:
        message["nonce"] = 5000 + seq
    store.insert_message("kibble", message)


def test_real_redacted_fixture_reconstructs_native_kibble(store):
    messages = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for message in messages:
        store.insert_message("kibble", message)
    job = Board(store).task("keea6486ee6")
    assert job.protocol == "KIBBLE" and job.protocol_version == "1"
    assert job.source_room == "kibble"
    assert job.state == "attested" and job.normalized_state == "attested_completed"
    assert [event["event_kind"] for event in job.events] == ["JOB", "CLAIM", "RESULT", "ATTEST"]
    assert job.events[-1]["fields"]["result_hash"] == "rh:aff223e8fd21a37b"
    public_event = job.to_dict()["event_timeline"][-1]
    assert public_event["protocol"] == "KIBBLE" and public_event["source_room"] == "kibble"
    assert public_event["partial_history"] is False and public_event["evidence_level"] == "signed_key_possession"
    partial = Board(store).task("k2474c21a64")
    assert partial.state == "partial" and partial.partial_history
    assert partial.events[0]["event_kind"] == "DELIVER"


@pytest.mark.parametrize(("text", "kind", "field"), [
    ("JOB v1 | kabcdef0123 | code | A title | A body | with a pipe", "JOB", "body"),
    ("CLAIM v1 | kabcdef0123 | worker", "CLAIM", "claim"),
    ("RESULT v1 | kabcdef0123 | result | remains intact", "RESULT", "result"),
    ("DELIVER v1 | kabcdef0123 | delivery", "DELIVER", "result"),
    ("ATTEST v1 | kabcdef0123 | not | rh:0123456789abcdef | reason | remains intact", "ATTEST", "reason"),
    ("ATTEST v1 | kabcdef0123 | useful | reason without hash | still intact", "ATTEST", "reason"),
])
def test_kibble_event_grammar_preserves_tail_text(text, kind, field):
    parsed = KibbleV1Adapter().parse_event(text)
    assert parsed.event_kind == kind
    assert parsed.fields[field]
    if "remains intact" in text or "with a pipe" in text:
        assert "|" in parsed.fields[field]


@pytest.mark.parametrize("text", [
    "JOB v1 | bad | code | title | body",
    "CLAIM v1 | kabcdef0123",
    "ATTEST v1 | kabcdef0123 | paid | reason",
    "ATTEST v1 | kabcdef0123 | useful | rh:not-a-hash | reason",
])
def test_malformed_kibble_lines_are_rejected_and_counted(store, dids, text):
    with pytest.raises(EventParseError):
        KibbleV1Adapter().parse_event(text)
    insert(store, 1, dids[0], text)
    assert store.counts()["parse_failures"] == 1
    assert Board(store).all_tasks() == []


def test_unsigned_job_is_not_signed_evidence(store, dids):
    insert(store, 1, dids[0], "JOB v1 | kabcdef0123 | code | unsigned | body", signed=False)
    task = Board(store).task("kabcdef0123")
    assert task.creator_did is None and task.partial_history and task.conflicted
    body = task.to_dict()
    assert body["observed_signed_events"] == []
    assert body["event_timeline"][0]["evidence_level"] == "unsigned_observation"


def test_conflicting_claims_results_and_attestations_are_preserved(store, dids):
    insert(store, 1, dids[0], "JOB v1 | kabcdef0123 | code | title | body")
    insert(store, 2, dids[1], "CLAIM v1 | kabcdef0123 | worker")
    insert(store, 3, dids[2], "CLAIM v1 | kabcdef0123 | worker")
    insert(store, 4, dids[1], "RESULT v1 | kabcdef0123 | result one")
    insert(store, 5, dids[2], "DELIVER v1 | kabcdef0123 | result two")
    insert(store, 6, dids[0], "ATTEST v1 | kabcdef0123 | useful | reason")
    insert(store, 7, dids[3], "ATTEST v1 | kabcdef0123 | not | reason")
    task = Board(store).task("kabcdef0123")
    assert len(task.claims) == 2 and len(task.results) == 2 and len(task.attestations) == 2
    assert {c["kind"] for c in task.conflicts} == {"CLAIM", "DELIVER", "ATTEST"}


def test_multi_protocol_api_filter_search_and_native_states(store, dids):
    insert(store, 10, dids[0], "JOB v1 | kabcdef0123 | explain | Kibble title | body")
    from conftest import add_create
    tc_id = add_create(store, dids[1], seq=11, nonce=5011, title="TC title")
    settings = Settings(database=Path(store.path), collector_enabled=False)
    with TestClient(create_app(settings)) as client:
        all_tasks = client.get("/api/tasks").json()["tasks"]
        kibble = client.get("/api/tasks", params={"protocol": "KIBBLE", "q": "kibble"}).json()["tasks"]
        protocols = client.get("/api/protocols").json()["protocols"]
        detail = client.get("/api/tasks/kabcdef0123").json()
    assert {item["protocol"] for item in all_tasks} == {"KIBBLE", "TC-TASK"}
    assert [item["task_id"] for item in kibble] == ["kabcdef0123"]
    assert {item["display_name"] for item in protocols} == {"KIBBLE-V1", "TC-TASK/1"}
    assert detail["native_state"] == "open" and detail["normalized_state"] == "open"
    assert tc_id in {item["task_id"] for item in all_tasks}


def test_hostile_kibble_html_escaped_and_url_never_fetched(store, dids):
    external = "http://169.254.169.254/latest/meta-data/"
    insert(store, 1, dids[0], 'JOB v1 | kabcdef0123 | code | <img src=x onerror="alert(1)"> | <script>bad()</script>')
    insert(store, 2, dids[1], f"RESULT v1 | kabcdef0123 | {external}")
    with TestClient(create_app(Settings(database=Path(store.path), collector_enabled=False))) as client:
        home, detail = client.get("/"), client.get("/task/kabcdef0123")
    assert "<script>bad()" not in home.text and "&lt;script&gt;bad()" in home.text
    assert "<img src=x" not in detail.text and "&lt;img src=x" in detail.text
    assert external in detail.text and f'href="{external}"' not in detail.text


@pytest.mark.asyncio
async def test_collector_follows_only_configured_room_not_message_urls(store, dids):
    paths = []
    message = {"seq": 1, "ts": "2026-08-27T00:00:00Z", "from": dids[0], "nonce": 1,
               "text": "RESULT v1 | kabcdef0123 | https://attacker.invalid/result"}
    def handler(request):
        paths.append(request.url.path)
        if request.url.path == "/.well-known/agent.json":
            return httpx.Response(200, json={})
        if request.url.path == "/openapi.json":
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"room": "kibble", "count": 1, "first_seq": 1, "last_seq": 1, "messages": [message]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://technocore.chat") as client:
        await Collector(store, "https://technocore.chat", "kibble", client=client).collect_once()
    assert set(paths) == {"/.well-known/agent.json", "/openapi.json", "/r/kibble"}
