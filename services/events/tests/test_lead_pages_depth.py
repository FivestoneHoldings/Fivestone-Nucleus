"""v1.6 continued — THE PARTNER AND DRIVER PAGES SHOULD SELL WITHOUT US.

Founder: 'The partner tab should sound more professional and go deeper in
depth. The driver tab can be more fun and personal but also very in depth.
Those pages should weed out and make the sale without us.'
"""
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")
UI = os.path.join(ROOT, "app", "ui")


def _page(name):
    return open(os.path.join(UI, name)).read()


def test_partner_page_explains_how_it_actually_works():
    p = _page("lead-merchant.html")
    assert "How it works" in p
    for step in ("Send us your menu", "We build your storefront",
                "walkthrough", "You're live"):
        assert step in p


def test_partner_page_gives_an_honest_comparison_not_just_a_pitch():
    """A page that only says 'we're great' doesn't answer the question a real
    restaurant owner is actually asking: great COMPARED TO WHAT."""
    p = _page("lead-merchant.html")
    assert 'class="cmp"' in p
    assert "The big apps" in p
    assert "we're not claiming to out-scale" in p.lower() or "not claiming to out-scale" in p


def test_partner_page_answers_real_objections_before_theyre_asked():
    p = _page("lead-merchant.html")
    for q in ("What does it cost?", "Do I need my own delivery drivers?",
             "Can I change my menu myself?", "already have a POS"):
        assert q in p


def test_partner_page_never_invents_a_fake_testimonial():
    """A fabricated customer quote would be dishonest, not persuasive.
    Everything on this page must be a structural fact GateWay can back."""
    p = _page("lead-merchant.html")
    # no quote-attribution patterns like a name + a review
    assert '"—' not in p and "5 stars" not in p and "★★★★★" not in p


def test_driver_page_is_fun_but_still_answers_real_questions():
    d = _page("lead-driver.html")
    for q in ("Do I need my own car?", "Is this full-time or side money?",
             "How do I actually get paid?", "Can I say no to a run?"):
        assert q in d


def test_driver_page_walks_through_a_real_shift():
    d = _page("lead-driver.html")
    assert "How a shift actually goes" in d
    for step in ("Tell us you're in", "Claim a day sheet",
                "Pick up, deliver, repeat", "Cash out"):
        assert step in d


def test_driver_page_keeps_the_100_percent_tip_promise_consistent():
    """This promise appears on /me, /drive-with-us, and the courier page — it
    must never contradict itself across surfaces."""
    d = _page("lead-driver.html")
    assert "100% yours" in d or "100%" in d


def test_both_pages_have_working_faq_accordions():
    for name in ("lead-merchant.html", "lead-driver.html"):
        p = _page(name)
        assert '<details class="faq">' in p
        assert "<summary>" in p


def test_neither_page_lost_its_working_lead_form():
    """The content deepening must not have broken the actual conversion
    mechanism underneath it."""
    for name, kind in [("lead-merchant.html", "merchant"), ("lead-driver.html", "driver")]:
        p = _page(name)
        assert 'id="formCard"' in p
        assert "sendLead" in p
        assert f"kind:'{kind}'" in p or f'kind: \'{kind}\'' in p
