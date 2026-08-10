import hmac
import os
from typing import Dict, Optional

from fastapi import Cookie, Header, HTTPException, status


def _auth_required() -> bool:
    return os.getenv("AGENT_AUTH_REQUIRED", "false").strip().lower() in ("1", "true", "yes", "on")


def _api_keys() -> Dict[str, str]:
    entries = {}
    raw = os.getenv("AGENT_API_KEYS", "")
    for item in raw.split(","):
        if ":" not in item:
            continue
        user_id, key = item.split(":", 1)
        user_id = user_id.strip()
        key = key.strip()
        if user_id and user_id != "default" and key:
            entries[user_id] = key
    return entries


def _authenticate_api_key(api_key: Optional[str]) -> str:
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key required")

    try:
        candidate = api_key.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key") from exc

    for user_id, expected_key in _api_keys().items():
        if hmac.compare_digest(candidate, expected_key.encode("utf-8")):
            return user_id

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


def get_current_user(
    api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    session_token: Optional[str] = Cookie(default=None, alias="agent_session"),
) -> str:
    if not _auth_required():
        return "default"
    return _authenticate_api_key(api_key if api_key is not None else session_token)


def get_metrics_access(authorization: Optional[str] = Header(default=None, alias="Authorization")) -> str:
    if not _auth_required():
        return "metrics"
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer metrics token required")
    token = authorization[7:].strip()
    expected = os.getenv("AGENT_METRICS_API_KEY", "")
    if not expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Metrics API key is not configured")
    try:
        matches = hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8"))
    except UnicodeEncodeError:
        matches = False
    if not matches:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid metrics API key")
    return "metrics"
