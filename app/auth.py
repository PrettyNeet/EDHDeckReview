"""Supabase-backed invite gate for API access."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


_ENV_LOADED = False
_bearer = HTTPBearer(auto_error=False)
_allow_cache: dict[str, tuple[float, bool]] = {}
_ALLOW_CACHE_SECONDS = 60


@dataclass(frozen=True)
class AuthUser:
    id: str | None
    email: str | None
    role: str = "user"


def _strip_env_value(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value[0] in ("'", '"'):
        quote = value[0]
        end = value.find(quote, 1)
        if end != -1:
            return value[1:end]
        return value[1:]
    return value.split(" #", 1)[0].strip()


def _load_env_file() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    env_file = Path(__file__).resolve().parents[1] / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), _strip_env_value(value))

    _ENV_LOADED = True


def _env(name: str) -> str:
    _load_env_file()
    return os.environ.get(name, "").strip()


def auth_enabled() -> bool:
    raw = _env("INVITE_AUTH_ENABLED").lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    return bool(_env("SUPABASE_URL") and _env("SUPABASE_ANON_KEY") and _env("SUPABASE_SERVICE_ROLE_KEY"))


def public_config() -> dict[str, Any]:
    return {
        "auth_enabled": auth_enabled(),
        "supabase_url": _env("SUPABASE_URL"),
        "supabase_anon_key": _env("SUPABASE_ANON_KEY"),
    }


def _json_request(url: str, *, headers: dict[str, str]) -> Any:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=exc.code, detail=detail or exc.reason) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=503, detail=f"Auth service unavailable: {exc.reason}") from exc


def _get_supabase_user(token: str) -> AuthUser:
    base_url = _env("SUPABASE_URL").rstrip("/")
    anon_key = _env("SUPABASE_ANON_KEY")
    payload = _json_request(
        f"{base_url}/auth/v1/user",
        headers={
            "apikey": anon_key,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    email = str(payload.get("email") or "").strip().lower()
    return AuthUser(id=payload.get("id"), email=email or None)


def _is_email_allowed(email: str) -> bool:
    now = time.time()
    cached = _allow_cache.get(email)
    if cached and now - cached[0] < _ALLOW_CACHE_SECONDS:
        return cached[1]

    base_url = _env("SUPABASE_URL").rstrip("/")
    service_key = _env("SUPABASE_SERVICE_ROLE_KEY")
    encoded_email = urllib.parse.quote(email, safe="")
    url = (
        f"{base_url}/rest/v1/allowed_users"
        f"?select=email,active&email=eq.{encoded_email}&active=eq.true&limit=1"
    )
    payload = _json_request(
        url,
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Accept": "application/json",
        },
    )
    allowed = bool(payload)
    _allow_cache[email] = (now, allowed)
    return allowed


async def require_invited_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser:
    if not auth_enabled():
        return AuthUser(id=None, email=None, role="dev")

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required.")

    user = _get_supabase_user(credentials.credentials)
    if not user.email:
        raise HTTPException(status_code=401, detail="Authenticated user has no email.")

    if not _is_email_allowed(user.email):
        raise HTTPException(status_code=403, detail="This email is not invited to use this app.")

    request.state.user = user
    return user
