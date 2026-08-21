"""Shared order classification for operational reporting.

Founder-generated demo tickets exercise the real workflow on purpose, but they
must never look like customer volume or money.  Keep this rule in one place so
Command, kitchens, statements, exports, insights, and public impact all agree.
"""


def is_demo_order(record: dict) -> bool:
    return str(record.get("fields", {}).get("source_channel", "")).lower() == "demo"


def production_orders(records: list) -> list:
    return [record for record in records if not is_demo_order(record)]
