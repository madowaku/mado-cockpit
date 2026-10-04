# MCC-M1.6 OpenDots Browser E2E / Human Gate Clickthrough

MCC-M1.6 adds a real Chromium clickthrough on top of the verified M1.5 OpenDots integration.

The test does not use a fake DOM and does not require an external model provider.

## Scope

M1.5 already verifies the OpenDots AG-UI / CopilotKit integration contracts with the real upstream typecheck, production build, and all upstream tests.

M1.6 focuses on the remaining browser boundary:

```text
Chromium
  -> real OpenDots production server
  -> M1.4 Mission Card
  -> M1.4 Human Gate Card
  -> human-equivalent button click
  -> OpenDots E2E-only server route
  -> M1.5 Node subprocess caller
  -> Python M1.3 Tool Surface
  -> real Cockpit Operator / Human Gate
  -> resolution
  -> refreshed Mission Card
  -> Chromium
```

## No external AI dependency

The E2E page is enabled only when:

```text
MADO_COCKPIT_E2E=1
```

It is copied by the M1.6 test overlay, not by the normal M1.5 production integration.

The route:

```text
/api/mado-dogfood/*
```

is therefore test-only.

The browser calls the same `mado-cockpit-caller.ts` and Python tool surface used by the real OpenDots integration. No alternate Cockpit mutation path exists.

## Real Cockpit fixture

The harness creates a real Operator and opens a real Human Question Gate:

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

Initial state:

```text
awaiting_human
```

The Chromium script explicitly clicks:

```text
stay_free
```

Expected final state:

```text
awaiting_builder
human_gate = null
```

## Browser assertions

The Playwright script verifies:

1. the Mission Card renders `awaiting_human`;
2. the Human Gate card renders the real question;
3. the explicit `stay_free` button can be clicked;
4. the Cockpit resolution card is returned;
5. the refreshed Mission Card renders `awaiting_builder`;
6. a direct final status fetch reports no open Human Gate.

The workflow then independently reads the Operator from Python and asserts the same final state.

## Visual evidence

Two full-page screenshots are captured:

```text
01-human-gate-open.png
02-human-gate-resolved.png
```

Additional evidence includes:

```text
browser-result.json
cockpit-final.json
server.log
```

## CI

Workflow:

```text
.github/workflows/opendots-browser-e2e.yml
```

It checks out a fresh real `CopilotKit/OpenDots@main`, applies M1.5 plus the M1.6 E2E overlay, typechecks and builds OpenDots, installs Chromium, starts the production server, and executes the clickthrough.

## Drift behavior

M1.6 inherits M1.5 drift checks and additionally pins the OpenDots `src/server/app.ts` blob used by the test route patch.

Anchor or SHA drift fails closed rather than guessing a new patch location.
