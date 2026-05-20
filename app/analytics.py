"""Best-effort Supabase action logging."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
import urllib.error
import urllib.request
from dataclasses import asdict
from typing import Any

from fastapi import Request

from app.auth import AuthUser, _env


ACTION_LOG_TABLE = "user_action_logs"


def action_logging_enabled() -> bool:
    raw = _env("ACTION_LOGGING_ENABLED").lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    return bool(_env("SUPABASE_URL") and _env("SUPABASE_SERVICE_ROLE_KEY"))


def new_request_id() -> str:
    return uuid.uuid4().hex


def now_ms() -> float:
    return time.perf_counter() * 1000


def elapsed_ms(start_ms: float) -> int:
    return max(0, round(now_ms() - start_ms))


def request_metadata(request: Request) -> dict[str, Any]:
    return {
        "path": request.url.path,
        "method": request.method,
        "query": str(request.url.query or ""),
        "host": request.headers.get("host"),
        "referer": request.headers.get("referer"),
        "origin": request.headers.get("origin"),
        "vercel_region": os.environ.get("VERCEL_REGION"),
        "vercel": bool(os.environ.get("VERCEL")),
    }


def user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


def ip_hash(request: Request) -> str | None:
    raw_ip = (
        request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        or request.headers.get("x-real-ip")
        or (request.client.host if request.client else None)
    )
    if not raw_ip:
        return None
    salt = _env("ACTION_LOG_IP_HASH_SALT") or _env("SUPABASE_SERVICE_ROLE_KEY") or "deckreview"
    return hashlib.sha256(f"{salt}:{raw_ip}".encode("utf-8")).hexdigest()


def decklist_stats(decklist_text: str) -> dict[str, int]:
    lines = [line for line in decklist_text.splitlines() if line.strip()]
    return {
        "bytes": len(decklist_text.encode("utf-8", errors="replace")),
        "chars": len(decklist_text),
        "line_count": len(lines),
    }


def user_payload(user: AuthUser | None) -> dict[str, str | None]:
    if not user:
        return {"user_id": None, "user_email": None}
    return {"user_id": user.id, "user_email": user.email}


def log_event(
    event_type: str,
    *,
    user: AuthUser | None = None,
    request: Request | None = None,
    request_id: str | None = None,
    source: str | None = None,
    decklist_text: str | None = None,
    moxfield_url: str | None = None,
    moxfield_deck_id: str | None = None,
    moxfield_deck_name: str | None = None,
    commander: str | None = None,
    card_count: int | None = None,
    input_metadata: dict[str, Any] | None = None,
    result_summary: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    """Insert an action log row. Never raises."""
    if not action_logging_enabled():
        return

    base_url = _env("SUPABASE_URL").rstrip("/")
    service_key = _env("SUPABASE_SERVICE_ROLE_KEY")
    if not base_url or not service_key:
        return

    payload: dict[str, Any] = {
        "event_type": event_type,
        "request_id": request_id,
        "source": source,
        "decklist_text": decklist_text,
        "moxfield_url": moxfield_url,
        "moxfield_deck_id": moxfield_deck_id,
        "moxfield_deck_name": moxfield_deck_name,
        "commander": commander,
        "card_count": card_count,
        "input_metadata": input_metadata or {},
        "result_summary": result_summary or {},
        "diagnostics": diagnostics or {},
        "error": error,
    }
    payload.update(user_payload(user))
    if request is not None:
        payload["user_agent"] = user_agent(request)
        payload["ip_hash"] = ip_hash(request)
        payload["diagnostics"] = {
            **payload["diagnostics"],
            "request": request_metadata(request),
        }

    # Drop null values for optional scalar columns; keep JSON fields present.
    payload = {
        key: value for key, value in payload.items()
        if value is not None or key in {"input_metadata", "result_summary", "diagnostics"}
    }

    url = f"{base_url}/rest/v1/{ACTION_LOG_TABLE}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception as exc:
        print(f"analytics log failed for {event_type}: {exc}", file=os.sys.stderr)


def safe_error_payload(exc: Exception) -> dict[str, Any]:
    payload = {"type": type(exc).__name__, "message": str(exc)}
    status_code = getattr(exc, "status_code", None)
    detail = getattr(exc, "detail", None)
    if status_code is not None:
        payload["status_code"] = status_code
    if detail is not None:
        payload["detail"] = detail
    return payload


def auth_user_to_dict(user: AuthUser | None) -> dict[str, Any]:
    return asdict(user) if user else {}
