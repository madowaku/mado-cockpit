# MCC-M2.6 Design Harness / Living UI Spec

M2.6 adds a deterministic, review-gated UI specification layer to the existing Cockpit control plane. It does **not** add another generative-design service or reimplement the action policy gateway.

## Boundary

```text
conversation / builder notes / UX review
        |
        v
structured change (JSON; source_ref + initiator)
        |
        v
proposal and semantic preview (NO spec mutation)
        |
        v
explicit human review (approve / reject)
        |
        v
revisioned JSON --> generated spec.md
       |                   |
       +--> immutable revisions + Event Spine
```

- Schema: `mado.living-ui-spec.v1` and `mado.design-change.v1`.
- State: `.mado/cockpit/design_specs/<mission-id>/spec.json`.
- Human-readable projection: `spec.md`, generated from JSON; do not edit manually.
- History: `revisions/0000.json`, `0001.json`, etc.
- Proposals: `proposals/dchg_<digest>.json`, content-addressed by mission, source, base revision, initiator and operations.
- The underlying Mission **must already exist**. Its ID and initial title bind the spec to the Cockpit Mission Envelope.
- `source_ref` is caller-asserted provenance (for example a conversation or task reference), **not** verified conversation authenticity.
- `--reviewer` and `--human-confirm` are explicit local-operator attribution and confirmation, **not** identity authentication. Do not expose this command as an unguarded agent tool.
- No LLM inference, internet access, paid API, Figma dependency, browser automation or implicit deployment.
- A spec revision is a design contract, not proof that the UI has been implemented.

## First dogfood: mado-cockpit itself

From a terminal in the Cockpit repository, with the project initialized:

```bash
mado-cockpit mission create MCC-UI "MADO Cockpit UI"
mado-cockpit design-spec init MCC-UI
mado-cockpit design-spec propose MCC-UI --file fixtures/design_spec/mcc-m2.6-cockpit-ui.json
mado-cockpit design-spec proposals MCC-UI
mado-cockpit design-spec preview MCC-UI dchg_<the-id-from-propose>
mado-cockpit design-spec show MCC-UI
```

Inspect the JSON proposal and its recorded operations. Only then, as the person responsible for the decision:

```bash
mado-cockpit design-spec review MCC-UI dchg_<the-id-from-propose> --decision approve --reviewer human:owner --human-confirm --note "Approved initial navigation contract"
mado-cockpit design-spec validate MCC-UI
mado-cockpit design-spec history MCC-UI
```

The `show` command shows **current accepted** state, not a pending draft. To reject: `--decision reject` instead. To add a second change, produce a new JSON input with `base_revision: 1`.

For a new project, run `mado-cockpit init --project-id my-project` first.

## Operation contract

| Operation | Field | Value |
|---|---|---|
| `set` | `goal` | string |
| `set` | `audiences`, `principles`, `constraints` | string array |
| `upsert` | `screens` | screen with `id`, `title`, `purpose`, optional `states`, `actions`, `accessibility` |
| `upsert` | `journeys` | journey with `id`, `title`, non-empty `steps`, optional `done_when` |
| `upsert` | `open_questions` | question with `id`, `question`, optional `choices` |
| `remove` | `screens`, `journeys`, `open_questions` | `id` |
| `resolve_question` | `open_questions` | `id`, answer string in `value` |
| `record_decision` | `decisions` | `id`, `statement`, `rationale` |

A screen action has `id`, `label`, and optional `next_screen`. A journey step has `screen_id` and optional `action_id`. Any dangling screen, action, or navigation link invalidates the whole proposal. Decisions are append-only and acquire reviewer, source, and approval timestamp **only when approved**.

## Determinism and safety

- Proposals are immutable intent records; a repeat with the same content yields the same proposal ID.
- Proposal creation validates a shadow copy of the spec. Failed validation does not write a proposal.
- `base_revision` is checked at proposal creation **and** approval. A stale approval fails closed.
- Explicit `--human-confirm` is required, even for rejection.
- Each mutation takes a filesystem lock (atomic directory creation), then writes temp files and replaces them.
- Resolved proposals cannot be approved again; repeating the same approval is idempotent.
- Approved IDs in the spec allow interrupted promotion to be completed without incrementing the revision again.
- `validate` compares the canonical JSON against its latest revision and regenerated Markdown, and checks sequential revision numbering.
- An interrupted writer may leave `.write-lock`. Check that no writer is active before manually removing it.
- An approval is not equivalent to M2.2 action permission, M2.4 control lease, or implementation deploy authorization.

## Acceptance checks

```bash
python -m pytest -q tests/test_design_spec.py
python -m pytest -q
```

Positive path: mission → proposal → explicit approval → one revision → Markdown + revision file + event. Negative paths: absent confirmation, stale approval, unsafe IDs, references to nonexistent screens/actions, decision overwrite, rejected proposals, corrupted Markdown.

## Next: MCC-M2.7

Design Divergence Lab should consume **approved** `spec.json` as input, produce alternative **proposals**, and keep the human approval boundary unchanged. UI screenshot and real browser journey verification are planned for M2.8, not claimed by this milestone.
