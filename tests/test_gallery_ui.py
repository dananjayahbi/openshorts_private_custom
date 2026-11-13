"""Clip Gallery: compact tiles, a full-viewport player, score, delete.

The gallery used to play every clip inline and unpack its title/caption/tags
on each card. These read the JSX: there is no JS test runner here, and the
wiring (poster tile, modal, selection, delete endpoints) is what regresses.
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "dashboard", "src")


def _read(*parts):
    with open(os.path.join(SRC, *parts), encoding="utf-8") as f:
        return f.read()


def test_a_card_is_a_still_not_a_video():
    card = _read("components", "GalleryCard.jsx")
    assert "onOpen" in card
    # The tile is a JPEG poster. It must not be a <video>: a browser download
    # manager treats every video source as a file to save, so painting the
    # grid opened a shelf of MP4 downloads.
    assert "<video" not in card
    assert "<img" in card
    assert "clip.poster" in card
    assert "loading=\"lazy\"" in card
    assert "aspect-square" in card


def test_the_home_page_tiles_are_stills_too():
    home = _read("components", "HomeDashboard.jsx")
    assert "<video" not in home
    assert "<img" in home
    assert "clip.poster" in home


def test_only_the_modal_player_loads_video_bytes():
    for name in ("GalleryCard.jsx", "HomeDashboard.jsx"):
        assert "<video" not in _read("components", name), name
    assert "<video" in _read("components", "ClipModal.jsx")


def test_clicking_opens_the_full_viewport_modal():
    gallery = _read("components", "Gallery.jsx")
    modal = _read("components", "ClipModal.jsx")
    assert "ClipModal" in gallery and "<ClipModal" in gallery
    assert "onOpen={setActive}" in gallery
    assert "fixed inset-0" in modal
    assert "<video" in modal and "controls" in modal
    assert "Escape" in modal
    assert "body.style.overflow" in modal


def test_the_viral_score_is_shown_on_the_card():
    card = _read("components", "GalleryCard.jsx")
    assert "clip.score" in card
    assert "scoreTone" in card


def test_single_and_bulk_delete_are_wired():
    gallery = _read("components", "Gallery.jsx")
    card = _read("components", "GalleryCard.jsx")
    assert "/api/gallery/delete" in gallery
    assert "selected" in gallery and "selectMode" in gallery
    assert "delete ({selected.size})" in gallery
    assert "window.confirm" in gallery
    # A single clip's delete button (hover) and the modal's delete both call it.
    assert "onDelete" in card
    assert "onDelete?.(clip)" in card


def test_bulk_delete_is_behind_a_confirm_and_a_delete_button():
    gallery = _read("components", "Gallery.jsx")
    assert "Delete ${label}?" in gallery
    assert "select all" in gallery
    assert "deleted" in gallery


def test_no_inline_metadata_wall_on_the_card():
    card = _read("components", "GalleryCard.jsx")
    for gone in ("handleCopy", "YouTube Title", "TikTok · IG Caption", "line-clamp-3"):
        assert gone not in card, gone
