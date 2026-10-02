from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from http import HTTPStatus
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .capabilities import CapabilityManager
from .evidence import EvidenceManager
from .gates import HumanQuestionGateManager
from .handoffs import HandoffManager
from .operator import OperatorManager
from .store import CockpitStore


_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MADO Cockpit</title>
<style>
:root {
  color-scheme: dark;
  --bg: #081019;
  --panel: #0d1824;
  --panel-2: #111f2e;
  --line: #22354a;
  --muted: #8ca0b4;
  --text: #edf5fb;
  --accent: #8cf7c3;
  --accent-2: #7bc4ff;
  --warn: #ffd479;
  --danger: #ff8a8a;
  --violet: #c9a7ff;
  --shadow: 0 18px 60px rgba(0,0,0,.28);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  background:
    radial-gradient(circle at 15% 0%, rgba(80,170,220,.14), transparent 32rem),
    radial-gradient(circle at 92% 10%, rgba(116,238,184,.10), transparent 28rem),
    var(--bg);
  color: var(--text);
  font: 14px/1.45 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
button, input, textarea { font: inherit; }
input {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: #0d1824;
  color: var(--text);
  padding: 9px 10px;
  outline: none;
}
input:focus { border-color: #42617f; }
button {
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #142337;
  color: var(--text);
  padding: 8px 12px;
  cursor: pointer;
}
button:hover { border-color: #42617f; }
button.primary {
  background: #153c35;
  border-color: #2c6d59;
  color: #d8fff0;
}
button.warn {
  background: #402f15;
  border-color: #755b24;
  color: #ffe9b2;
}
button:disabled { opacity: .45; cursor: default; }
.shell {
  display: grid;
  grid-template-columns: 230px minmax(0,1fr);
  min-height: 100vh;
}
aside {
  position: sticky;
  top: 0;
  height: 100vh;
  border-right: 1px solid var(--line);
  background: rgba(8,16,25,.88);
  backdrop-filter: blur(18px);
  padding: 20px 15px;
  overflow: auto;
}
.brand {
  display: flex;
  gap: 10px;
  align-items: center;
  margin: 2px 4px 24px;
}
.logo {
  width: 34px;
  height: 34px;
  border: 1px solid #4e718d;
  border-radius: 11px;
  display: grid;
  place-items: center;
  box-shadow: inset 0 0 18px rgba(123,196,255,.12);
}
.brand strong { font-size: 15px; letter-spacing: .04em; }
.brand small { color: var(--muted); display: block; margin-top: 2px; }
.nav-title {
  color: #668099;
  font-size: 11px;
  letter-spacing: .12em;
  text-transform: uppercase;
  margin: 18px 8px 8px;
}
.mission {
  padding: 10px 11px;
  border-radius: 10px;
  color: #c9d9e8;
  cursor: pointer;
  border: 1px solid transparent;
  margin: 4px 0;
}
.mission:hover { background: #0f1d2b; }
.mission.active {
  background: #132638;
  border-color: #28465f;
  color: #fff;
}
.mission span {
  display: block;
  color: var(--muted);
  font-size: 11px;
  margin-top: 3px;
}
main { padding: 22px; min-width: 0; }
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 18px;
}
.topbar h1 {
  font-size: 19px;
  margin: 0;
  letter-spacing: .02em;
}
.subtitle { color: var(--muted); margin-top: 3px; }
.local-pill {
  display: inline-flex;
  gap: 7px;
  align-items: center;
  border: 1px solid #28495b;
  border-radius: 999px;
  padding: 7px 10px;
  color: #bcd6e5;
  background: #0d1d28;
}
.dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 12px rgba(140,247,195,.65);
}
.stats {
  display: grid;
  grid-template-columns: repeat(6, minmax(110px,1fr));
  gap: 10px;
  margin-bottom: 14px;
}
.stat {
  background: linear-gradient(160deg, rgba(17,31,46,.96), rgba(12,23,35,.96));
  border: 1px solid var(--line);
  border-radius: 13px;
  padding: 13px;
  box-shadow: var(--shadow);
}
.stat .n { font-size: 23px; font-weight: 700; }
.stat .k { color: var(--muted); font-size: 11px; margin-top: 2px; }
.grid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(290px, .65fr);
  gap: 14px;
}
.panel {
  background: rgba(13,24,36,.93);
  border: 1px solid var(--line);
  border-radius: 15px;
  box-shadow: var(--shadow);
  overflow: hidden;
}
.panel-head {
  padding: 13px 15px;
  border-bottom: 1px solid var(--line);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}
.panel-head h2 {
  margin: 0;
  font-size: 13px;
  letter-spacing: .05em;
}
.panel-head span { color: var(--muted); font-size: 11px; }
.panel-body { padding: 13px; }
.operator-list {
  display: grid;
  gap: 10px;
}
.operator {
  border: 1px solid #24394f;
  background: #0d1a27;
  border-radius: 12px;
  padding: 13px;
}
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.operator .objective {
  margin: 8px 0 10px;
  color: #d3e3ef;
}
.meta {
  display: flex;
  gap: 7px;
  flex-wrap: wrap;
}
.badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 7px;
  border: 1px solid #2b4258;
  border-radius: 999px;
  color: #abc0d2;
  font-size: 11px;
}
.badge.good { color: var(--accent); border-color: #285644; }
.badge.warn { color: var(--warn); border-color: #604c27; }
.badge.danger { color: var(--danger); border-color: #623838; }
.badge.violet { color: var(--violet); border-color: #4d3e67; }
.actions { margin-top: 11px; display: flex; gap: 7px; }
.gate {
  border: 1px solid #654f28;
  border-radius: 12px;
  background: linear-gradient(160deg, #211b10, #15180f);
  padding: 12px;
  margin-bottom: 10px;
}
.gate:last-child { margin-bottom: 0; }
.gate .question { font-weight: 650; margin-bottom: 7px; }
.gate .reason { color: #c5b994; font-size: 12px; margin-bottom: 9px; }
.choice-grid { display: grid; gap: 7px; margin-top: 9px; }
.choice-btn { text-align: left; }
.choice-impact { color: #a89b79; font-size: 11px; display: block; margin-top: 3px; }
.section-spacer { height: 14px; }
.worker-grid {
  display: grid;
  grid-template-columns: repeat(2,minmax(0,1fr));
  gap: 9px;
}
.worker {
  background: #0d1a27;
  border: 1px solid #23374a;
  border-radius: 11px;
  padding: 11px;
}
.worker small { color: var(--muted); display: block; margin-top: 4px; }
.cap-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 7px;
}
.cap {
  padding: 3px 6px;
  border-radius: 7px;
  background: #132537;
  border: 1px solid #294861;
  color: #bfe1f8;
  font-size: 10px;
}
.event-spine {
  max-height: 460px;
  overflow: auto;
}
.event {
  position: relative;
  display: grid;
  grid-template-columns: 145px minmax(0,1fr);
  gap: 12px;
  padding: 9px 10px 9px 20px;
  border-bottom: 1px solid rgba(34,53,74,.7);
}
.event::before {
  content: "";
  position: absolute;
  left: 8px;
  top: 15px;
  width: 6px; height: 6px; border-radius: 50%;
  background: #51718b;
}
.event:last-child { border-bottom: 0; }
.event .type { color: #d6e6f2; font-size: 12px; }
.event .when { color: var(--muted); font-size: 10px; margin-top: 2px; }
.event .subject {
  color: #9fb4c7;
  font: 11px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace;
  word-break: break-word;
}
.empty {
  color: var(--muted);
  padding: 20px 10px;
  text-align: center;
}
.toast {
  position: fixed;
  right: 18px;
  bottom: 18px;
  min-width: 250px;
  max-width: 430px;
  background: #142536;
  border: 1px solid #31536d;
  border-radius: 11px;
  padding: 11px 13px;
  box-shadow: var(--shadow);
  display: none;
  z-index: 20;
}
.toast.error { border-color: #754247; color: #ffd5d8; }
@media (max-width: 1080px) {
  .stats { grid-template-columns: repeat(3,1fr); }
  .grid { grid-template-columns: 1fr; }
}
@media (max-width: 760px) {
  .shell { grid-template-columns: 1fr; }
  aside { position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--line); }
  main { padding: 14px; }
  .stats { grid-template-columns: repeat(2,1fr); }
  .worker-grid { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<div class="shell">
  <aside>
    <div class="brand">
      <div class="logo">M</div>
      <div><strong>MADO Cockpit</strong><small>local control plane</small></div>
    </div>
    <div class="nav-title">Missions</div>
    <div id="missions"></div>
    <div class="nav-title">Controls</div>
    <div class="mission active" id="all-missions">All missions<span>full production view</span></div>
  </aside>
  <main>
    <div class="topbar">
      <div>
        <h1 id="project-name">MADO Cockpit</h1>
        <div class="subtitle" id="project-root">Loading local state…</div>
      </div>
      <div style="display:flex;gap:8px;align-items:center">
        <span class="local-pill"><i class="dot"></i> localhost only</span>
        <button id="refresh">Refresh</button>
      </div>
    </div>
    <div class="stats" id="stats"></div>
    <div class="grid">
      <div>
        <section class="panel">
          <div class="panel-head"><h2>Operators</h2><span id="operator-count"></span></div>
          <div class="panel-body"><div class="operator-list" id="operators"></div></div>
        </section>
        <div class="section-spacer"></div>
        <section class="panel">
          <div class="panel-head"><h2>Workers & Capabilities</h2><span>bound execution surface</span></div>
          <div class="panel-body"><div class="worker-grid" id="workers"></div></div>
        </section>
        <div class="section-spacer"></div>
        <section class="panel">
          <div class="panel-head"><h2>Event Spine</h2><span id="event-count"></span></div>
          <div class="event-spine" id="events"></div>
        </section>
      </div>
      <div>
        <section class="panel">
          <div class="panel-head"><h2>Human Gates</h2><span id="gate-count"></span></div>
          <div class="panel-body" id="gates"></div>
        </section>
        <div class="section-spacer"></div>
        <section class="panel">
          <div class="panel-head"><h2>Production Evidence</h2><span>latest control signals</span></div>
          <div class="panel-body" id="production"></div>
        </section>
      </div>
    </div>
  </main>
</div>
<div class="toast" id="toast"></div>
<script>
const TOKEN = "__MADO_TOKEN__";
let dashboard = null;
let missionFilter = null;

const el = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "")
  .replaceAll("&","&amp;")
  .replaceAll("<","&lt;")
  .replaceAll(">","&gt;")
  .replaceAll('"',"&quot;");

function badge(text, tone="") {
  return '<span class="badge '+tone+'">'+esc(text)+'</span>';
}
function operatorTone(status) {
  if (status === "completed") return "good";
  if (status === "awaiting_human" || status === "needs_fix") return "warn";
  if (status === "blocked" || status === "failed") return "danger";
  return "";
}
function timeText(value) {
  if (!value) return "";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString();
}
function showToast(message, error=false) {
  const node = el("toast");
  node.textContent = message;
  node.className = "toast" + (error ? " error" : "");
  node.style.display = "block";
  setTimeout(() => node.style.display = "none", 3200);
}
async function api(path, options={}) {
  const config = {...options};
  config.headers = {
    "Content-Type": "application/json",
    ...(config.headers || {})
  };
  if ((config.method || "GET") !== "GET") {
    config.headers["X-Mado-Cockpit-Token"] = TOKEN;
  }
  const response = await fetch(path, config);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || response.statusText);
  return payload;
}
function filtered(items) {
  if (!missionFilter) return items;
  return items.filter((item) => {
    const planMission = item?.plan?.mission_id;
    const ownMission = item?.mission_id;
    return planMission === missionFilter || ownMission === missionFilter;
  });
}
function renderMissions() {
  const missions = dashboard.missions || [];
  el("missions").innerHTML = missions.map(m =>
    '<div class="mission '+(missionFilter===m.id?"active":"")+'" data-mission="'+esc(m.id)+'">'+
      '<strong>'+esc(m.title)+'</strong><span>'+esc(m.id)+'</span></div>'
  ).join("") || '<div class="empty">No missions</div>';
  el("all-missions").classList.toggle("active", !missionFilter);
}
function renderStats() {
  const openGates = dashboard.gates.filter(g => g.status.status === "open").length;
  const activeOps = dashboard.operators.filter(o => !["completed","blocked","failed"].includes(o.state.status)).length;
  const stats = [
    [dashboard.missions.length, "missions"],
    [activeOps, "active operators"],
    [dashboard.workers.length, "workers"],
    [openGates, "open human gates"],
    [dashboard.evidence.bundle_count || 0, "evidence bundles"],
    [dashboard.events.length, "recent events"],
  ];
  el("stats").innerHTML = stats.map(([n,k]) =>
    '<div class="stat"><div class="n">'+esc(n)+'</div><div class="k">'+esc(k)+'</div></div>'
  ).join("");
}
function renderOperators() {
  const ops = filtered(dashboard.operators);
  el("operator-count").textContent = ops.length + " visible";
  el("operators").innerHTML = ops.map(op => {
    const s = op.state.status;
    const next = op.next_action || "inspect";
    const mission = op.plan.mission_id;
    const canAdvance = !["completed","blocked","failed","awaiting_human"].includes(s);
    const gate = op.human_gate ? badge("human gate", "warn") : "";
    return '<article class="operator">'+
      '<div class="row"><strong>'+esc(op.plan.id)+'</strong>'+badge(s, operatorTone(s))+'</div>'+
      '<div class="objective">'+esc(op.plan.objective)+'</div>'+
      '<div class="meta">'+badge(mission)+badge("next: "+next, s==="awaiting_human"?"warn":"")+gate+'</div>'+
      '<div class="actions">'+
        '<button data-advance="'+esc(op.plan.id)+'" '+(canAdvance?"":"disabled")+'>Advance</button>'+
      '</div>'+
    '</article>';
  }).join("") || '<div class="empty">No operators in this view</div>';
}
function capabilitiesFor(workerId) {
  return dashboard.bindings
    .filter(b => b.worker_id === workerId && b.status === "bound")
    .map(b => dashboard.capabilities.find(c => c.id === b.capability_id))
    .filter(Boolean);
}
function renderWorkers() {
  const missionWorkers = dashboard.workers.filter(w => !missionFilter || w.mission_id === missionFilter);
  el("workers").innerHTML = missionWorkers.map(w => {
    const caps = capabilitiesFor(w.id);
    const capHtml = caps.length ? '<div class="cap-list">'+caps.map(c => '<span class="cap">'+esc(c.name)+'</span>').join("")+'</div>' : '<small>No capability binding</small>';
    return '<div class="worker">'+
      '<div class="row"><strong>'+esc(w.role)+'</strong>'+badge(w.status || "created")+'</div>'+
      '<small>'+esc(w.id)+'</small>'+
      '<small>provider: '+esc(w.provider)+'</small>'+capHtml+
    '</div>';
  }).join("") || '<div class="empty">No workers in this view</div>';
}
function renderGates() {
  const gates = dashboard.gates.filter(g => g.status.status === "open" && (!missionFilter || g.gate.mission_id === missionFilter));
  el("gate-count").textContent = gates.length + " open";
  el("gates").innerHTML = gates.map(item => {
    const g = item.gate;
    const impacts = g.impacts || {};
    const gateChoices = g.choices || [];
    const choices = gateChoices.map(choice =>
      '<button class="choice-btn" data-gate="'+esc(g.id)+'" data-choice="'+esc(choice)+'">'+
        '<strong>'+esc(choice)+'</strong>'+
        (impacts[choice] ? '<span class="choice-impact">'+esc(impacts[choice])+'</span>' : '')+
      '</button>'
    ).join("");
    const freeform = gateChoices.length === 0
      ? '<div style="display:grid;grid-template-columns:1fr auto;gap:7px">'+
          '<input data-gate-text="'+esc(g.id)+'" placeholder="Type the human decision">'+
          '<button class="primary" data-gate-text-submit="'+esc(g.id)+'">Resolve</button>'+
        '</div>'
      : '';
    const safe = g.allow_choose_for_me
      ? '<button class="warn" data-gate-default="'+esc(g.id)+'">Choose safe default · '+esc(g.safe_default)+'</button>'
      : '';
    return '<div class="gate">'+
      '<div class="row">'+badge(g.materiality,"warn")+(g.recommendation?badge("recommend: "+g.recommendation,"good"):"")+'</div>'+
      '<div class="question">'+esc(g.question)+'</div>'+
      '<div class="reason">'+esc(g.reason)+'</div>'+
      '<div class="choice-grid">'+choices+freeform+safe+'</div>'+
    '</div>';
  }).join("") || '<div class="empty">No human decision needed ✦</div>';
}
function renderEvents() {
  const events = (dashboard.events || []).filter(e => !missionFilter || e.mission_id === missionFilter).slice().reverse();
  el("event-count").textContent = events.length + " shown";
  el("events").innerHTML = events.map(e =>
    '<div class="event">'+
      '<div><div class="type">'+esc(e.type)+'</div><div class="when">'+esc(timeText(e.timestamp))+'</div></div>'+
      '<div class="subject">'+esc(JSON.stringify(e.subject))+'</div>'+
    '</div>'
  ).join("") || '<div class="empty">No events</div>';
}
function renderProduction() {
  const h = dashboard.handoffs || [];
  const tasks = dashboard.evidence.tasks || [];
  const parts = [
    '<div class="row"><span>Tasks</span><strong>'+esc(tasks.length)+'</strong></div>',
    '<div class="row"><span>Handoffs</span><strong>'+esc(h.length)+'</strong></div>',
    '<div class="row"><span>Validated bundles</span><strong>'+esc(dashboard.evidence.validated_bundle_count || 0)+'</strong></div>',
    '<div class="row"><span>Capability bindings</span><strong>'+esc(dashboard.bindings.length)+'</strong></div>',
  ];
  const latest = h[h.length-1];
  if (latest) {
    parts.push('<div class="section-spacer"></div>'+
      '<div>'+badge("latest handoff", "violet")+'</div>'+
      '<div style="margin-top:8px;color:#c8d8e5">'+esc(latest.handoff.id)+'</div>'+
      '<div style="margin-top:4px;color:var(--muted)">status: '+esc(latest.status.status)+'</div>');
  }
  el("production").innerHTML = parts.join("");
}
function render() {
  el("project-name").textContent = dashboard.project.name;
  el("project-root").textContent = dashboard.project.root;
  renderMissions();
  renderStats();
  renderOperators();
  renderWorkers();
  renderGates();
  renderEvents();
  renderProduction();
}
async function refresh() {
  try {
    dashboard = await api("/api/dashboard");
    render();
  } catch (err) {
    showToast(err.message, true);
  }
}
document.addEventListener("click", async (event) => {
  const mission = event.target.closest("[data-mission]");
  if (mission) {
    missionFilter = mission.dataset.mission;
    render();
    return;
  }
  if (event.target.closest("#all-missions")) {
    missionFilter = null;
    render();
    return;
  }
  const advance = event.target.closest("[data-advance]");
  if (advance) {
    advance.disabled = true;
    try {
      await api("/api/operator/advance", {
        method: "POST",
        body: JSON.stringify({operator_id: advance.dataset.advance})
      });
      showToast("Operator advanced");
      await refresh();
    } catch (err) {
      showToast(err.message, true);
      advance.disabled = false;
    }
    return;
  }
  const choice = event.target.closest("[data-gate][data-choice]");
  if (choice) {
    try {
      await api("/api/gate/resolve", {
        method: "POST",
        body: JSON.stringify({
          gate_id: choice.dataset.gate,
          choice: choice.dataset.choice
        })
      });
      showToast("Human Gate resolved");
      await refresh();
    } catch (err) {
      showToast(err.message, true);
    }
    return;
  }
  const textSubmit = event.target.closest("[data-gate-text-submit]");
  if (textSubmit) {
    const gateId = textSubmit.dataset.gateTextSubmit;
    const input = document.querySelector('[data-gate-text="'+CSS.escape(gateId)+'"]');
    const value = input ? input.value.trim() : "";
    if (!value) {
      showToast("Enter a decision first", true);
      return;
    }
    try {
      await api("/api/gate/resolve", {
        method: "POST",
        body: JSON.stringify({
          gate_id: gateId,
          choice: value
        })
      });
      showToast("Human Gate resolved");
      await refresh();
    } catch (err) {
      showToast(err.message, true);
    }
    return;
  }
  const safe = event.target.closest("[data-gate-default]");
  if (safe) {
    try {
      await api("/api/gate/resolve", {
        method: "POST",
        body: JSON.stringify({
          gate_id: safe.dataset.gateDefault,
          choose_for_me: true
        })
      });
      showToast("Safe default recorded");
      await refresh();
    } catch (err) {
      showToast(err.message, true);
    }
  }
});
el("refresh").addEventListener("click", refresh);
refresh();
setInterval(refresh, 8000);
</script>
</body>
</html>
"""


class CockpitDashboard:
    def __init__(
        self,
        store: CockpitStore,
    ) -> None:
        self.store = store
        self.evidence = EvidenceManager(store)
        self.handoffs = HandoffManager(store)
        self.operators = OperatorManager(store)
        self.capabilities = CapabilityManager(store)
        self.gates = HumanQuestionGateManager(store)

    def snapshot(
        self,
        *,
        event_limit: int = 200,
    ) -> dict[str, Any]:
        base = self.store.snapshot()
        evidence_summary = self.evidence.summary()
        tasks = self.evidence.list_tasks()
        results = self.evidence.list_results()
        bundles = self.evidence.list_bundles()
        evidence_summary["tasks"] = tasks
        evidence_summary["results"] = results
        evidence_summary["bundles"] = bundles
        evidence_summary["bundle_count"] = len(
            bundles
        )
        evidence_summary[
            "validated_bundle_count"
        ] = sum(
            1
            for bundle in bundles
            if bundle.get("status")
            == "validated"
        )
        return {
            **base,
            "operators": self.operators.list(),
            "handoffs": self.handoffs.list(),
            "capabilities": [
                item.to_dict()
                for item
                in self.capabilities.list_capabilities()
            ],
            "bindings": (
                self.capabilities.list_bindings()
            ),
            "capability_summary": (
                self.capabilities.summary()
            ),
            "gates": self.gates.list(),
            "gate_summary": self.gates.summary(),
            "evidence": evidence_summary,
            "events": self.store.list_events(
                limit=event_limit
            ),
        }


class CockpitUI:
    def __init__(
        self,
        root: Path | str = ".",
        *,
        token: str | None = None,
    ) -> None:
        self.store = CockpitStore(root)
        self.dashboard = CockpitDashboard(
            self.store
        )
        self.token = (
            token
            or secrets.token_urlsafe(24)
        )

    def html(self) -> str:
        return _HTML.replace(
            "__MADO_TOKEN__",
            self.token,
        )

    def resolve_gate(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        gate_id = self._required_string(
            payload,
            "gate_id",
        )
        current = self.dashboard.gates.inspect(
            gate_id
        )
        operator_id = current[
            "gate"
        ].get("operator_id")

        choice = payload.get(
            "choice"
        )
        choose_for_me = bool(
            payload.get(
                "choose_for_me",
                False,
            )
        )
        note = payload.get("note")

        if operator_id:
            return self.dashboard.operators.resolve_gate(
                str(operator_id),
                choice=(
                    str(choice)
                    if choice is not None
                    else None
                ),
                choose_for_me=(
                    choose_for_me
                ),
                note=(
                    str(note)
                    if note is not None
                    else None
                ),
            )

        return self.dashboard.gates.resolve(
            gate_id,
            choice=(
                str(choice)
                if choice is not None
                else None
            ),
            choose_for_me=choose_for_me,
            note=(
                str(note)
                if note is not None
                else None
            ),
        )

    def advance_operator(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        operator_id = self._required_string(
            payload,
            "operator_id",
        )
        return self.dashboard.operators.advance(
            operator_id
        )

    @staticmethod
    def _required_string(
        payload: dict[str, Any],
        key: str,
    ) -> str:
        value = payload.get(key)
        if (
            not isinstance(value, str)
            or not value.strip()
        ):
            raise RuntimeError(
                f"Missing required field: {key}"
            )
        return value.strip()


def _handler_class(
    ui: CockpitUI,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "MadoCockpitUI/0.8"

        def do_GET(self) -> None:
            parsed = urlparse(
                self.path
            )
            if parsed.path == "/":
                self._send_text(
                    ui.html(),
                    content_type=(
                        "text/html; charset=utf-8"
                    ),
                )
                return

            if parsed.path == "/api/dashboard":
                self._send_json(
                    ui.dashboard.snapshot()
                )
                return

            self._send_json(
                {
                    "error": "not found",
                },
                status=HTTPStatus.NOT_FOUND,
            )

        def do_POST(self) -> None:
            if (
                self.headers.get(
                    "X-Mado-Cockpit-Token"
                )
                != ui.token
            ):
                self._send_json(
                    {
                        "error": (
                            "invalid cockpit token"
                        ),
                    },
                    status=HTTPStatus.FORBIDDEN,
                )
                return

            try:
                payload = self._read_json()
                parsed = urlparse(
                    self.path
                )

                if (
                    parsed.path
                    == "/api/operator/advance"
                ):
                    result = (
                        ui.advance_operator(
                            payload
                        )
                    )
                elif (
                    parsed.path
                    == "/api/gate/resolve"
                ):
                    result = ui.resolve_gate(
                        payload
                    )
                else:
                    self._send_json(
                        {
                            "error": "not found",
                        },
                        status=(
                            HTTPStatus.NOT_FOUND
                        ),
                    )
                    return

                self._send_json(result)
            except (
                RuntimeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                self._send_json(
                    {
                        "error": str(exc),
                    },
                    status=(
                        HTTPStatus.BAD_REQUEST
                    ),
                )

        def log_message(
            self,
            format: str,
            *args: object,
        ) -> None:
            return

        def _read_json(
            self,
        ) -> dict[str, Any]:
            length = int(
                self.headers.get(
                    "Content-Length",
                    "0",
                )
            )
            if length > 1024 * 1024:
                raise RuntimeError(
                    "Request body is too large"
                )
            raw = self.rfile.read(
                length
            )
            if not raw:
                return {}
            payload = json.loads(
                raw.decode("utf-8")
            )
            if not isinstance(
                payload,
                dict,
            ):
                raise RuntimeError(
                    "JSON request must be an object"
                )
            return payload

        def _send_json(
            self,
            payload: object,
            *,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            body = json.dumps(
                payload,
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(
                int(status)
            )
            self.send_header(
                "Content-Type",
                "application/json; charset=utf-8",
            )
            self.send_header(
                "Cache-Control",
                "no-store",
            )
            self.send_header(
                "Content-Length",
                str(len(body)),
            )
            self.end_headers()
            self.wfile.write(body)

        def _send_text(
            self,
            text: str,
            *,
            content_type: str,
        ) -> None:
            body = text.encode(
                "utf-8"
            )
            self.send_response(
                int(HTTPStatus.OK)
            )
            self.send_header(
                "Content-Type",
                content_type,
            )
            self.send_header(
                "Cache-Control",
                "no-store",
            )
            self.send_header(
                "Content-Security-Policy",
                (
                    "default-src 'self'; "
                    "script-src 'unsafe-inline'; "
                    "style-src 'unsafe-inline'; "
                    "connect-src 'self'; "
                    "img-src 'self' data:; "
                    "frame-ancestors 'none'"
                ),
            )
            self.send_header(
                "X-Content-Type-Options",
                "nosniff",
            )
            self.send_header(
                "X-Frame-Options",
                "DENY",
            )
            self.send_header(
                "Content-Length",
                str(len(body)),
            )
            self.end_headers()
            self.wfile.write(body)

    return Handler


def create_ui_server(
    root: Path | str = ".",
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str | None = None,
    allow_remote: bool = False,
) -> tuple[ThreadingHTTPServer, CockpitUI]:
    if (
        host not in {
            "127.0.0.1",
            "localhost",
        }
        and not allow_remote
    ):
        raise RuntimeError(
            "Refusing non-local UI bind. "
            "Pass allow_remote=True explicitly."
        )
    if not 0 <= port <= 65535:
        raise RuntimeError(
            "UI port must be within 0..65535"
        )

    ui = CockpitUI(
        root,
        token=token,
    )
    ui.store.snapshot()

    server = ThreadingHTTPServer(
        (host, port),
        _handler_class(ui),
    )
    server.daemon_threads = True
    return server, ui


def serve_ui(
    root: Path | str = ".",
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    allow_remote: bool = False,
    open_browser: bool = False,
) -> None:
    server, _ = create_ui_server(
        root,
        host=host,
        port=port,
        allow_remote=allow_remote,
    )
    actual_host, actual_port = (
        server.server_address[:2]
    )
    url = (
        f"http://{actual_host}:"
        f"{actual_port}/"
    )
    print(
        "MADO Cockpit UI listening on "
        f"{url}"
    )
    print(
        "UI actions are limited to "
        "deterministic advance and "
        "Human Gate resolution."
    )

    if open_browser:
        threading.Timer(
            0.2,
            lambda: webbrowser.open(
                url
            ),
        ).start()

    try:
        server.serve_forever(
            poll_interval=0.25
        )
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
