"""Menu system tests — seeds, public/admin split, upsert, 86ing, delete."""
import os, tempfile
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["ADMIN_KEY"] = "test-key"
os.environ["AIRTABLE_PAT"] = "fake-pat"

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
K = "/api/board/test-key"


def test_seeded_partners_and_menus():
    assert client.get("/v0/partners/burgerboys").json()["display_name"] == "Burger Boys & Friends BBQ"
    assert client.get("/v0/partners/stephens").json()["display_name"] == "Stephen's Pizzeria"
    m = client.get("/v0/partners/burgerboys/menu").json()
    names = [i["name"] for c in m["categories"] for i in c["items"]]
    assert "Kobe Burger" in names and "Pulled Pork Sandwich" in names and "Sweet Potato Pie" in names
    m2 = client.get("/v0/partners/stephens/menu").json()
    names2 = [i["name"] for c in m2["categories"] for i in c["items"]]
    assert 'Pepperoni Pizza 16"' in names2 and "Philly Cheesesteak" in names2


def test_menu_404_for_partner_without_menu():
    assert client.get("/v0/partners/asiacafe/menu").status_code == 404


def test_upsert_86_and_delete():
    r = client.post(f"{K}/partners/burgerboys/menu",
                    json={"name": "Banana Pudding", "price_cents": 425, "category": "Desserts"})
    assert r.status_code == 200
    iid = r.json()["id"]
    pub = client.get("/v0/partners/burgerboys/menu").json()
    assert any(i["name"] == "Banana Pudding" for c in pub["categories"] for i in c["items"])
    # price edit via upsert
    client.post(f"{K}/partners/burgerboys/menu", json={"id": iid, "price_cents": 475})
    # 86 it → gone from public, present in admin
    client.post(f"{K}/partners/burgerboys/menu", json={"id": iid, "available": False})
    pub = client.get("/v0/partners/burgerboys/menu").json()
    assert not any(i["name"] == "Banana Pudding" for c in pub["categories"] for i in c["items"])
    adm = client.get(f"{K}/partners/burgerboys/menu").json()
    item = [i for c in adm["categories"] for i in c["items"] if i["id"] == iid][0]
    assert item["available"] is False and item["price_cents"] == 475
    # delete
    assert client.delete(f"{K}/menu-items/{iid}").status_code == 200
    assert client.delete(f"{K}/menu-items/{iid}").status_code == 404


def test_menu_write_requires_key_and_name():
    assert client.post("/api/board/wrong/partners/burgerboys/menu",
                       json={"name": "x"}).status_code == 403
    assert client.post(f"{K}/partners/burgerboys/menu", json={}).status_code == 400
