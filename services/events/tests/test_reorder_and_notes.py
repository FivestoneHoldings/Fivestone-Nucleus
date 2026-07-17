"""v1.9.17 — one-tap reorder from account history; prominent kitchen notes."""
import os
UI = os.path.join(os.path.dirname(__file__), "..", "app", "ui")


def _f(n):
    return open(os.path.join(UI, n)).read()


def test_account_history_has_reorder_link():
    m = _f("me.html")
    assert "Reorder ↻" in m
    assert "reorder=1" in m
    # gracefully hidden when no partner code is known
    assert "${x.partner?" in m


def test_kitchen_notes_are_prominent():
    k = _f("kitchen.html")
    # allergy/special notes are safety-critical — must stand out
    assert "border-left:4px solid #e08a1e" in k
    assert "font-weight:700" in k.split(".notes{")[1][:120]
