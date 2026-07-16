"""v1.9 — items whose NAME contains a double-quote (Stephen's 'Personal Pizza
10\"', 'Extra Large Pizza 16\"') used to break their own onclick attribute,
shattering the +/- and special-request buttons. Handlers now take only the item
id and look name/price up from a client-side index — no name interpolation into
markup at all, so the whole quote-injection class is gone.
"""
import os

UI = os.path.join(os.path.dirname(__file__), "..", "app", "ui")


def _f(n):
    return open(os.path.join(UI, n)).read()


def test_bump_takes_only_id_not_name_or_price():
    o = _f("order-form.html")
    # the fragile signature is gone
    assert "bump('${i2.id}',-1)" in o
    assert "bump('${i2.id}',1)" in o
    # and no name/price is interpolated into the bump onclick anymore
    assert "bump('${i2.id}','${nm2" not in o


def test_itemnote_takes_only_id():
    o = _f("order-form.html")
    assert "itemNote('${i2.id}')" in o
    assert "itemNote('${i2.id}','${nm2" not in o


def test_item_index_built_for_lookups():
    o = _f("order-form.html")
    assert "window._ITEMS" in o
    assert "function bump(id, d)" in o
    assert "async function itemNote(id)" in o


def test_bump_and_itemnote_resolve_name_from_index():
    o = _f("order-form.html")
    assert "window._ITEMS && window._ITEMS[id]" in o
