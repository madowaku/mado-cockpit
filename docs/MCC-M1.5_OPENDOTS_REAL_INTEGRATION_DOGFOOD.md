# MCC-M1.5 OpenDots Real Integration / Dogfood Harness

MCC-M1.5 turns the M1.2–M1.4 integration pack into a repeatable overlay that can be applied to a real local OpenDots checkout.

It intentionally does not fork OpenDots and does not add another network service.

## Runtime shape

```text
OpenDots server
    |
    | defineTool executor
    v
mado-cockpit-caller.ts
    |
    | local child_process.spawn, shell=false
    | stdin/stdout JSON
    v
python -m mado_cockpit.opendots_tools
    |
    v
MCC-M1.3 / M1.2
    |
    v
MADO Cockpit
```

The bridge requires:

```text
MADO_COCKPIT_ROOT=/path/to/mado-cockpit
```

Optional:

```text
MADO_COCKPIT_PYTHON=/path/to/python
```

The caller prepends `<MADO_COCKPIT_ROOT>/src` to `PYTHONPATH`, so editable installation of mado-cockpit is not required for dogfood.

## Why subprocess first

The M1.5 dogfood bridge is deliberately local-process only:

- no new HTTP listener;
- no bearer token copied into tool payloads;
- no arbitrary shell command;
- `spawn(..., shell: false)`;
- bounded stdout/stderr;
- 30-second timeout;
- M1.2/M1.3 validation remains the execution authority.

The later M1.1 secure transport can replace the caller without changing the five Dot tools.

## Upstream lock

```text
fixtures/opendots/mcc-m1.5-upstream-lock.json
```

pins the OpenDots files this overlay was built against on 2026-10-03:

```text
package.json
src/server/dot-agent.ts
src/client/Chat.tsx
src/client/main.tsx
```

By default the harness fails closed when those files drift.

Use `--allow-drift` only for an intentional local experiment. Anchor mismatches still fail rather than guessing where to patch.

## Overlay

The copy-ready overlay lives under:

```text
integrations/opendots/overlay/
└─ src/
   ├─ server/
   │  ├─ mado-cockpit-tools.ts
   │  └─ mado-cockpit-caller.ts
   ├─ shared/
   │  └─ mado-human-gate.ts
   └─ client/
      ├─ mado-cockpit-renderers.tsx
      └─ mado-cockpit-renderers.css
```

The harness then marker-patches only:

```text
src/server/dot-agent.ts
src/client/Chat.tsx
src/client/main.tsx
```

Applying the harness twice is a no-op the second time.

## Real checkout command

From the mado-cockpit repository:

```bash
python -m mado_cockpit.opendots_dogfood \
  --opendots-root /path/to/OpenDots \
  --apply
```

To install dependencies and run the OpenDots checks:

```bash
python -m mado_cockpit.opendots_dogfood \
  --opendots-root /path/to/OpenDots \
  --apply \
  --verify \
  --install
```

Verification runs the current OpenDots commands pinned in the fixture:

```text
npm run typecheck
npm run build
npm test
```

## Python bridge smoke

If the Cockpit checkout already has an Operator, add:

```bash
--operator-id opr_123
```

The harness executes a real `mado_check_mission` tool envelope through the same Python module used by OpenDots.

## Evidence

Every run writes:

```text
.mado/cockpit/integrations/opendots/dogfood/<UTC timestamp>/report.json
```

The report captures:

- upstream drift status;
- files changed by the overlay;
- verification commands and outputs;
- optional Python bridge smoke result.

The directory is under the existing ignored `.mado/` tree.

## OpenDots changes applied

The server patch:

- imports `madoCockpitTools` and `callMadoCockpit`;
- registers the five MADO server tools beside page/computer tools;
- forwards `mado_review_human_gate` as a client HITL tool;
- adds the two-phase Human Gate rule to the Dot prompt.

The client patch:

- registers the M1.4 renderers;
- keeps MADO-only tool-call messages visible in the transcript;
- loads the renderer CSS.

## Safety / drift properties

```text
upstream changed        -> stop on SHA drift
anchor changed          -> stop on anchor mismatch
apply twice             -> second apply is no-op
OpenDots -> Cockpit     -> local process, shell=false
tool execution          -> still bounded by M1.3/M1.2
Human Gate stale card   -> still rejected by gate_id check
verification evidence   -> stored under .mado/
```
