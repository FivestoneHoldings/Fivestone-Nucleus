"""Order-form served-markup contract: reordered flow keeps all fields; menu affordances present."""
import os
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_form_has_all_fields_in_new_order():
    html = client.get("/order").text
    # every intake field still present after reorder
    for name in ("items_description", "special_instructions", "dropoff_address",
                 "dropoff_contact_name", "dropoff_contact_phone",
                 "customer_name", "customer_phone", "pickup_address",
                 "requested_for", "subtotal_cents", "fee_cents", "tip_cents", "total_cents"):
        assert f'name="{name}"' in html, name


def test_form_section_order_food_first():
    html = client.get("/order").text
    # itemsFs (food) appears before whoFs (contact) before whenFs before pickupFs
    assert (html.index('id="itemsFs"') < html.index('id="deliverFs"')
            < html.index('id="whoFs"') < html.index('id="whenFs"')
            < html.index('id="pickupFs"'))


def test_menu_mode_hooks_present():
    html = client.get("/order").text
    assert 'id="recipientRow"' in html and 'id="itemsLeg"' in html
    assert 'readOnly' in html  # items becomes menu-driven in partner mode


def test_empty_states_branded():
    for path, token in [("/board/" + os.environ.get("ADMIN_KEY", "test-key"), "All clear"),
                        ("/driver/whatever", "caught up")]:
        assert token in client.get(path).text
