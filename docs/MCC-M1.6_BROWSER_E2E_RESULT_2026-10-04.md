# MCC-M1.6 Browser E2E Result — 2026-10-04

MCC-M1.6 was validated against a fresh real checkout of `CopilotKit/OpenDots@main` using Chromium and a real MADO Cockpit Operator/Human Question Gate.

## Passing run

- Workflow: `OpenDots Browser E2E`
- Run ID: `37164868552`
- Result: `success`
- mado-cockpit commit: `3d54c553dc8ea4329d2fc8929686d54d4175594c`
- Evidence artifact: `opendots-browser-e2e-evidence`
- Artifact ID: `11288553196`
- Artifact SHA-256: `63a2adec037fb177ad726268c83152960faae178b81d5d87497d796c75020e0f`

The normal Cockpit CI also passed at the same commit:

```text
80 passed
```

The M1.5 real OpenDots dogfood workflow also remained green at the same commit.

## Browser path exercised

```text
Chromium
  -> OpenDots production build
  -> /mado-dogfood
  -> MadoToolCard
  -> MadoHumanGateCard
  -> explicit stay_free click
  -> /api/mado-dogfood/resolve
  -> mado-cockpit-caller.ts
  -> child_process.spawn(shell=false)
  -> python -m mado_cockpit.opendots_tools
  -> mado_answer_human_gate
  -> real OperatorManager.resolve_gate
  -> refreshed mado_check_mission
  -> OpenDots browser
```

## Real fixture

The passing run created:

```text
mission_id  MCC-M1.6-E2E-816bfc70
operator_id opr_3855b2402a58
gate_id     gate_686d92b72af9
```

The Human Gate was:

```text
question:
Enable the paid provider for this run?

materiality:
cost

choices:
stay_free
enable_paid

recommendation:
stay_free

safe_default:
stay_free
```

Initial Operator state:

```text
awaiting_human
```

The Chromium scenario clicked the explicit `stay_free` button.

The browser step passed, then an independent Python verification step also passed with the expected final contract:

```text
status      awaiting_builder
human_gate  null
```

## Real OpenDots gates passed

```text
fresh OpenDots checkout        PASS
M1.5 drift preflight           PASS
M1.6 app.ts drift preflight    PASS
browser overlay apply          PASS
git diff --check               PASS
npm run typecheck              PASS
npm run build                  PASS
Chromium install               PASS
OpenDots production start      PASS
Human Gate browser click       PASS
Cockpit final-state assertion  PASS
evidence upload                PASS
```

The OpenDots production build completed successfully.

## Evidence captured

The browser job uploaded five evidence files, including the two full-page screenshots:

```text
01-human-gate-open.png
02-human-gate-resolved.png
browser-result.json
cockpit-final.json
server.log
```

The workflow also preserves the setup fixture JSON and server log when available.

## Bugs found while dogfooding M1.6

### 1. Patch marker prefix collision

The first harness version used marker names where:

```text
MADO_COCKPIT_M1_6_DOGFOOD_ROUTE
```

was a prefix of:

```text
MADO_COCKPIT_M1_6_DOGFOOD_ROUTE_IMPORT
```

The import marker therefore made the harness incorrectly believe the route marker already existed.

The same risk existed for the page markers.

The harness now checks complete marker comment lines, preserving idempotence without prefix collisions.

### 2. React unknown-value render narrowing

The first real OpenDots typecheck rejected E2E render guards such as:

```text
unknown && <JSX />
```

because `unknown` is not a ReactNode.

The page now uses explicit defined/boolean narrowing before rendering.

### 3. Stable post-click assertion

The initial scenario considered asserting a transient Human Gate receipt inside the card.

The final scenario instead asserts the durable state transition:

```text
awaiting_human
  -> explicit stay_free click
  -> awaiting_builder
  -> human_gate = null
```

This makes the E2E test validate the real outcome rather than a timing-sensitive intermediate render.

## Safety boundary

The browser-only route exists only in the M1.6 test overlay and is registered only when:

```text
MADO_COCKPIT_E2E=1
```

It is not part of the normal M1.5 production overlay.

Even in E2E mode, the route does not mutate Cockpit directly. It invokes the same M1.5 Node caller and M1.3 Python tool surface used by the real integration.

## M1.6 status

```text
MCC-M1.6 OpenDots Browser E2E / Human Gate Clickthrough
status: VERIFIED

real OpenDots production build: passed
real Chromium click: passed
explicit human choice: stay_free
Cockpit transition: awaiting_human -> awaiting_builder
Human Gate cleared: yes
Cockpit CI: 80 passed
M1.5 regression dogfood: passed
```
