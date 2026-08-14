from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_security_dashboard_contains_agent_chat_surface():
    page = (ROOT / "demos" / "park-security" / "index.html").read_text(encoding="utf-8")

    assert '<link rel="stylesheet" href="styles.css">' in page
    assert '<script type="module" src="app.js"></script>' in page
    assert '<style>' not in page
    assert '<script>' not in page
    assert 'style=' not in page
    app = (ROOT / "demos" / "park-security" / "app.js").read_text(encoding="utf-8")
    mock_data = (ROOT / "demos" / "park-security" / "mock-data.js").read_text(encoding="utf-8")
    assert 'import { createInitialEvents, shiftContext } from "./mock-data.js";' in app
    assert 'get("demo") === "1"' in app
    assert "export function createInitialEvents" in mock_data
    assert "event-fire-003" not in page
    assert 'raw ? formatPercent(state.events.length / raw) : "—"' in app

    source = page + app
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
        assert marker in source
