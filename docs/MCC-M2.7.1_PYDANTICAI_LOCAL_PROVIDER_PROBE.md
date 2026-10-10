# MCC-M2.7.1 PydanticAI Local Runtime / Provider Contract Probe

## Purpose

Exercise a **real PydanticAI Agent** (not a hand-rolled simulation), while
keeping the backing model strictly **PydanticAI TestModel**, a procedural
test double. This is not a model-quality benchmark, a real LLM, or a live
provider integration.

This milestone is stacked on
[MCC-M2.7-AS Agent Substrate Compatibility Lab](MCC-M2.7_AS_AGENT_SUBSTRATE_COMPATIBILITY_LAB.md).
The existing Cockpit Operator remains authoritative. **Nothing is promoted
to production**, even when this local probe reports PASS.

## Installation / local commands

~~~bash
pip install -e ".[dev,pydanticai-probe]"
pytest -q tests/test_pydanticai_probe.py
python scripts/pydanticai_probe_smoke.py
mado-cockpit-pydanticai-probe \
  --baseline fixtures/substrate/mcc-m2.7-agent-substrate-parity.json \
  --probe fixtures/substrate/mcc-m2.7.1-pydanticai-testmodel.json \
  --root . \
  --out /tmp/mcc-m2.7.1-pydanticai-report.json
~~~

On Windows PowerShell, replace the final output path with a local path.
Use a temporary value for --root if you don't want action receipts stored in
your project.

The optional dependency is **pydantic-ai-slim**. It is deliberately kept out
of Cockpit's standard installation. Installing the extra downloads ordinary
Python packages, but neither a provider API call nor a cloud model call is
made by the probe. The dedicated CI workflow installs the extra and runs the
actual Agent in a job with empty provider API key environment variables.

## How it works

1. Validate the pre-existing M2.7-AS baseline and a separate, strict
   mado.pydanticai-local-probe.input.v1 canned-output fixture.
2. Instantiate PydanticAI TestModel directly, register a typed OutputModel
   and a single no-argument fixture_lookup tool, then call Agent.run_sync.
3. Disable all non-test model requests inside the execution scope using
   pydantic_ai.models.ALLOW_MODEL_REQUESTS = False, restoring the prior value.
4. Execute fixture_lookup through the existing ActionPolicyGateway with the
   existing Human Control Lease fence. This tool only returns an in-memory
   mission objective. There is no shell, browser, network, external service,
   database mutation, or arbitrary user-supplied code.
5. Verify the model actually called the permitted tool once, check the
   registered tool schema and validate model output using strict Pydantic
   classes with forbid-extra fields.
6. Convert the observed result into a replay envelope and pass it through
   the M2.7-AS Evidence/Temporal Memory/Trace/Parity evaluator.
7. Emit mado.pydanticai-local-probe.report.v1 with provider provenance,
   tool admission count, agent model request count, parity verdict and
   non-promotable scope.

In this version memory facts come from the original replay fixture, not
Graphiti; evidence hashes are claimed in fixture data and not verified
against live files. The derived trace is an adapter lifecycle trace, **not**
a Langfuse export. The first actual tool invocation is policy-checked in
PydanticAI itself; M2.7-AS separately replays normalized tool calls.

## Safety and negative testing

- The user-controlled input accepts only mode = testmodel and the exact
  schema/model_output fields. No API provider names, endpoints, credentials
  or tool implementations are accepted.
- Unknown/malformed fixture input fails before an Agent is constructed.
- Invalid model output, denied human-control lease, missing tool invocation,
  schema mismatch and PydanticAI run exceptions HOLD.
- The probe is fail-closed and emits stable reason codes rather than raw
  provider exceptions or potentially sensitive payload data.
- PydanticAI's test model may use model-request bookkeeping but generates
  output procedurally, not through a paid inference service.
- PASS is contract interoperability evidence only. It does not prove
  inference quality, safety of arbitrary third-party tools, sandbox
  isolation, real model alignment, or production readiness.

## Roadmap

MCC-M2.7.2 may introduce a *bounded local FunctionModel* to test distinct
decision paths and failure recovery, without paying for external providers.
Actual hosted provider execution, Graphiti, E2B, Langfuse and DeepEval are
separate gates requiring opt-in, expense bounds and original evidence.
