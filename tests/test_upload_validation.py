"""Tests for deck upload validation."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.main import _validate_uploaded_deck_file


def _file(filename="deck.txt", content_type="text/plain"):
    return SimpleNamespace(filename=filename, content_type=content_type)


def test_upload_validation_accepts_txt_text_file():
    _validate_uploaded_deck_file(_file(), b"1 Sol Ring\n")


def test_upload_validation_rejects_non_txt_extension():
    with pytest.raises(HTTPException) as exc:
        _validate_uploaded_deck_file(_file(filename="deck.pdf", content_type="application/pdf"), b"%PDF")

    assert exc.value.status_code == 400


def test_upload_validation_rejects_empty_file():
    with pytest.raises(HTTPException) as exc:
        _validate_uploaded_deck_file(_file(), b"")

    assert exc.value.status_code == 400


def test_upload_validation_rejects_binary_file():
    with pytest.raises(HTTPException) as exc:
        _validate_uploaded_deck_file(_file(filename="deck.txt", content_type="text/plain"), b"a\x00b")

    assert exc.value.status_code == 400
