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
    # A single clip's delete button (hover) and the modal's delete both call it.
    assert "onDelete" in card
    assert "onDelete?.(clip)" in card


def test_delete_uses_an_in_app_confirmation_not_window_confirm():
    gallery = _read("components", "Gallery.jsx")
    modal = _read("components", "ConfirmDeleteModal.jsx")
    # The delete path no longer builds a confirm string or calls window.confirm
    # (archive-all, which keeps the files, still uses the browser prompt).
    assert "Delete ${label}?" not in gallery
    assert "requestDelete" in gallery
    assert "ConfirmDeleteModal" in gallery and "<ConfirmDeleteModal" in gallery
    # The dialog is the explanation plus the two decisions.
    assert "<Modal" in modal
    assert "btn-danger" in modal
    assert "keep it" in modal
    assert "cannot be undone" in modal


def test_the_confirmation_names_the_clips_that_go():
    modal = _read("components", "ConfirmDeleteModal.jsx")
    assert "clips.slice(0, 4)" in modal
    assert "clip.title" in modal
    assert "+{more} more" in modal


def test_the_delete_dialog_sits_above_the_player():
    modal = _read("components", "ConfirmDeleteModal.jsx")
    shell = _read("components", "ui", "Modal.jsx")
    clip = _read("components", "ClipModal.jsx")
    assert "layer=\"z-[140]\"" in modal
    assert "z-[130]" in clip
    assert "layer = 'z-[100]'" in shell


def test_bulk_delete_is_behind_a_confirm_and_a_delete_button():
    gallery = _read("components", "Gallery.jsx")
    assert "requestDelete(selectedClips)" in gallery
    assert "select all" in gallery
    assert "deleted" in gallery


def test_no_inline_metadata_wall_on_the_card():
    card = _read("components", "GalleryCard.jsx")
    for gone in ("handleCopy", "YouTube Title", "TikTok · IG Caption", "line-clamp-3"):
        assert gone not in card, gone
