# MCC-M2.9 OpenUI Adaptive Cockpit UI Lab

## Decision

Integrate **OpenUI Lang 1.0** as a sidecar visual experiment, not as a replacement
for MADO's existing local Python control plane. The official React renderer
receives a two-statement OpenUI Lang program that selects a dedicated read-only
panel (projects / agents / QA). No new action path is exposed.

Use the existing `GET /api/dashboard` through a loopback-only local Vite proxy.
Display only a bounded allowlist of fields from the snapshot, with a sample-only
fallback to make zero-cost testing possible. The source of each view must remain
explicit. Never claim the mock fixture represents actual Cockpit status.

## Initial acceptance gates

| Gate | Mechanism | Evidence |
| --- | --- | --- |
| Isolation | New `integrations/openui-lab` package; no core API changes | git diff |
| Actual OpenUI | `@openuidev/react-lang@1.0.1`, zod-defined component library, real `Renderer` | browser / build |
| Local data | GET-only exact-path proxy + normalization | manual loopback smoke |
| Security | no mutation provider, buttons, or Human Gate completion path | source review / node tests |
| Resilience | sample fallback, friendly connection error, progressive replay | browser screenshot |
| Regression | existing Python pytest plus new Node test/build CI | GitHub checks |

The deterministic producer is deliberate: first prove that the UI registry,
state mapping, streaming parser and data boundaries work without adding an LLM.
Future live generation will be a separately gated iteration; measure response
correctness and accessibility against the baseline rather than assuming lower
token counts guarantee a better user experience.

## Non-goals

No new cloud account, no token/key collection, no write access, no deployment,
no replacing M1.4 two-phase human review, no claims of completed browser E2E.
