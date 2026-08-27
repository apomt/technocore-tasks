from fastapi.testclient import TestClient

from conftest import add_create, add_event
from technocore_tasks.config import Settings
from technocore_tasks.web import create_app


def client_for(store):
    settings = Settings(database=store.path, mode="hosted", collector_enabled=False)
    return TestClient(create_app(settings))


def test_task_and_did_search(store, dids):
    first = add_create(store, dids[0], title="Review Atlas", description="parser edge cases")
    second = add_create(store, dids[2], seq=2, nonce=101, title="Write docs")
    add_event(store, 3, dids[1], 102, "CLAIM", {"task": first})
    board = client_for(store).app.state.board
    assert [t.task_id for t in board.search("ATLAS")] == [first]
    assert [t.task_id for t in board.search(dids[1])] == [first]
    assert {t.task_id for t in board.did_tasks(dids[0])} == {first}
    assert second in {t.task_id for t in board.search("docs")}


def test_read_only_api_and_fact_boundaries(store, dids):
    task_id = add_create(store, dids[0], reward="advertised")
    with client_for(store) as client:
        response = client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["observed_signed_facts"]["creator_did"] == dids[0]
        assert body["advertised_unverified"] == {"reward": "advertised"}
        assert body["derived_state"]["state"] == "open"
        assert client.get(f"/api/did/{dids[0]}/tasks").json()["tasks"][0]["task_id"] == task_id
        assert client.get("/api/stats").json()["tasks"] == 1
        for route in client.app.routes:
            if getattr(route, "path", "").startswith("/api/") and route.path != "/api/docs":
                assert not ({"POST", "PUT", "PATCH", "DELETE"} & set(route.methods or ()))
        assert client.post("/api/tasks", json={}).status_code == 405
        assert client.get("/health").json()["signing"] is False


def test_hostile_html_is_escaped_and_result_url_is_inert(store, dids):
    title = '<img src=x onerror="alert(1)">'
    description = '<script>fetch("http://169.254.169.254")</script>'
    task_id = add_create(store, dids[0], title=title, description=description)
    add_event(store, 2, dids[1], 101, "CLAIM", {"task": task_id})
    add_event(store, 3, dids[0], 102, "ASSIGN", {"task": task_id, "assignee": dids[1]})
    result = "http://169.254.169.254/latest/meta-data/"
    add_event(store, 4, dids[1], 103, "COMPLETE", {"task": task_id, "result": result})
    with client_for(store) as client:
        home = client.get("/")
        detail = client.get(f"/task/{task_id}")
    assert "<script>" not in home.text and "&lt;script&gt;" in home.text
    assert "<img src=x" not in detail.text and "&lt;img src=x" in detail.text
    assert result in detail.text
    assert f'href="{result}"' not in detail.text
    assert "default-src 'self'" in detail.headers["content-security-policy"]
    assert "object-src 'none'" in detail.headers["content-security-policy"]
    assert "form-action 'self'" in detail.headers["content-security-policy"]


def test_ecosystem_page(store):
    with client_for(store) as client:
        page = client.get("/ecosystem")
    assert page.status_code == 200
    assert "Observe." in page.text and "Technocore Signal" in page.text
