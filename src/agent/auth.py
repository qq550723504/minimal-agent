import hmac
import os
from typing import Dict, Optional

from fastapi import Header, HTTPException, status


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
        if user_id and key:
            entries[user_id] = key
    return entries


def get_current_user(api_key: Optional[str] = Header(default=None, alias="X-API-Key")) -> str:
    if not _auth_required():
        return "default"

    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key required")

    for user_id, expected_key in _api_keys().items():
        if hmac.compare_digest(api_key, expected_key):
            return user_id

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
