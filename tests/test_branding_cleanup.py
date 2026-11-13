"""This private build carries no upstream branding.

The fork used to show the hosted product's surface: a GitHub star banner, a
repo link and contact address in the drawer, a "skill-autoshorts" clone card,
an SEO/OpenGraph block for openshorts.app, upstream screenshots and promo
videos. These guards keep the visible app branded as Clip Studio only.
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASH = os.path.join(REPO, "dashboard")
SRC = os.path.join(DASH, "src")


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def test_no_upstream_links_or_names_in_the_app_shell():
    app = _read(SRC, "App.jsx")
    assert "github.com/mutonby" not in app
    assert "info@openshorts.app" not in app
    assert "skill-autoshorts" not in app
    assert "clip studio" in app          # the wordmark
    assert "favicon.svg" in app
    assert "logo-openshorts" not in app


def test_index_html_is_a_local_app_not_an_seo_page():
    html = _read(DASH, "index.html")
    assert "<title>Clip Studio</title>" in html
    for gone in ("openshorts.app", "og:image", "twitter:card", "application/ld+json",
                 "OpenPanel", "__osAnalyticsInit"):
        assert gone not in html, gone


def test_marketing_components_and_assets_are_gone():
    for rel in ("src/components/StarBanner.jsx", "src/components/CookieBanner.jsx",
                "src/Legal.jsx", "public/logo-openshorts.png", "public/og-image.png",
                "public/op1.js", "public/screens", "public/demo"):
        assert not os.path.exists(os.path.join(DASH, *rel.split("/"))), rel
    for rel in ("glama.json", "server.json", "demo-openshorts.mp4"):
        assert not os.path.exists(os.path.join(REPO, rel)), rel


def test_the_mcp_card_points_at_this_install():
    card = _read(SRC, "components", "McpConnectCard.jsx")
    # The API runs on its own port and does not proxy /mcp: the snippet has to
    # come from /api/config, not a hard-coded hosted domain.
    assert "publicApiUrl" in card
    assert "mcp.openshorts.app" not in card
    assert "13 tools" in card


def test_media_attestation_has_no_dead_legal_links():
    src = _read(SRC, "components", "MediaInput.jsx")
    assert "I confirm I own this content" in src
    assert 'href="/terms"' not in src and 'href="/privacy"' not in src
