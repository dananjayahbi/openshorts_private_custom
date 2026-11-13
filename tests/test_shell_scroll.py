"""The shell's scroll contract.

A page must never scroll the document: the shell is exactly one viewport, the
header/nav stay put, and each page owns at most one scroller. Two regressions
are easy to reintroduce in JSX and invisible in unit-free code:

* wrapping a component that already owns a scroller (Gallery) in another
  ``overflow-y-auto`` produced two nested scroll areas and hid the
  infinite-scroll sentinel from IntersectionObserver;
* putting a ``max-w-*`` on the scroll container itself moves its scrollbar to
  the middle of the window instead of the window edge.

This reads App.jsx/component sources, like the other dashboard-contract tests.
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "dashboard", "src")


def _read(path):
    with open(os.path.join(SRC, path), encoding="utf-8") as f:
        return f.read()


def test_the_shell_is_one_viewport_and_the_workspace_never_scrolls():
    app = _read("App.jsx")
    # Dynamic viewport height (mobile browser chrome), not 100vh.
    assert "h-screen supports-[height:100dvh]:h-[100dvh]" in app
    assert "flex-1 overflow-hidden relative" in app


def test_gallery_is_not_wrapped_in_a_second_scroller():
    app = _read("App.jsx")
    view = app.split("{activeTab === 'gallery' && (", 1)[1].split(")}", 1)[0]
    # <Gallery/> owns its own h-full overflow-y-auto: the wrapper must not.
    assert "overflow-y-auto" not in view
    assert "<Gallery />" in view


def test_settings_scroller_is_full_width():
    app = _read("App.jsx")
    scroller = [line for line in app.splitlines()
                if "w-full overflow-y-auto overscroll-contain" in line]
    assert scroller, "Settings' scroll container must span the window"
    # The reading column inside is full width too: pages are not letterboxed.
    assert 'className="w-full p-3 sm:p-6"' in app
    assert "max-w-2xl mx-auto p-4" not in app


def test_every_page_pane_contains_its_overscroll():
    """Chained scrolling is what makes an inner pane feel like a broken page."""
    for name in ("components/Gallery.jsx", "components/HomeDashboard.jsx",
                 "components/Collector.jsx", "components/ThumbnailStudio.jsx",
                 "components/BatchQueue.jsx"):
        assert "overscroll-contain" in _read(name), name


def test_youtube_studio_is_mounted():
    """The nav item existed while the view was imported but never rendered."""
    app = _read("App.jsx")
    assert "{activeTab === 'thumbnails' && (" in app
    assert "<ThumbnailStudio" in app


def test_pages_are_full_width():
    """No page is letterboxed inside a centered max-w container."""
    app = _read("App.jsx")
    for capped in ("max-w-6xl mx-auto", "max-w-5xl mx-auto",
                   "max-w-4xl mx-auto", "max-w-2xl mx-auto"):
        assert capped not in app, capped
    for name in ("components/HomeDashboard.jsx", "components/Gallery.jsx",
                 "components/ThumbnailStudio.jsx"):
        src = _read(name)
        assert "max-w-6xl mx-auto" not in src
        assert "max-w-5xl mx-auto" not in src
