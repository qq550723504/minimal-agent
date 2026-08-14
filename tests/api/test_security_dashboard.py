from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_security_dashboard_contains_agent_chat_surface():
    page = (ROOT / "demos" / "park-security" / "index.html").read_text(encoding="utf-8")

    for marker in (
        "园区智能运营 Agent",
        "/park-agent/",
        "chat-form",
        "chat-messages",
        "response_mode",
        "/api/handle",
        "energy_trend",
        "energy_ranking",
        "energy_peak",
        "energy_compare",
        "energy_alarm",
        "PARK_ENERGY_MCP_URL",
    ):
        assert marker in page
