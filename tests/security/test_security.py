import os

from src.agent.security.input import redact_sensitive_text, sanitize_input


def test_sanitize_input_rejects_control_chars():
    try:
        sanitize_input("hello\x00world")
        assert False, "Expected ValueError"
    except ValueError:
        assert True


def test_redact_sensitive_text_email_and_phone():
    text = "请联系 admin@example.com 或电话 +86 138-0013-8000"
    safe_text = redact_sensitive_text(text)
    assert "[REDACTED]" in safe_text
    assert "admin@example.com" not in safe_text
    assert "+86" not in safe_text
