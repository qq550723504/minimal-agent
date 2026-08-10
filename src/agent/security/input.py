import logging
import os
import re

from typing import Any

AUDIT_LOG_PATH = os.getenv("AGENT_AUDIT_LOG", "audit.log")

logger = logging.getLogger("agent.security")
logger.setLevel(logging.INFO)
if not logger.handlers:
    file_handler = logging.FileHandler(AUDIT_LOG_PATH)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

SENSITIVE_PATTERNS = [
    re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
    re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?){2,4}\d{2,4}\b"),
    re.compile(r"\b\d{15,18}\b"),
]
REDACTION = "[REDACTED]"


class ClientInputError(ValueError):
    """Raised when a request payload is invalid before execution starts."""


def sanitize_input(prompt: str, max_len: int = 1024) -> str:
    if not isinstance(prompt, str):
        raise ClientInputError("prompt must be a string")

    if "\x00" in prompt:
        raise ClientInputError("prompt contains disallowed NUL bytes")

    cleaned = prompt.strip()
    if len(cleaned) > max_len:
        raise ClientInputError("prompt is too long")
    if any(ord(c) < 32 and c not in ("\n", "\r", "\t") for c in cleaned):
        raise ClientInputError("prompt contains disallowed control characters")
    return cleaned


def redact_sensitive_text(text: str) -> str:
    safe_text = text
    for pattern in SENSITIVE_PATTERNS:
        safe_text = pattern.sub(REDACTION, safe_text)
    return safe_text


def audit_log(user_id: str, event: str, payload: Any) -> None:
    logger.info("%s %s %s", user_id, event, redact_sensitive_text(str(payload)))
