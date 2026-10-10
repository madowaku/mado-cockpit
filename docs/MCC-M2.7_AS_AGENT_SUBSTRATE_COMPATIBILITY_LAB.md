# MCC-M2.7-AS Agent Substrate Compatibility Lab

## Scope and collision note

MCC-M2.7-AS is the **Agent Substrate Compatibility Lab** milestone.
The repository also has a separate, currently open M2.7 *Screenshot / Visual
Evidence* PR (#12). This module uses the distinct suffix M2.7-AS and the
substrate paths below to avoid rewriting that independent work.

The lab compares **two deterministic, free, offline replay snapshots** under
the same mission contract. It does not instantiate an LLM, an OSS agent
framework, a cloud sandbox, or any network client. A PASS means *offline
contract parity* only, **never production approval**.

## Why a compatibility lab instead of installing all ten frameworks

- Keep the existing Cockpit Operator, Action Policy Gateway and Human Control
  Lease as the system of record.
- Treat PydanticAI (typed runtime), Graphiti (temporal knowledge), E2B
  (sandbox), Langfuse (traces), and DeepEval (evaluation) as optional,
  interchangeable **unintegrated provider slots**.
- Do not introduce an alternative top-level orchestrator. LangGraph, Mastra
  and Agno can be tested in later opt-in adapters without replacing Operator.
- Keep first stage independent of API keys, paid services and optional deps.

## Contract layout

The fixture schema is mado.agent-substrate.fixture.v1. A fixture contains:

- mission: stable ID, objective and required evidence kinds;
- as_of: timezone-aware reference time for knowledge projections;
- exactly two runs, each with unique runtime label and adapter = replay;
- outcome: completion status, JSON object result, and evidence descriptors;
- memory: sourced validity intervals (valid_from, valid_to) for each fact;
- execution: explicitly declared fixture-only, no network, no code execution,
  zero cost;
- trace: sourced event records, including mission.started,
  outcome.recorded, evaluation.completed;
- tool_calls: simulated actions checked by the **existing**
  ActionPolicyGateway. The *only* permitted call is a read-only
  fixture.lookup with target_kind fixture. Dispatch is a deliberate NO-OP.

Evidence item hashes are **claimed digests** in the fixtures; there is no
actual file-integrity verification here. The existing Cockpit evidence
pipeline remains authoritative for live files and QA artifacts.

Outputs use mado.agent-substrate.report.v1. Outcome equality compares
status, structured result and the content hashes associated with evidence
kinds. Memory equality compares active knowledge at as_of rather than old
history. Trace coverage, evidence kinds, run completion, tool policy,
memory conflicts and execution boundary are checked separately.

Any mismatch, denied tool or unsafe execution claim produces status=hold.
Malformed fixture inputs are rejected before any replay policy dispatch.
A hold exits the CLI with code 2, an invalid input with code 1, and an
offline parity pass with code 0. Reports deliberately omit raw prompts,
raw evidence, and provider credentials.

## Run

With Python >=3.11 and the repository package installed:

    pip install -e ".[dev]"
    mado-cockpit-substrate fixtures/substrate/mcc-m2.7-agent-substrate-parity.json --root . --out /tmp/mcc-m2.7-as-report.json
    pytest -q tests/test_substrate_lab.py
    python scripts/substrate_lab_smoke.py

Run under Windows PowerShell by replacing the /tmp output path with a path
in a temporary directory. Generated policy receipts are stored under
<root>/.mado/cockpit/action_decisions as in MCC-M2.2/M2.4.

For a non-installed source checkout:

    PYTHONPATH=src python -m mado_cockpit.substrate_lab fixtures/substrate/mcc-m2.7-agent-substrate-parity.json --root .

Set --root to a scratch directory if you do not want audit receipts written
inside the project.

## Gate mapping

| Contract gate | Existing/new behavior | Promotion meaning |
| --- | --- | --- |
| Runtime | two explicitly replay-only snapshots + typed JSON contracts | same outcome digest, not live framework validation |
| Memory | sourced time-bounded facts + active-state parity | time conflicts or drift hold |
| Sandbox | fixture-only/no-network/no-execution/zero-cost assertion | all other declarations hold; **no sandbox actually launched** |
| Tool control | ActionPolicyGateway + mission-scoped ControlScope | unknown or write-like actions fail closed |
| Human control | MCC-M2.4 lease check on every simulated tool call | active lease fences replay as well |
| Trace | sourced required event types | missing stage holds; not a Langfuse export |
| Evaluation | deterministic checks + regression fixtures | not yet DeepEval scoring |

External adapters are declared **not_integrated** in every report, including
for PydanticAI, Graphiti, E2B, Langfuse, and DeepEval. This field is an
intentional guard against mistaking a fixture replay for a real provider test.

## Acceptance and next steps

The first milestone is accepted when tests prove:

1. Same mission and evidence can pass across two replay envelopes.
2. Outcome/content hash differences and active temporal fact differences hold.
3. Write-like/unknown actions are denied through the existing gateway; active
   Human Control Lease also fences synthetic reads.
4. Claimed network activity, execution, or money makes the gate hold.
5. Invalid schemas cannot produce a PASS and never dispatch a tool.
6. CI's full pytest suite remains green.

Later milestones can add **real, opt-in** adapters with explicit provider
versions, licensing, external-boundary approval, budgets, safe isolated
credentials and live-vs-replay verification. Live adapters must route every
side-effecting action through the same production policy gateway and lease
fence, and produce independently verified evidence. An offline PASS must
never automatically authorize a live execution or a release.
