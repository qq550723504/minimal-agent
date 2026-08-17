from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_security_dashboard_contains_agent_chat_surface():
    page = (ROOT / "demos" / "park-security" / "index.html").read_text(encoding="utf-8")

    assert '<link rel="stylesheet" href="styles.css?v=20260814-2">' in page
    assert '<script type="module" src="app.js?v=20260814-9"></script>' in page
    assert "MOCK DATA" not in page
    assert "模拟时刻" not in page
    assert '<style>' not in page
    assert '<script>' not in page
    assert 'style=' not in page
    assert '<section class="kpis local-dashboard" id="local-kpis" aria-label="安防指标" hidden>' in page
    assert '<main class="dashboard local-dashboard" id="local-dashboard" hidden' in page
    app = (ROOT / "demos" / "park-security" / "app.js").read_text(encoding="utf-8")
    mock_data = (ROOT / "demos" / "park-security" / "mock-data.js").read_text(encoding="utf-8")
    styles = (ROOT / "demos" / "park-security" / "styles.css").read_text(encoding="utf-8")
    assert 'import { createInitialEvents, shiftContext } from "./mock-data.js";' in app
    assert 'get("demo") === "1"' in app
    assert 'hidden = !demoMode' in app
    assert 'local-dashboard' in page
    assert "export function createInitialEvents" in mock_data
    assert 'data-prompt="查看事件 event-fire-003 的详情"' in page
    assert 'data-prompt="查看事件 event-night-001 的详情"' in page
    assert 'raw ? formatPercent(state.events.length / raw) : "—"' in app
    assert 'evidenceSummaryLabels' in app
    assert 'After-hours access attempt denied.' in app
    assert '夜间门禁尝试被拒绝。' in app
    assert 'Person detected near laboratory door.' in app
    assert '实验室门附近检测到人员。' in app
    assert "[hidden] { display: none !important; }" in styles

    source = page + app
    for marker in (
        "园区智能运营 Agent",
        "/park-agent/",
        "chat-form",
        "chat-messages",
        "response_mode: stream",
        'response_mode: isStreamingEndpoint ? "stream" : "structured"',
        "/api/handle",
        "/api/handle/stream",
        "response.body.getReader",
        "energy_trend",
        "energy_ranking",
        "energy_peak",
        "energy_compare",
        "energy_alarm",
        "PARK_ENERGY_MCP_URL",
    ):
        assert marker in source
