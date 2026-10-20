// Deterministic baseline: the LLM is *not* invoked or simulated.
// Translate only bounded, display-safe portions of the Cockpit snapshot.
export const MODES = Object.freeze(["projects", "agents", "qa"]);
export const EMPTY = Object.freeze({ project: { name: "MADO Cockpit" }, missions: [], workers: [], gates: [], evidence: { tasks: [] } });

const asArray = (v) => Array.isArray(v) ? v : [];
const text = (v, max = 100) => {
  if (typeof v !== "string" && typeof v !== "number") return "";
  return String(v).slice(0, max);
};
const row = (title, detail, status) => ({ title: text(title) || "Unnamed", detail: text(detail, 140), status: text(status, 50) || "unknown" });

export function normalizeSnapshot(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new TypeError("Dashboard snapshot must be an object");
  const source = raw;
  const missions = asArray(source.missions).slice(0, 12).map((m) =>
    row(m?.title || m?.id, m?.id || "Mission", m?.status || "tracked")
  );
  const workers = asArray(source.workers).slice(0, 12).map((w) =>
    row(w?.id, [text(w?.role), text(w?.provider)].filter(Boolean).join(" · "), w?.status || "registered")
  );
  const tasks = asArray(source.evidence?.tasks).slice(0, 10).map((t) =>
    row(t?.id, t?.mission_id || "Evidence task", t?.status || "pending")
  );
  const gates = asArray(source.gates).filter((g) => g?.status !== "resolved").slice(0, 2).map((g) =>
    row(g?.id || "Human Gate", "Human decision required in the original Cockpit", "review only")
  );
  return {
    project: text(source.project?.name || "MADO Cockpit"),
    projects: missions,
    agents: workers,
    qa: [...gates, ...tasks].slice(0, 12),
  };
}

export const FIXTURE = Object.freeze({
  project: "MADO Cockpit [SAMPLE]",
  projects: [
    row("MCC", "Adaptive Control Plane", "active"),
    row("MGSF", "Game Factory", "qa"),
    row("MAF", "Media & AI Factory", "review"),
  ],
  agents: [
    row("Codex", "Builder · isolated worktree", "ready"),
    row("OpenCode", "Free model fallback", "standby"),
    row("QA", "Independent reviewer", "pending"),
  ],
  qa: [
    row("Evidence #001", "Visual screenshot proof", "passed"),
    row("QA task #002", "Browser E2E replay", "needs_fix"),
    row("Human Gate", "Resolve in original Cockpit", "review only"),
  ],
});

export function buildProgram(mode, data, source = "sample") {
  if (!MODES.includes(mode)) throw new RangeError("Unsupported cockpit view");
  const panel = { projects: "ProjectPanel", agents: "AgentPanel", qa: "QaPanel" }[mode];
  const title = { projects: "Project overview", agents: "Agent runtime", qa: "QA & Human Gates" }[mode];
  const entries = Array.isArray(data?.[mode]) ? data[mode].slice(0, 12) : [];
  const clean = entries.map((e) => row(e?.title, e?.detail, e?.status));
  const label = text(data?.project || "MADO Cockpit");
  const origin = source === "live" ? "localhost · read-only" : "isolated sample · no API key";
  return [
    "root = CockpitScreen(" + JSON.stringify(title) + ", " + JSON.stringify(label + " · " + origin) + ", [panel])",
    "panel = " + panel + "(" + JSON.stringify(clean) + ")",
  ].join("\n") + "\n";
}

export function byteSize(value) {
  return new TextEncoder().encode(value).length;
}
