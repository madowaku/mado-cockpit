# MCC-M2.3 Policy Shadow / Action Equivalence / Initiator Context Result — 2026-10-04

MCC-M2.3 was validated as the observation and retry-fencing layer on top of the verified M2.2 Action Policy Gateway.

## Passing runs

### Cockpit CI

- Workflow: `CI`
- Run ID: `37183598438`
- Commit: `1e733cace547a2947ad0ad38c5c48ebe1c660448`
- Result: `success`

```text
135 passed
```

### Policy Shadow

- Workflow: `Policy Shadow`
- Run ID: `37183596274`
- Commit: `7e7cbd48ad824716727e22b8dbb16fec7516c0e9`
- Result: `success`
- Focused M2.3 tests: `34 passed`
- Evidence artifact: `policy-shadow-evidence`
- Artifact ID: `11295723822`
- Artifact SHA-256: `cdbbf93971c99f9752c55c1f866b1d630dbe26347d0dd68863c99aae1a9c9710`

### M2.2 regression after M2.3

The Action Policy Gateway workflow was cleaned up to restore an explicit `set -o pipefail` on its focused pytest pipeline.

- Workflow: `Action Policy Gateway`
- Run ID: `37183654169`
- Commit: `41c66f925e9433fefce9d3470be6379e227d7472`
- Result: `success`

The real Streamable HTTP governed write smoke remained green.

## Real Operator M2.3 smoke

The dedicated M2.3 workflow created a real Git-backed Cockpit Project, Mission and Operator and exercised the production-shaped `OpenDotsToolSurface`.

The result was:

```json
{
  "schema": "mado.policy-shadow-smoke.v1",
  "version": "MCC-M2.3",
  "ok": true,
  "operator_id": "opr_fbef2e82b68a",
  "shadow": {
    "receipt_id": "actdec_2914f7bab527",
    "live_allowed": true,
    "shadow_allowed": false,
    "shadow_delta": "would_deny",
    "dispatch_status": "dispatched"
  },
  "equivalence": {
    "digest": "d31ffdf4b685c7c5d6fb36135abf99c0f886a1e0f592f48a0af74b9208a56bb2",
    "refused_receipt_id": "actdec_661d4d893bef",
    "fenced_receipt_id": "actdec_b5589dda14b1",
    "equivalent_to_receipt_id": "actdec_661d4d893bef",
    "same_context_fenced": true,
    "new_context_dispatched": true
  },
  "initiator": {
    "actor": "dot:scout",
    "context": {
      "kind": "chat",
      "source": "opendots:scout",
      "context_id": "thread-shadow"
    },
    "fence_scope": "chat:opendots:scout:thread-shadow"
  },
  "shadow_event_count": 1
}
```

## Policy shadow is non-enforcing

The live policy explicitly allowed the bounded MADO action while the shadow policy explicitly denied it.

Observed result:

```text
live_allowed    true
shadow_allowed  false
shadow_delta    would_deny
dispatch_status dispatched
```

The shadow candidate did not block or alter live execution.

The receipt preserves both decisions and the Cockpit event spine records:

```text
action.shadow.evaluated
```

A broken shadow rule is also non-enforcing. It is recorded as a shadow `policy_error` while the live policy remains authoritative.

This gives MADO a safe policy bake-off path before enforcement promotion.

## Full digest vs equivalence digest

M2.3 separates two identities.

### Full execution digest

`ActionCandidate.digest` includes:

```text
stable side-effect identity
+
initiator kind
initiator source
initiator context
```

This is still used for approval revalidation.

If the same side effect is handed from one initiator context to another, it is not treated as the exact same approved execution.

### Stable equivalence digest

`ActionCandidate.equivalence_digest` includes:

```text
action
effect
target kind
target
arguments
actor
capability
mission
```

and excludes volatile transport IDs and initiator context.

Two retries of the same side effect can therefore be recognized even when they use different tool-call IDs.

## Same-context retry fence

The smoke first sent an action through a policy with no allow rule.

That produced the durable refusal:

```text
actdec_661d4d893bef
```

A second call used:

- the same action;
- the same target;
- the same arguments;
- the same actor;
- a new tool-call ID;
- the same OpenDots thread.

Even though the second surface used a permissive live policy, M2.3 refused it before dispatch because an equivalent action had already been declined in the same initiator context.

The new receipt was:

```text
actdec_b5589dda14b1
```

with:

```text
source = equivalent_fenced
equivalent_to_receipt_id = actdec_661d4d893bef
```

This prevents an agent from silently recreating a declined write with a fresh transport ID.

## Pending-action fence

Focused tests also prove the concurrent case.

While the first equivalent action has an approved receipt with:

```text
dispatch_status = pending
```

a nested second equivalent attempt in the same initiator context is refused.

The second dispatch callback is never entered.

Once the first action finishes and becomes `dispatched`, it is no longer a pending fence.

## Intentional retry through a new context

The same side effect was then retried from a different OpenDots thread.

Because retry fencing is scoped by both:

```text
equivalence_digest
+
initiator.fence_scope
```

the new thread was not silently conflated with the previous declined conversation context.

The retry dispatched successfully.

M2.3 therefore distinguishes:

```text
silent same-context retry  -> fence
explicit new-context retry -> evaluate normally
```

## Actor and initiator are now separate

M2.2 had only an actor string.

M2.3 receipts separate:

```text
actor
= whose execution authority/path is used

initiator
= what caused the action attempt
```

The real OpenDots smoke recorded:

```json
{
  "actor": "dot:scout",
  "initiator": {
    "kind": "chat",
    "source": "opendots:scout",
    "context_id": "thread-shadow"
  }
}
```

The supported initiator kinds are:

```text
person
chat
routine
replay
system
```

This is the policy dimension needed to distinguish a user-triggered action from a future routine or replay that uses the same underlying authority.

## OpenDots mapping

For the existing OpenDots bridge:

```text
actor = dot:<dot_id>
initiator.kind = chat
initiator.source = opendots:<dot_id>
initiator.context_id = thread_id
```

When there is no thread ID, the current adapter can use Space ID as the context scope.

This makes equivalence fencing immediately useful in OpenDots.

## ChatGPT MCP boundary

The current M2.0 MCP bridge identifies its path with:

```text
dot_id = chatgpt-mcp
```

but it does not yet expose a trustworthy ChatGPT conversation identifier to the M1.3 tool envelope.

M2.3 therefore records:

```text
actor = dot:chatgpt-mcp
initiator.kind = chat
initiator.source = chatgpt-mcp
initiator.context_id = null
```

A null context deliberately disables retry fencing for that route.

This is an intentional fail-safe boundary. MADO does not invent a process-global or request-derived pseudo-conversation ID that could incorrectly fence unrelated ChatGPT conversations.

When a stable MCP conversation/session scope becomes available, it can be mapped into `context_id` without changing the M2.3 receipt schema.

## Receipt additions

The durable M2.3 action receipt adds:

```text
initiator
equivalence_digest
fence_scope
equivalent_to_receipt_id
shadow_decision
shadow_delta
```

The M2.2 privacy boundary remains intact:

- raw action arguments are not persisted;
- only their canonical digest is stored;
- initiator context is a technical scope identifier, not message content.

## Regression evidence

The M2.3 core changes were exercised while the existing integration suite remained green:

```text
OpenDots Dogfood              success
OpenDots Browser E2E          success
OpenDots Browser Chat         success
OpenDots Conversation Replay  success
ChatGPT MCP Bridge            success
Action Policy Gateway         success
```

The M2.3 design therefore extends the shared Action Gateway beneath both OpenDots and ChatGPT without changing the existing Human Gate or MCP wire contracts.

## Deferred boundary

M2.3 intentionally does not add:

- arbitrary CEL/user-authored expression rules;
- automatic shadow-policy file promotion;
- fabricated ChatGPT conversation scopes;
- human takeover/control leases.

Human interactive computer/browser control remains the natural M2.4 boundary.

## MCC-M2.3 status

```text
MCC-M2.3 Policy Shadow / Action Equivalence / Initiator Context
status: VERIFIED

live policy remains authoritative: passed
shadow deny does not block live allow: passed
shadow allow does not rescue live deny: passed
shadow policy error is observational: passed
shadow event ledger: passed
stable equivalence digest: passed
full approval digest includes initiator: passed
refused same-context retry fencing: passed
pending same-context retry fencing: passed
equivalent receipt lineage: passed
new-context intentional retry: passed
actor / initiator separation: passed
OpenDots thread context mapping: passed
ChatGPT null-context safety boundary: passed
focused tests: 34 passed
Cockpit CI: 135 passed
real Operator smoke: passed
M2.2 governed MCP write regression: passed
```
