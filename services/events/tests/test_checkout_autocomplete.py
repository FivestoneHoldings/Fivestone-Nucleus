"""v1.9.21 — checkout fields wired for native autofill and the right mobile
keyboard. The main order-form checkout was missing autocomplete entirely, while
every other lead form (courier, drive-with-us, partner-with-us, support) already
had it — an isolated gap on the highest-traffic form in the app."""
import os
UI = os.path.join(os.path.dirname(__file__), "..", "app", "ui")


def _f(n):
    return open(os.path.join(UI, n)).read()


def test_checkout_name_field_autofills():
    o = _f("order-form.html")
    assert 'id="cn" name="customer_name" required placeholder="Alex Johnson" autocomplete="name"' in o


def test_checkout_phone_field_uses_numeric_keyboard_and_autofills():
    o = _f("order-form.html")
    assert 'id="cp" name="customer_phone" type="tel" inputmode="tel"' in o
    assert 'autocomplete="tel" required' in o


def test_checkout_address_field_autofills():
    o = _f("order-form.html")
    assert 'autocomplete="street-address"' in o


def test_recipient_phone_uses_numeric_keyboard():
    o = _f("order-form.html")
    assert 'id="dcp" name="dropoff_contact_phone" type="tel" inputmode="tel"' in o
