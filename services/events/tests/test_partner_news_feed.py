"""v1.9.14 — a real, kitchen-authored news feed. Partners post their own
updates ('Back from vacation!'); shown on their storefront page and folded into
the home highlights rail. A real blog, not a static field."""
import os, json, tempfile
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["ADMIN_KEY"] = "test-key"

from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.models import Partner
from app import menu, growth

menu.seed_menus(); growth.migrate_brand_columns(); growth.seed_brands_and_demos()
client = TestClient(app)

db = SessionLocal()
_p = db.query(Partner).filter(Partner.code == "asiacafe").first()
TOKEN = _p.portal_token
db.close()


def test_kitchen_can_post_and_read_own_feed():
    r = client.post(f"/api/kitchen/{TOKEN}/posts", json={"text": "New winter menu is in!"})
    assert r.status_code == 200
    r2 = client.get(f"/api/kitchen/{TOKEN}/posts")
    posts = r2.json()["posts"]
    assert any("winter menu" in p["text"] for p in posts)


def test_empty_post_rejected():
    r = client.post(f"/api/kitchen/{TOKEN}/posts", json={"text": "   "})
    assert r.status_code == 400


def test_post_text_is_capped():
    r = client.post(f"/api/kitchen/{TOKEN}/posts", json={"text": "x" * 500})
    assert r.status_code == 200
    posts = client.get(f"/api/kitchen/{TOKEN}/posts").json()["posts"]
    assert len(posts[0]["text"]) <= 280


def test_public_feed_shows_the_posts():
    client.post(f"/api/kitchen/{TOKEN}/posts", json={"text": "Public feed check"})
    r = client.get("/v0/partners/asiacafe/posts")
    assert r.status_code == 200
    assert any("Public feed check" in p["text"] for p in r.json()["posts"])


def test_posts_are_scoped_per_partner():
    # a different partner's feed must never show asiacafe's posts
    db = SessionLocal()
    other = db.query(Partner).filter(Partner.code == "burgerboys").first()
    other_token = other.portal_token
    db.close()
    client.post(f"/api/kitchen/{TOKEN}/posts", json={"text": "Asia Cafe only post"})
    r = client.get(f"/api/kitchen/{other_token}/posts")
    assert not any("Asia Cafe only" in p["text"] for p in r.json()["posts"])


def test_kitchen_can_delete_own_post_only():
    client.post(f"/api/kitchen/{TOKEN}/posts", json={"text": "Delete me"})
    posts = client.get(f"/api/kitchen/{TOKEN}/posts").json()["posts"]
    pid = next(p["id"] for p in posts if p["text"] == "Delete me")
    r = client.delete(f"/api/kitchen/{TOKEN}/posts/{pid}")
    assert r.status_code == 200
    posts2 = client.get(f"/api/kitchen/{TOKEN}/posts").json()["posts"]
    assert not any(p["id"] == pid for p in posts2)


def test_posts_feed_into_global_highlights():
    client.post(f"/api/kitchen/{TOKEN}/posts", json={"text": "Highlights integration check"})
    hl = client.get("/v0/highlights").json()["highlights"]
    assert any(h["kind"] == "post" and "Highlights integration" in h["text"] for h in hl)


def test_order_form_renders_the_news_section():
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "app", "ui", "order-form.html")).read()
    assert 'id="partnerNews"' in src
    assert "function paintPartnerNews" in src


def test_home_highlights_show_richer_detail():
    h = open(os.path.join(os.path.dirname(__file__), "..",
                          "app", "ui", "home.html")).read()
    assert "hlkind" in h and "hlwhen" in h
    assert "width:290px" in h  # enlarged from 238px
