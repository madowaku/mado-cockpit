"""Genuine Chromium visual proof for three *manually authored* design directions.

Never pass this off as Superdesign, Better Design or Design Taste output:
candidate IDs reuse the experiment's three slots for harness integration only.
All registered runs are manual_baseline and cannot pass the quality gate.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from mado_cockpit.design_bakeoff import BakeoffError
from mado_cockpit.design_discovery import DesignDiscoveryHub
from mado_cockpit.design_intelligence_lab import CANDIDATE_MAP, DesignIntelligenceLab, _sha
from mado_cockpit.design_quality_gate import RealUIDecisionGate, RUN_SCHEMA
from mado_cockpit.models import Project
from mado_cockpit.store import CockpitStore


STYLE = {
    "superdesign": {
        "label": "MANUAL BASELINE A / EDITORIAL",
        "title": "Clarity precedes approval.",
        "subtitle": "A restrained, editorial approach to controlled decisions.",
        "css": r"""
:root{color-scheme:light dark;--bg:#faf6ee;--panel:#fffcf5;--ink:#29251d;--muted:#7a746b;--line:#ddd6c9;--accent:#922f33}
@media(prefers-color-scheme:dark){:root{--bg:#191b1d;--panel:#252729;--ink:#eee8df;--muted:#bbb0a4;--line:#44413e;--accent:#e8a5a7}}
main{max-width:1120px;margin:auto;padding:48px 35px}.hero{max-width:890px;margin-bottom:34px}
h1{font-family:Georgia,serif;font-weight:500;font-size:clamp(34px,5.2vw,66px);letter-spacing:-.055em;max-width:800px}
.layout{grid-template-columns:1.65fr 1fr;gap:30px}.panel{border-top:2px solid var(--ink);background:none;border-radius:0;padding:26px 5px;box-shadow:none}
h2{font-family:Georgia,serif;font-size:24px;font-weight:500}.flag{letter-spacing:.17em;text-transform:uppercase}
.meta{font-family:Georgia,serif;font-style:italic}
@media(max-width:700px){main{padding:25px 19px}.layout{grid-template-columns:1fr;gap:18px}h1{font-size:44px}}
""",
    },
    "better-design": {
        "label": "MANUAL BASELINE B / OPERATIONS",
        "title": "Review surface / 014.",
        "subtitle": "A dense operations console with explicit evidence states.",
        "css": r"""
:root{color-scheme:light dark;--bg:#0b1520;--panel:#142533;--ink:#e3f4ef;--muted:#91b6bf;--line:#2c4852;--accent:#66edbd}
@media(prefers-color-scheme:light){:root{--bg:#e8f0f2;--panel:#f9ffff;--ink:#162e36;--muted:#586e78;--line:#becfd4;--accent:#08765d}}
body{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
main{padding:37px 31px;max-width:1280px;margin:auto}
h1{font-size:clamp(26px,3.3vw,43px);letter-spacing:-.045em;text-transform:uppercase}
h2{font-size:16px;text-transform:uppercase;letter-spacing:.04em}
.layout{grid-template-columns:1.35fr 1fr;gap:15px}
.panel{padding:23px 25px;border-radius:3px;box-shadow:none}
.flag{border-left:3px solid var(--accent);padding-left:8px;letter-spacing:.1em}
.details{border-radius:2px}
header{border-bottom:2px solid var(--accent)}
@media(max-width:700px){main{padding:25px 14px}.layout{grid-template-columns:1fr}h1{font-size:30px}}
""",
    },
    "design-taste": {
        "label": "MANUAL BASELINE C / CALM SYSTEM",
        "title": "Review with confidence.",
        "subtitle": "A calm, intentionally quiet workspace for thoughtful decisions.",
        "css": r"""
:root{color-scheme:light dark;--bg:#eaf2ef;--panel:#fff;--ink:#17352c;--muted:#58746b;--line:#d1dfd9;--accent:#246f61}
@media(prefers-color-scheme:dark){:root{--bg:#0f2220;--panel:#182f2b;--ink:#edf9f4;--muted:#a3c0b7;--line:#365149;--accent:#92e2cb}}
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1090px;margin:50px auto;padding:0 26px}
.hero{margin:0 0 34px;max-width:700px}
h1{font-size:clamp(36px,4.6vw,60px);letter-spacing:-.052em}
.layout{grid-template-columns:1fr 1fr;gap:22px}
.panel{border-radius:18px;padding:30px;box-shadow:0 18px 42px #0c3d2520}
.flag{background:var(--bg);padding:8px 11px;border-radius:30px}
.details{border-radius:12px}
@media(max-width:700px){main{margin:27px auto;padding:0 17px}.layout{grid-template-columns:1fr}h1{font-size:38px}}
""",
    },
}


def render_html(candidate: str) -> str:
    v = STYLE[candidate]
    base = r"""
*{box-sizing:border-box}html{scroll-behavior:auto}
body{margin:0;min-height:100vh;background:var(--bg);color:var(--ink)}
header{height:62px;display:flex;justify-content:space-between;align-items:center;padding:0 28px;border-bottom:1px solid var(--line)}
.brand{font-weight:800;letter-spacing:.1em;font-size:13px}
nav a{color:var(--ink);text-decoration:none;font-size:12px;font-weight:700}
a:focus-visible,button:focus-visible{outline:3px solid var(--accent);outline-offset:3px}
.kicker,.flag{font-size:11px;font-weight:800;color:var(--accent)}
h1{line-height:1.12;margin:13px 0 12px}
.subtitle,.quiet{color:var(--muted);line-height:1.65}
.layout{display:grid}.panel{background:var(--panel);border:1px solid var(--line);padding:24px}
h2{font-size:19px;margin:6px 0 13px}
.grid-row{display:flex;justify-content:space-between;gap:16px;align-items:center;padding:16px 0;border-bottom:1px solid var(--line);font-size:13px}
.grid-row:last-child{border-bottom:none}.grid-row span{color:var(--muted);text-align:right}
.details{margin-top:22px;background:var(--bg);padding:16px;line-height:1.9;font-size:13px}
.plus{color:var(--accent)}button{width:100%;padding:15px;margin-top:20px;font-size:13px;background:var(--muted);color:#fff;border:0;border-radius:6px}
button:disabled{opacity:.68;cursor:not-allowed}.quiet{font-size:12px}.footer{font-size:10px;letter-spacing:.08em;color:var(--muted);margin-top:28px}
@media(max-width:700px){header{padding:0 17px}.brand{font-size:11px}}
"""
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MADO · Manually Authored Bake-off Direction</title>
<style>{base}\n{v['css']}</style></head>
<body>
<header><div class="brand">MADO / COCKPIT</div><nav><a href="#evidence">View evidence</a></nav></header>
<main>
  <div class="hero"><div class="kicker">{v['label']}</div>
  <h1>{v['title']}</h1><p class="subtitle">{v['subtitle']}</p></div>
  <div class="layout">
    <section class="panel" id="evidence">
      <div class="flag">SOURCE REVIEW / PENDING</div>
      <h2>Proposed component change</h2>
      <p class="quiet">Review provenance, UI evidence and legal usage before changing live controls.</p>
      <div class="grid-row"><strong>Source</strong><span>Operator-provided build</span></div>
      <div class="grid-row"><strong>License evidence</strong><span>Human review required</span></div>
      <div class="grid-row"><strong>Visual evidence</strong><span>Light / Dark / Mobile</span></div>
      <div class="details">− Previous approval presentation<br>
        <span class="plus">+ Clearer hierarchy and traceable source</span><br>
        <span class="plus">+ Visible keyboard focus states</span></div>
    </section>
    <section class="panel">
      <div class="flag">HUMAN CONTROL</div>
      <h2>Authorization stays separate</h2>
      <p class="quiet">Design similarity does not grant approval capability. A human control lease and verified release process remain mandatory.</p>
      <div class="grid-row"><strong>Execution</strong><span>Mocked / no backend</span></div>
      <div class="grid-row"><strong>Release</strong><span>Blocked</span></div>
      <div class="grid-row"><strong>Approval</strong><span>Awaiting human</span></div>
      <button type="button" disabled aria-disabled="true">Approval unavailable</button>
    </section>
  </div>
  <div class="footer">LOCAL MANUAL BASELINE · NOT GENERATED BY SUPERDESIGN / BETTER DESIGN / DESIGN TASTE</div>
</main>
</body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Actual-browser evidence for three manual design directions")
    parser.add_argument("--output-root", type=Path, default=Path(".mado/real-ui-decision-fixture"))
    parser.add_argument("--browser-channel", choices=("chrome", "chromium", "msedge"))
    parser.add_argument("--browser-executable")
    args = parser.parse_args()
    root = args.output_root.resolve()
    if (root / ".mado").exists():
        parser.error("Output already initialized")
    brief = Path("fixtures/design_intelligence/mcc-m2.6.2e-approval-console.json").resolve()
    if not brief.is_file():
        parser.error("Run from repository root")
    root.mkdir(parents=True, exist_ok=True)
    CockpitStore(root).init(Project(id="manual-ui-bakeoff", name="Manual Design Smoke", root=str(root)))
    DesignDiscoveryHub(root).bootstrap()
    lab = DesignIntelligenceLab(root)
    plan = lab.plan(brief)
    exp = plan["experiment"]
    gate = RealUIDecisionGate(root)
    bundle_dir = root / "builds"
    candidate_names = ("superdesign", "better-design", "design-taste")
    for cid in candidate_names:
        folder = bundle_dir / cid
        folder.mkdir(parents=True)
        (folder / "index.html").write_text(render_html(cid), encoding="utf-8")
        decl = {
            "schema": RUN_SCHEMA, "experiment": exp, "candidate": cid,
            "task_sha256": _sha((Path(plan["path"]) / "tasks" / (cid + ".json")).read_bytes()),
            "upstream_commit": CANDIDATE_MAP[cid]["commit"],
            "execution_mode": "manual_baseline", "run_id": f"test-only-manual-{cid}",
            "operator": "human:ci-fixture",
            "command_summary": "Original, manually authored UI fixture; provider never invoked",
            "output_revision": "0" * 40,
            "cost_usd": None, "duration_seconds": 1.0, "status": "completed",
        }
        declaration = root / (cid + "-declaration.json")
        trace = root / (cid + "-trace.txt")
        declaration.write_text(json.dumps(decl), encoding="utf-8")
        trace.write_text("Manually authored test page. No external design provider was invoked. "
                         + cid, encoding="utf-8")
        gate.intake(exp, cid, declaration_file=declaration, bundle=folder, trace_file=trace)
        gate.capture_local(exp, cid, browser_channel=args.browser_channel,
                           browser_executable=args.browser_executable)
        assert gate.bridge.verify(exp, cid)["provenance"] == "fixture_smoke"
    sheets = [gate.bridge.sheet(exp, state=state) for state in ("light", "dark", "mobile")]
    result = gate.evaluate(exp)
    assert result["status"] == "hold_missing_evidence"
    assert result["recommendation"] is None
    assert result["model_authorship_verified"] is False
    assert result["license_and_release_approved"] is False
    hashes = [gate.bridge.verify(exp, cid)["images"][0]["sha256"] for cid in candidate_names]
    assert len(set(hashes)) == 3, "Visually distinct original UI builds expected"
    sealed = gate.seal(exp)
    report = {
        "schema": "mado.ui-real-bakeoff-manual-fixture-proof.v1",
        "experiment": exp, "real_chromium_screenshots": 9,
        "manual_ui_directions": 3, "independent_visual_hashes": True,
        "external_design_provider_invoked": False,
        "human_reviewed": False, "model_authorship_verified": False,
        "decision_status": result["status"], "recommended": None,
        "release_approved": False,
        "contact_sheets": sheets, "decision_report": sealed,
    }
    (root / "manual-proof.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
