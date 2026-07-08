"""Event Service law tests: append works, mutation paths do not exist."""
import os, tempfile
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_append_and_read():
    r = client.post("/v0/events", json={
        "event_type": "order.received",
        "entity_ref": "ORD-TEST0001",
        "tenant": "gateway",
        "actor": "pytest",
        "payload": '{"test": true}',
    })
    assert r.status_code == 201
    assert r.json()["event_type"] == "order.received"

    r2 = client.get("/v0/events", params={"entity_ref": "ORD-TEST0001"})
    assert r2.status_code == 200
    assert len(r2.json()) == 1


def test_no_mutation_paths_exist():
    """N-2: the append-only law is structural, not procedural."""
    eid = client.post("/v0/events", json={
        "event_type": "order.received", "entity_ref": "ORD-TEST0002"
    }).json()["id"]
    assert client.put(f"/v0/events/{eid}", json={}).status_code in (404, 405)
    assert client.delete(f"/v0/events/{eid}").status_code in (404, 405)
    assert client.patch(f"/v0/events/{eid}", json={}).status_code in (404, 405)


def test_event_type_format_enforced():
    r = client.post("/v0/events", json={"event_type": "NOT VALID", "entity_ref": "X"})
    assert r.status_code == 422
