"""v1.9 — honest vision/roadmap page. Must never claim unbuilt features are live."""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_roadmap_page_serves():
    r = client.get("/roadmap")
    assert r.status_code == 200
    assert "not yet built" in r.text.lower() or "Vision" in r.text


def test_roadmap_is_explicitly_honest_about_being_unbuilt():
    body = client.get("/roadmap").text
    # must not read as a feature announcement — has to say plainly it's not live
    assert "not live in the app yet" in body or "roadmap" in body.lower()
    assert "Swarm" in body  # the founder's flagship concept is represented


def test_home_links_to_roadmap():
    home = client.get("/").text
    assert '/roadmap' in home
