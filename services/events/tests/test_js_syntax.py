"""Every inline <script> in every UI page must parse. A single JS syntax error
freezes an entire surface (see: the v0.8–v0.15 board rotate-token apostrophe).
Served HTML for token pages is also checked so template assembly stays valid."""
import re
import shutil
import subprocess
import tempfile
import os
import pytest

UI = os.path.join(os.path.dirname(__file__), "..", "app", "ui")
PAGES = ["board.html", "driver.html", "kitchen.html", "order-form.html", "home.html"]
STATIC_JS = ["static/gw-ui.js", "static/sw.js"]

node = shutil.which("node")


@pytest.mark.skipif(node is None, reason="node not installed")
@pytest.mark.parametrize("page", PAGES)
def test_inline_scripts_parse(page):
    src = open(os.path.join(UI, page)).read()
    scripts = re.findall(r"<script>(.*?)</script>", src, re.S)
    assert scripts, f"{page} has no inline script — unexpected"
    for i, sc in enumerate(scripts):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as t:
            t.write(sc)
            path = t.name
        try:
            r = subprocess.run([node, "--check", path], capture_output=True, text=True)
            assert r.returncode == 0, f"{page} script #{i} syntax error:\n{r.stderr[:500]}"
        finally:
            os.unlink(path)


@pytest.mark.skipif(node is None, reason="node not installed")
@pytest.mark.parametrize("path", STATIC_JS)
def test_static_js_parses(path):
    r = subprocess.run([node, "--check", os.path.join(UI, path)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[:500]


@pytest.mark.skipif(node is None, reason="node not installed")
def test_track_page_script_parses():
    import app.track as track_mod
    html = track_mod._HEAD + '<body data-oid="ORD-X">' + track_mod._MAP_SCRIPT
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    inline = [s for s in scripts if "unpkg" not in s and s.strip()]
    for i, sc in enumerate(inline):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as t:
            t.write(sc)
            path = t.name
        try:
            r = subprocess.run([node, "--check", path], capture_output=True, text=True)
            assert r.returncode == 0, f"track script #{i}:\n{r.stderr[:500]}"
        finally:
            os.unlink(path)
