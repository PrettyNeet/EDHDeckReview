"""Tests for Supabase invite auth dependency."""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.auth import AuthUser, _allow_cache, require_invited_user


def setup_function():
    _allow_cache.clear()


def _request():
    return SimpleNamespace(state=SimpleNamespace())


def _credentials():
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")


def test_requires_bearer_token_when_enabled():
    with patch("app.auth.auth_enabled", return_value=True):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(require_invited_user(_request(), None))

    assert exc.value.status_code == 401


def test_rejects_uninvited_user():
    with (
        patch("app.auth.auth_enabled", return_value=True),
        patch("app.auth._get_supabase_user", return_value=AuthUser(id="u1", email="user@example.com")),
        patch("app.auth._is_email_allowed", return_value=False),
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(require_invited_user(_request(), _credentials()))

    assert exc.value.status_code == 403


def test_allows_invited_user():
    request = _request()
    with (
        patch("app.auth.auth_enabled", return_value=True),
        patch("app.auth._get_supabase_user", return_value=AuthUser(id="u1", email="user@example.com")),
        patch("app.auth._is_email_allowed", return_value=True),
    ):
        user = asyncio.run(require_invited_user(request, _credentials()))

    assert user.email == "user@example.com"
    assert request.state.user.email == "user@example.com"
