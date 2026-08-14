import { createInitialEvents, shiftContext } from "./mock-data.js";

    (() => {
      "use strict";

      const riskLabels = { low: "低风险", medium: "中风险", high: "高风险", critical: "严重风险" };
      const statusLabels = { open: "开放", confirmed: "已确认", work_order_created: "已建工单", closed: "已关闭" };
      const sourceLabels = { access_control: "门禁", video: "视频", patrol: "巡更", fire: "消防", device: "设备", shift: "值班", appointment: "预约" };
      const scenarioLabels = {
        night_abnormal_access: "夜间实验区异常门禁",
        access_failure_and_loitering: "园区入口访问失败与徘徊",
        fire_alarm_and_equipment_fault: "机房消防与设备故障"
      };
      const planLabels = {
        night_access_verification: "核验夜间门禁记录、访客预约和现场人员",
        verify_visitor_appointment_and_dispatch_patrol: "核验访客预约并派巡逻人员复核",
        fire_emergency_response: "启动消防应急响应，检查疏散区并处置通风设备故障"
      };
      const transitionLabels = { confirmed: "确认事件", work_order_created: "创建工单", closed: "关闭事件" };
      const nextStatus = { open: "confirmed", confirmed: "work_order_created", work_order_created: "closed" };
      const elements = {};

      const demoMode = new URLSearchParams(window.location.search).get("demo") === "1";
      function initialState() {
        return {
          events: demoMode ? createInitialEvents() : [],
          selectedEventId: demoMode ? "event-fire-003" : null,
          riskFilter: "all",
          statusFilter: "all",
          queryTime: demoMode ? "2026-08-11T01:00:00Z" : null,
          shiftContext: demoMode ? clone(shiftContext) : null
        };
      }
      let state = initialState();
      let pendingAction = null;

      function clone(value) { return JSON.parse(JSON.stringify(value)); }
      function byId(id) { return document.getElementById(id); }
      function setText(node, value) { node.textContent = value == null ? "—" : String(value); }
      function make(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = text;
        return node;
      }
      function formatTime(value) { return new Date(value).toISOString().replace("T", " ").slice(0, 16) + " UTC"; }
      function formatPercent(value) { return `${Math.round(value * 100)}%`; }
      function selectedEvent() { return state.events.find((event) => event.event_id === state.selectedEventId) || null; }
      function filteredEvents() {
        return state.events.filter((event) => (state.riskFilter === "all" || event.risk_level === state.riskFilter) && (state.statusFilter === "all" || event.status === state.statusFilter));
      }
      function ensureSelection(events) {
        if (!events.length) { state.selectedEventId = null; return; }
        if (!events.some((event) => event.event_id === state.selectedEventId)) state.selectedEventId = events[0].event_id;
      }

      function defaultAgentEndpoint() {
        const configured = new URLSearchParams(window.location.search).get("agent");
        if (configured) return configured;
        return window.location.port === "8088" ? "http://127.0.0.1:8000/api/handle" : "/api/handle";
      }

      function appendMessage(role, text) {
        const message = make("div", `message message-${role}`); message.append(make("div", "message-role", role === "user" ? "你" : "Agent"), make("p", "message-text", text)); elements.chatMessages.append(message); elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight; return message;
      }

      function responseStat(parent, label, value) {
        const stat = make("div", "response-stat"); stat.append(make("div", "response-stat-label", label), make("div", "response-stat-value", value)); parent.append(stat);
      }

      function energyItems(data) { return Array.isArray(data) ? data : Array.isArray(data?.items) ? data.items : []; }
      function energyValue(item, keys, fallback = "—") { for (const key of keys) if (item?.[key] != null) return item[key]; return fallback; }

      function renderEnergyTrend(wrapper, data) {
        const items = energyItems(data); const values = items.map((item) => Number(item.value)).filter(Number.isFinite); const max = Math.max(...values, 1);
        if (!items.length) { wrapper.append(make("div", "empty", "没有可展示的趋势点")); return; }
        const trend = make("div", "energy-trend"); items.slice(-12).forEach((item) => { const point = make("div", "energy-point"); const value = Number(item.value); const bar = make("div", "energy-bar"); bar.style.height = `${Math.max(8, Math.round((Number.isFinite(value) ? value : 0) / max * 70))}px`; point.append(bar, make("div", "energy-point-value", `${energyValue(item, ["value"])} ${item.unit || ""}`), make("div", "energy-point-label", String(energyValue(item, ["timestamp", "time"], "—")).slice(0, 10))); trend.append(point); }); wrapper.append(trend); if (data && typeof data === "object" && data.total != null) { const grid = make("div", "response-grid"); responseStat(grid, "累计能耗", `${data.total} ${data.unit || ""}`); wrapper.append(grid); }
      }

      function renderResponseBlock(block) {
        const wrapper = make("div", "response-block"); const title = make("div", "response-block-title"); const labels = { security_summary: "安防态势摘要", security_events: "事件列表", security_event_detail: "事件详情", shift_context: "值班与升级", energy_trend: "能耗趋势", energy_ranking: "能耗排名", energy_peak: "能耗峰值", energy_compare: "周期对比", energy_alarm: "能耗异常", tool_result: "工具结果", tool_error: "工具调用失败" }; title.append(make("span", "", labels[block.type] || block.type), make("span", "small", block.tool || "agent")); wrapper.append(title);
        const data = block.data;
        if (block.type === "security_summary" && data && typeof data === "object") {
          const grid = make("div", "response-grid"); responseStat(grid, "归并事件", data.total_events ?? 0); responseStat(grid, "严重风险", data.risk_counts?.critical ?? 0); responseStat(grid, "原始告警", data.raw_alarm_count ?? 0); wrapper.append(grid); return wrapper;
        }
        if (block.type === "security_events" && Array.isArray(data)) {
          const list = make("div", "response-list"); data.forEach((event) => { const item = make("div", "response-list-item"); item.append(make("strong", "", event.scenario || event.event_id), make("span", "", `${event.risk_level || ""} · ${event.status || ""}`)); list.append(item); }); wrapper.append(list); return wrapper;
        }
        if (block.type === "security_event_detail" && data && typeof data === "object") {
          const grid = make("div", "response-grid"); responseStat(grid, "事件", data.event_id || "—"); responseStat(grid, "风险", data.risk_level || "—"); responseStat(grid, "证据", data.evidence_completeness == null ? "—" : formatPercent(data.evidence_completeness)); wrapper.append(grid); if (Array.isArray(data.timeline)) { const list = make("div", "response-list"); data.timeline.slice(0, 4).forEach((item) => { const row = make("div", "response-list-item"); row.append(make("strong", "", sourceLabels[item.source] || item.source), make("span", "", item.summary || "")); list.append(row); }); wrapper.append(list); } return wrapper;
        }
        if (block.type === "shift_context" && data && typeof data === "object") {
          const grid = make("div", "response-grid"); responseStat(grid, "值班", data.on_duty_guard?.name || "无"); responseStat(grid, "状态", data.on_duty ? "值班中" : "无值班"); responseStat(grid, "重点区域", data.key_areas?.length ?? 0); wrapper.append(grid); return wrapper;
        }
        if (block.type === "energy_trend") { renderEnergyTrend(wrapper, data); return wrapper; }
        if (block.type === "energy_ranking") {
          const list = make("div", "response-list"); energyItems(data).slice(0, 8).forEach((item) => { const row = make("div", "response-list-item"); row.append(make("strong", "", energyValue(item, ["building_id", "meter_id", "name"])), make("span", "", `${energyValue(item, ["value", "total"])} ${item.unit || ""}`)); list.append(row); }); wrapper.append(list); return wrapper;
        }
        if (block.type === "energy_peak" && data && typeof data === "object") {
          const grid = make("div", "response-grid"); responseStat(grid, "峰值", `${energyValue(data, ["peak_value", "value"])} ${data.unit || ""}`); responseStat(grid, "发生时间", energyValue(data, ["peak_time", "timestamp"])); wrapper.append(grid); return wrapper;
        }
        if (block.type === "energy_compare" && data && typeof data === "object") {
          const grid = make("div", "response-grid"); responseStat(grid, "本期", `${energyValue(data, ["current_total", "currentTotal"])} ${data.unit || ""}`); responseStat(grid, "对比期", `${energyValue(data, ["compare_total", "baselineTotal"])} ${data.unit || ""}`); responseStat(grid, "变化率", energyValue(data, ["change_rate", "changePercent"])); wrapper.append(grid); return wrapper;
        }
        if (block.type === "energy_alarm" && data && typeof data === "object") {
          const grid = make("div", "response-grid"); responseStat(grid, "异常总数", energyValue(data, ["total"] , 0)); responseStat(grid, "严重", energyValue(data, ["critical"], 0)); responseStat(grid, "预警", energyValue(data, ["warning"], 0)); wrapper.append(grid); const items = energyItems(data); if (items.length) { const list = make("div", "response-list"); items.slice(0, 6).forEach((item) => { const row = make("div", "response-list-item"); row.append(make("strong", "energy-alarm", energyValue(item, ["code", "name"])), make("span", "", `${energyValue(item, ["count", "value"], 0)} 条`)); list.append(row); }); wrapper.append(list); } return wrapper;
        }
        const pre = make("pre", "response-json", typeof data === "string" ? data : JSON.stringify(data, null, 2)); wrapper.append(pre); return wrapper;
      }

      function appendAgentResponse(payload) {
        const message = appendMessage("assistant", payload.message || "Agent 已返回结果。");
        if (Array.isArray(payload.blocks)) payload.blocks.forEach((block) => message.append(renderResponseBlock(block)));
      }

      async function askAgent(prompt) {
        const cleanPrompt = String(prompt || "").trim(); if (!cleanPrompt) return;
        appendMessage("user", cleanPrompt); setText(elements.chatStatus, "Agent 正在查询安防能力…"); elements.chatStatus.classList.remove("error"); elements.chatSubmit.disabled = true;
        try {
          const endpoint = elements.agentEndpoint.value.trim() || defaultAgentEndpoint();
          const response = await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: cleanPrompt, response_mode: "structured" }) });
          if (!response.ok) throw new Error(`Agent 返回 HTTP ${response.status}`);
          const payload = await response.json(); appendAgentResponse(payload); setText(elements.chatStatus, `已完成 · run_id ${payload.run_id || "local"}`);
        } catch (error) { setText(elements.chatStatus, `${error.message}。请确认 Agent 已启动、能力开关已开启，并检查 API 地址。`); elements.chatStatus.classList.add("error"); appendMessage("assistant", "这次请求没有完成，我保留了本地模拟看板，你仍可以查看已有事件。"); }
        finally { elements.chatSubmit.disabled = false; }
      }

      function renderKpis() {
        const raw = state.events.reduce((sum, event) => sum + event.alarm_ids.length, 0);
        const urgent = state.events.filter((event) => event.risk_level === "critical" || event.risk_level === "high").length;
        setText(elements.kpiTotal, state.events.length); setText(elements.kpiCritical, urgent); setText(elements.kpiRaw, raw); setText(elements.kpiRate, raw ? formatPercent(state.events.length / raw) : "—");
      }

      function renderEventList() {
        const events = filteredEvents();
        ensureSelection(events);
        elements.eventList.replaceChildren();
        setText(elements.eventCount, `${events.length} 条`);
        if (!events.length) { elements.eventList.append(make("div", "empty", "没有匹配当前筛选条件的事件")); return; }
        events.forEach((event) => {
          const card = make("button", `event-card${event.event_id === state.selectedEventId ? " selected" : ""}`);
          card.type = "button"; card.dataset.eventId = event.event_id; card.setAttribute("aria-pressed", event.event_id === state.selectedEventId ? "true" : "false");
          const top = make("div", "event-card-top"); top.append(make("span", `badge badge-${event.risk_level}`, riskLabels[event.risk_level]), make("span", `badge badge-${event.status}`, statusLabels[event.status]));
          const title = make("h3", "", scenarioLabels[event.scenario]);
          const meta = make("div", "event-card-meta"); meta.append(make("span", "", event.area_id), make("span", "", formatTime(event.first_occurred_at)));
          card.append(top, title, meta); card.addEventListener("click", () => { state.selectedEventId = event.event_id; render(); }); elements.eventList.append(card);
        });
      }

      function addFact(grid, label, value) { const fact = make("div", "fact"); fact.append(make("div", "fact-label", label), make("div", "fact-value", value)); grid.append(fact); }
      function renderEventDetail() {
        const event = selectedEvent(); elements.eventDetail.replaceChildren();
        if (!event) { elements.eventDetail.append(make("div", "empty", "请选择一个事件查看详情")); return; }
        const head = make("div", "detail-head"); const titleWrap = make("div"); const title = make("div", "detail-title"); title.append(make("h2", "", scenarioLabels[event.scenario]), make("span", `badge badge-${event.risk_level}`, riskLabels[event.risk_level])); titleWrap.append(title, make("p", "detail-id", event.event_id)); head.append(titleWrap, make("span", `badge badge-${event.status}`, statusLabels[event.status])); elements.eventDetail.append(head);
        const grid = make("div", "detail-grid"); addFact(grid, "首次发生", formatTime(event.first_occurred_at)); addFact(grid, "最近发生", formatTime(event.last_occurred_at)); addFact(grid, "责任团队", event.responsible_party); addFact(grid, "证据完整度", formatPercent(event.evidence_completeness)); elements.eventDetail.append(grid);
        elements.eventDetail.append(make("div", "section-label", "影响范围")); const chips = make("div", "chips"); event.impact_scope.forEach((item) => chips.append(make("span", "chip", item))); elements.eventDetail.append(chips);
        elements.eventDetail.append(make("div", "section-label", "建议处置"), make("div", "recommendation", planLabels[event.recommended_plan] || event.recommended_plan));
        const actionRow = make("div", "action-row"); const next = nextStatus[event.status]; const action = make("button", `btn ${next === "closed" ? "btn-danger" : "btn-primary"}`, next ? transitionLabels[next] : "流程已完成"); action.type = "button"; action.disabled = !next; if (next) action.addEventListener("click", () => openActionDialog(event.event_id, next)); actionRow.append(action); elements.eventDetail.append(actionRow);
        setText(elements.notice, ""); elements.notice.classList.remove("error");
      }

      function renderTimeline() {
        const event = selectedEvent(); elements.timeline.replaceChildren(); elements.auditList.replaceChildren();
        if (!event) return;
        [...event.timeline].sort((a, b) => new Date(a.occurred_at) - new Date(b.occurred_at)).forEach((item) => {
          const row = make("div", "timeline-item"); row.append(make("span", "timeline-dot")); const body = make("div"); body.append(make("div", "timeline-source", sourceLabels[item.source] || item.source), make("div", "timeline-summary", item.summary), make("div", "timeline-ref", `${formatTime(item.occurred_at)} · ${item.reference}`)); row.append(body); elements.timeline.append(row);
        });
        event.audit_records.forEach((record) => { const item = make("div", "audit-item"); item.append(make("strong", "", record.action), make("span", "", ` · ${record.operator_id} · ${formatTime(record.occurred_at)}`)); if (record.note) item.append(make("div", "", record.note)); elements.auditList.append(item); });
        event.work_orders.forEach((order) => { const item = make("div", "audit-item"); item.append(make("strong", "", `工单 ${order.work_order_id}`), make("span", "", ` · ${order.status} · ${order.assignee}`)); elements.auditList.append(item); });
      }

      function renderShiftContext() {
        const context = state.shiftContext; elements.shiftPanel.replaceChildren();
        if (!context) { elements.shiftPanel.append(make("div", "empty", "尚未查询值班数据")); return; }
        const hero = make("div", "shift-hero"); const status = make("div", "shift-status"); status.append(make("span", "dot"), make("span", context.on_duty ? "当前值班中" : "当前无值班人员")); hero.append(status, make("div", "shift-person", context.on_duty_guard ? context.on_duty_guard.name : "未配置"), make("div", "small", context.on_duty_guard ? `${context.on_duty_guard.guard_id} · ${context.on_duty_guard.shift} 班 · ${formatTime(context.on_duty_guard.shift_start)} — ${formatTime(context.on_duty_guard.shift_end)}` : "当前时刻没有值班人员")); elements.shiftPanel.append(hero);
        elements.shiftPanel.append(make("div", "section-label", "重点负责区域")); const areas = make("div", "chips"); context.responsible_areas.forEach((area) => areas.append(make("span", "chip", area))); elements.shiftPanel.append(areas);
        elements.shiftPanel.append(make("div", "section-label", "升级规则")); Object.entries(context.escalation_rules).forEach(([level, rule]) => { const block = make("div", "rule"); const title = make("div", "rule-title"); title.append(make("strong", "", level === "level_1" ? "一级响应" : "二级响应"), make("span", "rule-time", `${rule.response_within_minutes} 分钟内`)); block.append(title, make("p", "", rule.condition), make("p", "", `通知：${rule.notify.join("、")}`)); elements.shiftPanel.append(block); });
      }

      function render() { renderKpis(); renderEventList(); renderEventDetail(); renderTimeline(); renderShiftContext(); }

      function openActionDialog(eventId, targetStatus) {
        pendingAction = { eventId, targetStatus }; setText(elements.dialogDescription, `将对 ${eventId} 执行“${transitionLabels[targetStatus]}”。这是浏览器内存中的模拟操作。`); elements.operatorInput.value = ""; elements.noteInput.value = ""; elements.actionDialog.showModal(); elements.operatorInput.focus();
      }

      function transitionEvent(eventId, targetStatus, operatorId, note) {
        const event = state.events.find((item) => item.event_id === eventId);
        if (!event) throw new Error("event_not_found");
        if (nextStatus[event.status] !== targetStatus) throw new Error("invalid_event_transition");
        if (!String(operatorId || "").trim() || !String(note || "").trim()) throw new Error("operator_and_note_required");
        const timestamp = targetStatus === "confirmed" ? "2026-08-11T01:15:00Z" : targetStatus === "work_order_created" ? "2026-08-11T01:20:00Z" : "2026-08-11T01:30:00Z";
        event.status = targetStatus; event.audit_records.push({ audit_id: `audit-${eventId}-${targetStatus}`, operator_id: String(operatorId).trim(), action: targetStatus, occurred_at: timestamp, note: String(note).trim() });
        if (targetStatus === "confirmed") event.confirmed_at = timestamp;
        if (targetStatus === "work_order_created") { event.work_order_id = `wo-${eventId}`; event.work_orders.push({ work_order_id: event.work_order_id, event_id: eventId, status: "open", assignee: event.responsible_party, operator_id: String(operatorId).trim(), created_at: timestamp, closed_at: null, note: String(note).trim() }); }
        if (targetStatus === "closed") { event.closed_at = timestamp; event.work_orders.forEach((order) => { order.status = "closed"; order.closed_at = timestamp; }); }
        render(); setNotice(`${transitionLabels[targetStatus]}完成：${eventId}`, false);
      }

      function setNotice(message, error) { setText(elements.notice, message); elements.notice.classList.toggle("error", Boolean(error)); }
      function reset() { state = initialState(); render(); setNotice(demoMode ? "已恢复模拟初始状态" : "已恢复空白状态", false); }

      function init() {
        elements.kpiTotal = byId("kpi-total"); elements.kpiCritical = byId("kpi-critical"); elements.kpiRaw = byId("kpi-raw"); elements.kpiRate = byId("kpi-rate"); elements.eventCount = byId("event-count"); elements.eventList = byId("event-list"); elements.eventDetail = byId("event-detail"); elements.timeline = byId("evidence-timeline"); elements.auditList = byId("audit-list"); elements.shiftPanel = byId("shift-panel"); elements.notice = document.createElement("div"); elements.notice.className = "notice"; elements.eventDetail.after(elements.notice); elements.riskFilter = byId("risk-filter"); elements.statusFilter = byId("status-filter"); elements.actionDialog = byId("action-dialog"); elements.actionForm = byId("action-form"); elements.dialogDescription = byId("dialog-description"); elements.operatorInput = byId("operator-input"); elements.noteInput = byId("note-input");
        elements.chatMessages = byId("chat-messages"); elements.chatForm = byId("chat-form"); elements.chatInput = byId("chat-input"); elements.chatSubmit = byId("chat-submit"); elements.chatStatus = byId("chat-status"); elements.agentEndpoint = byId("agent-endpoint"); elements.agentEndpoint.value = defaultAgentEndpoint();
        elements.riskFilter.addEventListener("change", (event) => { state.riskFilter = event.target.value; render(); }); elements.statusFilter.addEventListener("change", (event) => { state.statusFilter = event.target.value; render(); });
        elements.chatForm.addEventListener("submit", (event) => { event.preventDefault(); const prompt = elements.chatInput.value; elements.chatInput.value = ""; askAgent(prompt); }); document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => { elements.chatInput.value = button.dataset.prompt || ""; elements.chatInput.focus(); }));
        elements.actionForm.addEventListener("submit", (event) => { event.preventDefault(); if (event.submitter && event.submitter.value === "cancel") { elements.actionDialog.close(); return; } if (!pendingAction) return; try { if (!window.confirm(`确认执行“${transitionLabels[pendingAction.targetStatus]}”吗？`)) return; transitionEvent(pendingAction.eventId, pendingAction.targetStatus, elements.operatorInput.value, elements.noteInput.value); elements.actionDialog.close(); pendingAction = null; } catch (error) { setNotice(error.message === "operator_and_note_required" ? "请填写操作员和处置说明" : "当前状态不允许执行该操作", true); } });
        elements.actionDialog.addEventListener("close", () => { pendingAction = null; }); render();
        window.__parkSecurityDemo = { getState: () => clone(state), render, transitionEvent, reset, askAgent };
      }

      document.addEventListener("DOMContentLoaded", init);
    })();
