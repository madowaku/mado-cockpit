# MCC-M1.5 Dogfood Result — 2026-10-03

MCC-M1.5 was validated against a real checkout of `CopilotKit/OpenDots@main` in GitHub Actions.

## Passing run

- Workflow: `OpenDots Dogfood`
- Run ID: `37131626384`
- Result: `success`
- mado-cockpit commit: `945e24103caae37443fd1c0f01803ba6042bfb55`

The workflow checked out both repositories independently, applied the M1.5 overlay to the real OpenDots tree, installed OpenDots dependencies under Node 24, and ran the upstream verification suite.

## Verified gates

```text
real OpenDots checkout        PASS
M1.5 upstream SHA preflight   PASS
overlay apply                 PASS
git diff --check              PASS
npm run typecheck             PASS
npm run build                 PASS
npm test                      PASS
Node -> Python caller smoke   PASS
dogfood evidence upload       PASS
```

OpenDots upstream test result:

```text
35 test files passed
164 tests passed
```

The production Vite build also completed successfully after transforming 10,975 modules.

## Node -> Python smoke

The real OpenDots-side `mado-cockpit-caller.ts` was loaded with `tsx` and invoked:

```text
mado_check_mission
operator_id = opr_missing_dogfood_fixture
```

The Operator was intentionally nonexistent. The important assertion was that the full local bridge completed and returned a stable MADO tool result rather than crashing or bypassing the adapter:

```json
{
  "tool_call_id": "mcc-m1.5-node-python-smoke",
  "ok": false,
  "error": {
    "code": "cockpit_read_error"
  }
}
```

This proves the executed path:

```text
OpenDots TypeScript
  -> child_process.spawn(shell=false)
  -> Python module
  -> M1.3 Tool Surface
  -> Cockpit read boundary
  -> structured result
  -> OpenDots
```

## Bugs found by real dogfood

### 1. CopilotKit v2 renderer contracts were stricter than the fixture

The first real typecheck found:

- `unknown` could not be rendered directly as a React node;
- named `useRenderTool` registrations require a `parameters` schema.

The renderer was corrected to use explicit boolean narrowing and canonical Zod parameter schemas.

### 2. Client tool definitions must remain canonical

The second real run passed typecheck/build but failed two upstream security-oriented tests.

The initial M1.5 patch forwarded client-supplied matching tool definitions with `input.tools.filter(...)`. OpenDots intentionally does not trust those definitions. It detects an offered tool by name, then forwards its own canonical `pageReviewTool`.

M1.5 was changed to preserve that boundary for both tools:

```text
client offers review_space_page name
  -> inject canonical pageReviewTool

client offers mado_review_human_gate name
  -> inject canonical madoHumanGateReviewTool
```

No client-supplied description or parameters are trusted.

This correction restored all 164 upstream tests.

## Evidence location

Each dogfood run writes local structured evidence under:

```text
.mado/cockpit/integrations/opendots/dogfood/<UTC timestamp>/report.json
```

The passing GitHub Actions run uploaded the evidence as the `opendots-dogfood-evidence` artifact.

## M1.5 status

```text
MCC-M1.5 OpenDots Real Integration / Dogfood Harness
status: VERIFIED
upstream: CopilotKit/OpenDots main, pinned 2026-10-03
transport: local subprocess
OpenDots upstream tests: 164/164 passed
real bridge smoke: passed
```
