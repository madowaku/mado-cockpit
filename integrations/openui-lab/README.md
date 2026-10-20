# MCC-M2.9 OpenUI Lang 1.0 / Adaptive Cockpit UI Lab

This directory is an **isolated, read-only experiment** built with the real
`@openuidev/react-lang@1.0.1` renderer. It does not replace the existing Python
Cockpit UI or the OpenDots Human Gate review workflow.

## Run (no model account or cloud API key)

Node 22+ is recommended.

```bash
# Terminal A, from repo root. Requires a configured local Cockpit state store.
mado-cockpit ui
# Terminal B
cd integrations/openui-lab
npm install
npm test
npm run build
npm run dev
# http://127.0.0.1:4179
```

The **Sample data** mode needs only Terminal B and is explicitly synthetic.
**Read local Cockpit** fetches the existing Python `GET /api/dashboard` through a
loopback-only Vite proxy at `/cockpit-read`. If unavailable, the previous view
remains on screen with a visible warning. Nothing is persisted, uploaded, or
sent to an LLM.

## Architecture and safety

```text
GET /api/dashboard (Python loopback UI)       sample fixture
                  |                                |
            exact-path Vite proxy                   |
                  +--------------+-----------------+
                                 v
                  bounded snapshot normalization
                      (no token, paths, gate text)
                                 v
                       buildProgram(view)
                     (deterministic baseline)
                                 v
                      OpenUI Lang text stream
                                 v
                     @openuidev/react-lang
                       whitelisted components
                                 v
                         read-only cards
```

- No agent launches, fetch tools, write actions, gate decisions, or model calls.
- No access to the UI token, raw evidence files, or private gate question text.
- The OpenUI component registry contains only CockpitScreen, ProjectPanel,
  AgentPanel, and QaPanel. No arbitrary HTML executor or mutating tools.
- JSON serialization of strings prevents newline injection into OpenUI Lang.
- Untrusted source lists, labels, and statuses are size-bounded.
- The progressive render switch demonstrates partial OpenUI Lang arrival.
  It is not a measured LLM token stream.
- Never expose the Vite dev server or Python UI to public networks.
- Existing Python UI, CLI, audit, Human Gate and permission boundaries are untouched.

## Qualification and follow-up

Gate 1: `npm test`, `npm run build` succeed.
Gate 2: run Sample / all 3 views / progressive replay, inspect DOM and screenshots.
Gate 3: start local Cockpit UI and check live views accurately reflect current
read-only snapshot. Confirm no mutation request is emitted.
Gate 4: compare with the existing UI on clarity, load speed and information
coverage; log screenshot evidence and any accessibility issues.
Gate 5 (future, NOT part of this PR): optional BYO local/free model generates
OpenUI Lang from the same restricted component prompt; compare output validity,
latency, token use and cost against this deterministic baseline.

No agent-initiated decision or execution feature should be promoted without
independent QA evidence and existing human approval gates.
