"""Every nav item is a real page with its own URL.

The nav used to be tabs over one `/` document: `activeTab` state plus
`#app?tab=<id>` links. Shared links, reloads and Back all lost the page. The
router is small enough to have no test runner of its own, so, like the other
dashboard-contract tests, this reads the sources and runs lib/routes.js in node.

The path list must also stay clear of the prefixes Vite/nginx proxy to the API:
a page mounted at `/collector` would be swallowed by the media mount.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "dashboard", "src")
ROUTES = os.path.join(SRC, "lib", "routes.js")
APP = os.path.join(SRC, "App.jsx")

PROXIED_PREFIXES = ("/api", "/videos", "/thumbnails", "/collector", "/gallery", "/video", "/render")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _dump(expr):
    """Evaluate an expression against lib/routes.js in node."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script = (
        "const m = await import(process.argv[1]);"
        f"console.log(JSON.stringify({expr}));"
    )
    out = subprocess.run(
        [node, "--input-type=module", "-e", script, "file://" + ROUTES],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def test_every_tab_round_trips_through_its_path():
    paths = _dump("m.TAB_PATHS")
    for tab, path in paths.items():
        assert _dump(f"m.tabFromPath({json.dumps(path)})") == tab, tab
        # A trailing slash and different casing are the same page.
        assert _dump(f"m.tabFromPath({json.dumps(path + '/')})") == tab, path


def test_unknown_and_legacy_paths_land_on_home_not_a_blank_shell():
    assert _dump("m.tabFromPath('/no-such-page')") == "home"
    assert _dump("m.tabFromPath('/home')") == "home"
    # 'history' was the pre-redesign name of the Clip Gallery.
    assert _dump("m.normalizeTab('history')") == "gallery"
    assert _dump("m.normalizeTab('removed-tab')") == "home"


def test_page_paths_do_not_collide_with_proxied_api_prefixes():
    paths = _dump("m.TAB_PATHS")
    for tab, path in paths.items():
        for prefix in PROXIED_PREFIXES:
            # Vite's proxy matches by prefix: /video-collector would be proxied
            # as if it were /video/..., so a page may not merely start with one.
            assert not path.startswith(prefix), (tab, path, prefix)


def test_the_nav_ids_are_exactly_the_routed_pages():
    app = _read(APP)
    nav = app.split("const navItems = [", 1)[1].split("];", 1)[0]
    ids = re.findall(r"id: '([^']+)'", nav)
    assert ids == list(_dump("Object.keys(m.TAB_PATHS)"))


def test_app_reads_the_path_and_writes_history_on_navigation():
    app = _read(APP)
    assert "useState(() => tabFromPath(window.location.pathname))" in app
    # Back/Forward: the path is read again on popstate.
    assert "window.addEventListener('popstate'" in app
    # Clicking a page adds a history entry; the URL is not left behind.
    assert "history[replace ? 'replaceState' : 'pushState']" in app
    # A setActiveTab from a deep flow (project restore, tutorial) still
    # corrects the address bar.
    assert "window.history.replaceState(null, '', path + window.location.search" in app
    assert "document.title = pageTitle(activeTab)" in app


def test_old_hash_deep_links_redirect_to_the_page_path():
    app = _read(APP)
    effect = app.split("const DEEP_LINK_TABS", 1)[1].split("}, []);", 1)[0]
    # The clips-ready email still points at #app?tab=history.
    assert "'history'" in effect
    # It resolves to the Clip Gallery's path, not a hash.
    assert "normalizeTab(tab)" in effect
    assert "pathForTab(target)" in effect
