"use strict";
// Review-only pilot. No automatic network submission, preview probing or recording.
const $ = id => document.getElementById(id);
const ratings = new Set(["good", "okay", "stuck"]);
const STORAGE_PREFIX = "mado-human-test-flight-v1:";
let flights = [];
let projects = new Map();
let active = null;
let rating = null;
let publishedPreview = null;

function showStatus(message, error = false) {
  const el = $("feedbackStatus");
  el.textContent = message;
  el.dataset.error = String(error);
}
function validUrl(raw) {
  try {
    const u = new URL(raw);
    if (u.username || u.password || u.hash || !u.hostname) return null;
    if (u.protocol === "https:") return u.href;
    if (u.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(u.hostname)) return u.href;
  } catch (_error) { /* incomplete or unsafe URL */ }
  return null;
}
function payload() {
  if (!active || !ratings.has(rating)) {
    showStatus("先に「全体の感触」を選んでください。", true);
    return null;
  }
  return {
    schema: "mado.human-feedback.v1",
    mission_id: active.id,
    project_id: active.project_id,
    submitted_at: new Date().toISOString(),
    completed_step_indexes: Array.from(document.querySelectorAll("#stepList input:checked")).map(el => Number(el.value)),
    rating: rating,
    build_ref: $("buildRef").value.trim().slice(0, 120),
    note: $("note").value.trim().slice(0, 500),
    preview_source: publishedPreview && $("previewUrl").value === publishedPreview ? "catalog_verified" :
      $("previewUrl").value.trim() ? "human_supplied_unverified" : "not_provided",
    preview_url_included: false,
    human_review: true,
  };
}
function storageKey() { return STORAGE_PREFIX + active.id; }
function clearFields() {
  rating = null;
  $("note").value = "";
  $("buildRef").value = "";
  document.querySelectorAll("#stepList input").forEach(el => { el.checked = false; });
  refreshRatings();
}
function refreshRatings() {
  document.querySelectorAll("#ratings button").forEach(button => {
    button.setAttribute("aria-pressed", String(button.dataset.rating === rating));
  });
  refreshIssuePreview();
}
function issueText(data) {
  const checked = active.steps.map((step, i) => (data.completed_step_indexes.includes(i) ? "[x] " : "[ ] ") + step).join("\n");
  return [
    "## Human Test Flight / " + active.title,
    "Project: " + data.project_id,
    "Mission: " + data.mission_id,
    "Build ref (human-entered): " + (data.build_ref || "unspecified"),
    "Preview provenance: " + data.preview_source + " (URL intentionally excluded)",
    "Rating: " + data.rating,
    "",
    "### 3-minute checkpoints",
    checked,
    "",
    "### Human feedback",
    data.note || "(no note)",
    "",
    "Recorded (client clock): " + data.submitted_at,
    "Review-only human report. No automated QA, playable build, screenshot or deployment proof claimed.",
  ].join("\n");
}
function refreshIssuePreview() {
  const list = Array.from(document.querySelectorAll("#stepList input:checked")).map(el => Number(el.value));
  const data = {
    project_id: active?.project_id || "none",
    mission_id: active?.id || "none",
    build_ref: $("buildRef").value.trim().slice(0, 120),
    completed_step_indexes: list,
    rating: rating || "(rating not selected)",
    note: $("note").value.trim().slice(0, 500),
    submitted_at: "(created on export)",
    preview_source: publishedPreview && $("previewUrl").value === publishedPreview ? "catalog_verified" :
      $("previewUrl").value.trim() ? "human_supplied_unverified" : "not_provided",
  };
  if (active) $("issuePreview").textContent = issueText(data);
}
function restore() {
  try {
    const raw = localStorage.getItem(storageKey());
    if (!raw) return;
    const saved = JSON.parse(raw);
    if (saved.schema !== "mado.human-feedback.v1" || saved.mission_id !== active.id ||
        saved.project_id !== active.project_id || !ratings.has(saved.rating) ||
        !Array.isArray(saved.completed_step_indexes) || typeof saved.note !== "string" ||
        typeof saved.build_ref !== "string") throw new Error("Unsupported saved report");
    clearFields();
    rating = saved.rating;
    $("buildRef").value = saved.build_ref.slice(0, 120);
    $("note").value = saved.note.slice(0, 500);
    document.querySelectorAll("#stepList input").forEach(el => {
      el.checked = saved.completed_step_indexes.includes(Number(el.value));
    });
    refreshRatings();
    showStatus("このブラウザに保存した前回の評価を読み込みました。");
  } catch (_error) { showStatus("保存済みの記録を読み込めませんでした。新規作成できます。", true); }
}
function renderMission(id) {
  active = flights.find(m => m.id === id) || flights[0];
  const project = projects.get(active.project_id);
  $("missionSelect").value = active.id;
  $("missionTitle").textContent = active.title;
  $("missionGoal").textContent = active.goal;
  $("sourceLink").href = project.repository;
  publishedPreview = project.publication.state === "published_verified" ? validUrl(project.publication.url) : null;
  $("previewUrl").value = publishedPreview || "";
  $("previewUrl").readOnly = Boolean(publishedPreview);
  $("previewState").textContent = publishedPreview ? "LIVE VERIFIED / CATALOG" : "NO VERIFIED PLAY URL";
  $("openPreview").disabled = !publishedPreview;
  $("previewHelp").textContent = publishedPreview
    ? "公開URLはカタログの検証済み記録を参照しています。"
    : "ソースの存在は試遊版の存在を意味しません。手動でURLを入れるか、Windows版を別途起動してください。";
  $("stepList").replaceChildren(...active.steps.map((step, i) => {
    const label = document.createElement("label");
    label.className = "flight-step";
    const input = document.createElement("input");
    input.type = "checkbox"; input.value = String(i);
    input.addEventListener("change", refreshIssuePreview);
    const span = document.createElement("span"); span.textContent = step;
    label.append(input, span);
    return label;
  }));
  clearFields();
  showStatus("このミッションはレビュー用の下書きです。自動テスト済みとは扱いません。");
  restore();
  refreshIssuePreview();
}
$("missionSelect").addEventListener("change", e => {
  renderMission(e.target.value);
  const url = new URL(window.location.href);
  url.searchParams.set("project", active.project_id);
  history.replaceState(null, "", url);
});
$("previewUrl").addEventListener("input", () => {
  const typed = $("previewUrl").value.trim();
  const safe = validUrl(typed);
  $("openPreview").disabled = !safe;
  $("previewState").textContent = publishedPreview && typed === publishedPreview
    ? "LIVE VERIFIED / CATALOG" : safe ? "HUMAN SUPPLIED / NOT VERIFIED" : "NO VERIFIED PLAY URL";
  refreshIssuePreview();
});
$("openPreview").addEventListener("click", () => {
  const url = validUrl($("previewUrl").value.trim());
  if (!url) { showStatus("安全なHTTPS URLかlocalhostのHTTP URLのみ指定できます。", true); return; }
  const opened = window.open(url, "_blank", "noopener,noreferrer");
  // window.open may return null even when successful with noopener.
  showStatus("指定されたURLを開く操作をしました。到達性や動作は未検証です。");
});
$("ratings").addEventListener("click", e => {
  const button = e.target.closest("button[data-rating]");
  if (button && ratings.has(button.dataset.rating)) { rating = button.dataset.rating; refreshRatings(); }
});
$("note").addEventListener("input", refreshIssuePreview);
$("buildRef").addEventListener("input", refreshIssuePreview);
$("saveDraft").addEventListener("click", () => {
  const data = payload();
  if (!data) return;
  try {
    localStorage.setItem(storageKey(), JSON.stringify(data));
    showStatus("保存しました。この端末・ブラウザ内だけに保管されています。");
  } catch (_error) { showStatus("ブラウザの保存領域を利用できません。JSONを書き出してください。", true); }
});
$("clearDraft").addEventListener("click", () => {
  if (!active || !window.confirm("このミッションの評価とローカル保存を消去しますか？")) return;
  try { localStorage.removeItem(storageKey()); } catch (_error) { /* may be blocked */ }
  clearFields();
  refreshIssuePreview();
  showStatus("入力中の評価とローカル保存を消去しました。");
});
$("exportDraft").addEventListener("click", () => {
  const data = payload();
  if (!data) return;
  const blob = new Blob([JSON.stringify(data, null, 2) + "\n"], {type:"application/json"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "human-feedback-" + active.id + ".json";
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  showStatus("JSONを書き出しました。ファイルの保存先を確認してください。");
});
$("openIssue").addEventListener("click", () => {
  const data = payload();
  if (!data) return;
  if (!window.confirm("フィードバックをGitHubのIssue下書きURLに含めます。内容に秘密情報がないことを確認しましたか？")) return;
  const title = "[Human Test] " + active.title + " / " + data.rating;
  const repo = projects.get(active.project_id).repository;
  const body = issueText(data);
  const url = repo + "/issues/new?title=" + encodeURIComponent(title) + "&body=" + encodeURIComponent(body);
  window.open(url, "_blank", "noopener,noreferrer");
  showStatus("GitHubの新規Issue画面を開く操作をしました。Issueの作成・投稿は行っていません。");
});
async function init() {
  try {
    const responses = await Promise.all([
      fetch("./catalog.json", {cache:"no-store"}),
      fetch("./test-flights.json", {cache:"no-store"}),
    ]);
    if (responses.some(r => !r.ok)) throw new Error("Manifest fetch failed");
    const [catalog, manifest] = await Promise.all(responses.map(r => r.json()));
    if (catalog.schema !== "mado.sites-catalog.v1" || !Array.isArray(catalog.projects) ||
        manifest.schema !== "mado.human-test-flight.v1" || manifest.release_state !== "review_only" ||
        !Array.isArray(manifest.missions) || !manifest.missions.length) throw new Error("Invalid contract");
    projects = new Map(catalog.projects.map(p => [p.id, p]));
    flights = manifest.missions.filter(m => projects.has(m.project_id) &&
      m.review_state === "draft" && m.estimated_minutes === 3 &&
      Array.isArray(m.steps) && m.steps.length === 3);
    if (!flights.length) throw new Error("No reviewed mission catalog");
    for (const m of flights) {
      const option = document.createElement("option");
      option.value = m.id;
      option.textContent = projects.get(m.project_id).title + " / " + m.title;
      $("missionSelect").append(option);
    }
    const requested = new URL(window.location.href).searchParams.get("project");
    const first = flights.find(m => m.project_id === requested) || flights[0];
    renderMission(first.id);
    $("flightContent").hidden = false;
  } catch (error) {
    $("flightError").hidden = false;
    console.error("Human Test Flight manifest failed", error);
  }
}
init();
