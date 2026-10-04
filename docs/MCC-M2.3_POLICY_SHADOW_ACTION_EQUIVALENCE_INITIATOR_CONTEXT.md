# MCC-M2.3 Policy Shadow / Action Equivalence / Initiator Context

MCC-M2.3 adds three governance capabilities on top of the verified M2.2 Action Policy Gateway:

1. non-enforcing shadow policy evaluation;
2. stable action equivalence and retry fencing;
3. first-class initiator context separate from actor authority.

## 1. Policy shadow

The live policy remains the only enforcing policy.

An optional shadow policy is evaluated against the same authoritative ActionCandidate after revalidation, but its result can never change whether the action dispatches.

Each receipt can now contain:

```text
decision
shadow_decision
shadow_delta
```

Possible shadow deltas:

```text
same
would_allow
would_deny
```

Examples:

```text
live allow + shadow deny
  -> dispatch
  -> shadow_delta = would_deny

live deny + shadow allow
  -> refuse
  -> shadow_delta = would_allow
```

A broken shadow rule is recorded as a shadow `policy_error` but does not affect the live decision.

A shadow evaluation also appends:

```text
action.shadow.evaluated
```

to the Cockpit event spine.

This provides a safe bake-off path before a candidate policy is promoted to enforcement.

## 2. Action equivalence

M2.3 separates two hashes.

### Full action digest

`ActionCandidate.digest` contains:

- the stable side-effect identity;
- actor authority;
- initiator kind/source/context.

This remains the digest used for approval revalidation.

Changing initiator context therefore changes the approved execution identity.

### Equivalence digest

`ActionCandidate.equivalence_digest` represents the stable side effect:

```text
action
effect
target_kind
target
arguments
actor
capability
mission_id
```

It deliberately excludes initiator context.

Volatile tool-call IDs and request IDs were already outside the candidate and therefore never participate in equivalence.

## 3. Retry fencing

Equivalence alone does not block anything.

The fence key is:

```text
equivalence_digest
+
initiator.fence_scope
```

The current scope is derived from:

```text
initiator.kind
initiator.source
initiator.context_id
```

Within the same scope, a new equivalent action is refused when a prior equivalent receipt is:

```text
status = refused
OR
dispatch_status = pending
```

The new durable receipt records:

```text
source = equivalent_fenced
equivalent_to_receipt_id = <prior receipt>
```

A previously dispatched action does not create this fence.

A different initiator context can intentionally retry the same side effect.

This is the first MADO defense against an agent silently rephrasing or recreating a declined write with a new tool-call ID.

## 4. Actor vs initiator

Receipts now separate:

```text
actor
= whose execution authority/path is being used

initiator
= what caused this attempt
```

The initiator object is:

```json
{
  "kind": "chat",
  "source": "opendots:scout",
  "context_id": "thread-123"
}
```

Supported kinds:

```text
person
chat
routine
replay
system
```

This distinction allows later policy rules such as:

```text
allow a person-initiated publish
deny the same publish from a nightly routine
```

without pretending they are different actors.

## Current OpenDots mapping

For OpenDots tool calls:

```text
actor = dot:<dot_id>
initiator.kind = chat
initiator.source = opendots:<dot_id>
initiator.context_id =
  thread_id when present,
  otherwise space_id
```

This makes same-thread retry fencing available immediately.

## Current ChatGPT MCP mapping

M2.0 currently supplies:

```text
dot_id = chatgpt-mcp
```

but does not yet expose a trustworthy conversation/thread identifier through the MCP bridge.

Therefore M2.3 deliberately records:

```text
actor = dot:chatgpt-mcp
initiator.kind = chat
initiator.source = chatgpt-mcp
initiator.context_id = null
```

and does **not** enable equivalence fencing for that path yet.

This is safer than inventing a fake or process-global ChatGPT conversation scope.

When a stable MCP session/conversation identifier is available, it can be mapped into `context_id` without changing the receipt schema.

## Privacy boundary

Receipts still do not store raw action arguments.

M2.3 adds:

```text
equivalence_digest
fence_scope
initiator
shadow_decision
shadow_delta
equivalent_to_receipt_id
```

but preserves M2.2's arguments-digest-only rule.

Initiator context must remain a technical session/thread identifier, never message content or credentials.

## Dogfood

The M2.3 smoke uses a real Cockpit Project, Mission and Operator.

It proves:

1. live allow + shadow deny still dispatches;
2. the receipt says `would_deny`;
3. a default-denied write creates a refusal receipt;
4. a second equivalent write with a new tool-call ID in the same OpenDots thread is fenced;
5. the fenced receipt points to the original refusal;
6. the same action from a new thread can intentionally retry and dispatch;
7. actor and initiator are recorded separately.

## Deferred

M2.3 does not add:

- arbitrary CEL or user-authored expression evaluation;
- automatic shadow-policy file loading;
- ChatGPT retry fencing without a trustworthy conversation scope;
- human computer takeover leases.

The final item remains the natural M2.4 boundary.
