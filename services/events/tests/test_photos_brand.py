"""Food photos + GateWay Delivery parent-brand lockups."""
import pytest
from fastapi.testclient import TestClient
from app.db import SessionLocal
from app.models import MenuItem, Partner
from app.main import app

client = TestClient(app)
K = "/api/board/test-key"


def test_real_menus_seeded_with_prices():
    db = SessionLocal()
    for code, min_items in (("burgerboys", 15), ("friendsbbq", 15), ("stephens", 25)):
        items = db.query(MenuItem).filter(MenuItem.partner_code == code).all()
        assert len(items) >= min_items, f"{code} has {len(items)}"
        assert all(i.price_cents > 0 for i in items)
    # spot-check verified real dishes
    names = {i.name for i in db.query(MenuItem).all()}
    assert "Kobe Burger" in names          # Burger Boys (Toast)
    assert any("Turkey Leg" in n for n in names)   # Friends BBQ (Uber Eats)
    assert any("Margherita" in n for n in names)   # Stephen's
    db.close()


def test_partner_stories_seeded():
    db = SessionLocal()
    for code in ("burgerboys", "friendsbbq", "stephens"):
        p = db.get(Partner, code)
        assert p.about_blurb and p.thank_you_note
    assert "Andre" in db.get(Partner, "burgerboys").thank_you_note
    assert "family" in db.get(Partner, "friendsbbq").about_blurb.lower()
    db.close()


def test_hero_photo_endpoint_validates_and_saves():
    assert client.post(f"{K}/partners/stephens/hero",
                       json={"url": "javascript:alert(1)"}).status_code == 400
    r = client.post(f"{K}/partners/stephens/hero",
                    json={"url": "https://example.com/pizza.jpg"})
    assert r.status_code == 200
    db = SessionLocal()
    assert db.get(Partner, "stephens").hero_url.endswith("pizza.jpg")
    db.close()
    assert client.get("/v0/partners/stephens").json()["hero_url"].endswith("pizza.jpg")


def test_item_photo_saves_and_serves_in_menu():
    db = SessionLocal()
    item = db.query(MenuItem).filter(MenuItem.partner_code == "stephens").first()
    iid = item.id
    db.close()
    r = client.post(f"{K}/partners/stephens/menu",
                    json={"id": iid, "image_url": "https://example.com/slice.jpg"})
    assert r.status_code == 200
    menu = client.get("/v0/partners/stephens/menu").json()
    urls = [i["image_url"] for c in menu["categories"] for i in c["items"]]
    assert "https://example.com/slice.jpg" in urls
    bad = client.post(f"{K}/partners/stephens/menu",
                      json={"id": iid, "image_url": "ftp://x/y.jpg"})
    assert bad.status_code == 400


def test_powered_by_gateway_delivery_lockups():
    for path in ("/", "/order", "/me"):
        html = client.get(path).text
        assert "Powered by" in html and "GateWay Delivery" in html
        assert "gwd-emblem.png" in html
    assert client.get("/static/gwd-emblem.png").status_code == 200
    assert client.get("/static/gwd-logo.png").status_code == 200


def test_photo_fallback_uses_emblem():
    html = client.get("/").text
    assert "gwd-emblem.png" in html          # no-photo restaurants show the brand mark
    form = client.get("/order?partner=stephens").text
    assert "gwd-emblem.png" in form
