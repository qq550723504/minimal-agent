from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_security_dashboard_contains_agent_chat_surface():
    page = (ROOT / "demos" / "park-security" / "index.html").read_text(encoding="utf-8")

    for marker in ("chat-form", "chat-messages", "response_mode", "/api/handle"):
        assert marker in page

