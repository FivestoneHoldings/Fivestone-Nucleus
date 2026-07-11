"""Payments seam. Stripe drops in here when the founder provides keys.
Until then: configured() is False, orders default to pay-at-the-door,
and the chosen method is recorded in the owned event log."""
import os

VALID_METHODS = ("cod",)          # "card" joins when Stripe lands
DEFAULT_METHOD = "cod"


def configured() -> bool:
    return bool(os.environ.get("STRIPE_SECRET_KEY"))


def normalize_method(raw: str) -> str:
    m = str(raw or "").strip().lower()
    return m if m in VALID_METHODS else DEFAULT_METHOD
