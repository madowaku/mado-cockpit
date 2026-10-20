import { StrictMode, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Renderer } from "@openuidev/react-lang";
import { library } from "./library";
import { FIXTURE, MODES, buildProgram, byteSize, normalizeSnapshot } from "./model.mjs";
import "./style.css";

type Mode = (typeof MODES)[number];
type ViewData = ReturnType<typeof normalizeSnapshot>;
const modeLabels: Record<Mode, string> = { projects: "Projects", agents: "Agents", qa: "QA & Gates" };

function App() {
  const [mode, setMode] = useState<Mode>("projects");
  const [data, setData] = useState<ViewData>(FIXTURE);
  const [source, setSource] = useState<"sample" | "live">("sample");
  const [stream, setStream] = useState(true);
  const [replay, setReplay] = useState(0);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("Sample fixture. This is not current project status.");
  const [parseIssues, setParseIssues] = useState<string[]>([]);
  const program = useMemo(() => buildProgram(mode, data, source), [mode, data, source]);
  const [shown, setShown] = useState(program);

  useEffect(() => {
    if (!stream) { setShown(program); return; }
    const lines = program.trimEnd().split("\n");
    let position = 0;
    setShown("");
    const timer = window.setInterval(() => {
      position = Math.min(position + 1, lines.length);
      setShown(lines.slice(0, position).join("\n") + "\n");
      if (position === lines.length) window.clearInterval(timer);
    }, 600);
    return () => window.clearInterval(timer);
  }, [program, replay, stream]);

  async function loadLocal() {
    setBusy(true);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 3500);
    try {
      const response = await fetch("/cockpit-read", { method: "GET", cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error("HTTP " + response.status);
      const raw: unknown = await response.json();
      const result = normalizeSnapshot(raw);
      setData(result);
      setSource("live");
      setNotice("Local read-only dashboard snapshot. Refresh to read again.");
    } catch {
      setNotice("Local Cockpit unavailable. Start `mado-cockpit ui` on port 8765; the existing view was preserved.");
    } finally {
      window.clearTimeout(timeout);
      setBusy(false);
    }
  }

  function useSample() {
    setData(FIXTURE);
    setSource("sample");
    setNotice("Sample fixture. This is not current project status.");
  }

  return (
    <main className="layout">
      <nav className="rail" aria-label="Lab navigation">
        <div className="mark">M</div>
        <div className="rail-text"><strong>MADO</strong><span>system one</span></div>
        <span className="rail-tag">MCC-M2.9</span>
      </nav>
      <div className="workspace">
        <header className="top">
          <div><p className="eyebrow">EXPERIMENT 029 · OPENUI LANG 1.0</p><h1>Adaptive Cockpit <em>Lab</em></h1><p className="lede">A bounded generative-UI renderer for real Cockpit records, starting with a zero-cost deterministic baseline.</p></div>
          <span className="status-light"><i /> local / no model calls</span>
        </header>
        <section className="toolbar" aria-label="Data and preview controls">
          <div className="toolbar-group">
            <button className={source === "sample" ? "selected" : ""} onClick={useSample}>Sample data</button>
            <button className={source === "live" ? "selected" : ""} onClick={loadLocal} disabled={busy}>{busy ? "Connecting..." : "Read local Cockpit"}</button>
          </div>
          <div className="toolbar-group">
            <label><input type="checkbox" checked={stream} onChange={(event) => setStream(event.target.checked)} /> Progressive rendering</label>
            <button onClick={() => setReplay((r) => r + 1)}>↻ Replay</button>
          </div>
        </section>
        <p className="notice" role="status">{notice}</p>
        <div className="tabs" role="group" aria-label="Generated view">
          {MODES.map((key: Mode) => <button key={key} aria-pressed={key === mode} className={key === mode ? "active" : ""} onClick={() => setMode(key)}>{modeLabels[key]}</button>)}
        </div>
        <div className="columns">
          <div className="preview">
            <div className="column-heading"><h3>Rendered by OpenUI</h3><span>React runtime · four registered components</span></div>
            <Renderer
              response={shown}
              library={library}
              isStreaming={stream && shown !== program}
              onError={(errors) => {
                const messages = errors.map((e) => JSON.stringify(e));
                setParseIssues((prev) => JSON.stringify(prev) === JSON.stringify(messages) ? prev : messages);
              }}
            />
            {parseIssues.length > 0 && <div className="error-box" role="alert">Renderer issues: {parseIssues.join("; ")}</div>}
          </div>
          <aside className="source-panel">
            <div className="column-heading"><h3>OpenUI Lang</h3><span>{byteSize(program)} UTF-8 bytes</span></div>
            <pre aria-label="Generated OpenUI Lang">{shown || "Waiting for first line..."}</pre>
            <p>Program is a deterministic view from whitelisted read-only data. Attach an LLM only after baseline validation.</p>
            <details><summary>View model prompt contract</summary><pre>{library.prompt({
              preamble: "Render a read-only MADO cockpit view. Never invent state or request mutations.",
              additionalRules: [
                "Use only CockpitScreen, ProjectPanel, AgentPanel and QaPanel.",
                "Never render controls for operator.advance or gate.resolve.",
                "Only show supplied data. Unavailable fields must remain unavailable.",
              ],
              examples: [buildProgram("projects", FIXTURE)],
            })}</pre></details>
          </aside>
        </div>
        <footer>Experiment only · no network AI calls · no mutation tools · no auto-approval · existing Cockpit remains authoritative</footer>
      </div>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
