# MPC-M0.1 Plugin Inventory Scanner / Sync Adapter

## Purpose

MPC-M0.1 compares an observed ChatGPT plugin inventory with the static MPC-M0.0 Plugin Capability Registry.

It answers:

- Which plugins are newly observed?
- Which registered plugins show observable drift?
- Which registered plugins are missing from a complete inventory?
- Which plugins are unchanged?
- Which new plugins should become enrichment candidates?

M0.1 is an observation and planning layer. It does not install, connect, activate, disable, or execute plugins.

## Flow

Plugin inventory snapshot
  -> normalize observed plugins
  -> compare by plugin_ref
  -> new / changed / missing / unchanged
  -> candidate proposals
  -> human / promotion gate later
  -> registry remains unchanged

## Snapshot contract

The scanner accepts either a JSON list or an object with:

- source
- complete
- observed_at
- metadata
- plugins

Observed plugin records accept the same core fields returned by plugin inventory/search surfaces:

- id
- name
- display_name
- description
- status
- installation_policy
- installed

The canonical matching key is name/plugin_ref. Provider-specific plugin IDs are retained as evidence but are not the stable MPC routing key.

## Complete versus incomplete snapshots

This distinction is mandatory.

Search and recommendation surfaces are not guaranteed to return every available plugin. Therefore:

- complete=false is the default
- incomplete snapshots never produce missing classifications
- complete=true is required before absence can be treated as missing

An incomplete scan emits:

snapshot_incomplete_missing_not_evaluated

This prevents a narrow search result from accidentally disabling or demoting capabilities that were simply not returned.

## Diff classes

### new

Observed plugin_ref is not present in the registry.

M0.1 emits a candidate proposal containing observed identity and platform state plus a requires_enrichment list.

It always sets:

suggested_status = candidate
auto_activate = false

### changed

A matching registry entry shows observable drift.

M0.1 currently detects:

- display_name_changed
- platform_availability_changed
- active_but_not_installed
- candidate_now_installed

These are observations only. The registry is not mutated.

### missing

Only evaluated for complete snapshots.

A registered plugin_ref is missing from the complete observed inventory.

No automatic disable occurs.

### unchanged

Observed identity and state do not trigger any current drift rule.

## Sync adapter

PluginRegistrySyncAdapter builds an inspectable sync plan from two files:

mado-plugin-inventory fixtures/plugins/mpc-m0.0.json fixtures/plugins/mpc-m0.1-observed.json

Write the plan to a file:

mado-plugin-inventory fixtures/plugins/mpc-m0.0.json fixtures/plugins/mpc-m0.1-observed.json --output plugin-sync.json

The sync plan records:

- summary counts
- new candidate proposals
- changed entries and reason codes
- missing entries when safe to evaluate
- unchanged entries
- warnings
- registry_mutated=false
- promotion_required

## October 2026 dogfood fixture

The observed fixture represents the current madowaku-oriented inventory slice.

Registered and observed:

- GitHub
- Context7
- Superpowers
- OpenAI Developers
- Google Drive
- Figma
- tldraw
- Canva
- Adobe
- PostHog
- Firecrawl
- Google Calendar

Newly observed relative to M0.0:

- Railway
- GitBook

Because the fixture came from search-oriented discovery rather than a guaranteed full inventory export, it is marked complete=false. Missing is therefore intentionally not evaluated.

## Safety contract

M0.1 never:

- auto-activates a new plugin
- promotes a candidate because it became installed
- disables an active entry because it was not found in an incomplete search
- mutates the source registry
- grants plugin permissions
- invokes plugin actions

## Golden fixtures

Tests verify:

- 14 observed records against 12 registered records
- Railway and GitBook become candidate proposals
- incomplete snapshots never create false missing entries
- complete snapshots can report missing entries
- active-but-uninstalled drift is reported without demotion
- candidate-now-installed drift is reported without promotion
- platform disable is reported as availability drift
- duplicate observed refs fail closed
- sync planning leaves the registry byte-for-byte unchanged
- CLI output is inspectable JSON

## Next milestone

MPC-M0.2 should add Candidate Enrichment / Promotion Gate.

That layer can take a candidate proposal and gather the missing routing fields:

- provider
- capability
- layers
- cost class
- permissions
- risk tags
- consumers
- fallbacks
- evidence

Only after enrichment and explicit promotion should a candidate become active.
