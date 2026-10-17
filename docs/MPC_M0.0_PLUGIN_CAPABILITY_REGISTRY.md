# MPC-M0.0 Plugin Capability Registry

## Purpose

MPC-M0.0 turns ChatGPT plugins from ambient conveniences into explicit, inspectable capabilities that MADO Cockpit can reason about.

The registry answers five questions before routing:

1. What capability does this plugin provide?
2. Which MADO production layers consume it?
3. Is it active, merely a candidate, or disabled?
4. What permissions, cost, prerequisites, and risks travel with it?
5. What evidence and fallback path should exist when it is used?

## Boundary

M0.0 is intentionally static and deterministic. It does not discover, install, connect, execute, or grant permissions to plugins. It compiles plugin records into the existing CapabilityDescriptor contract used by MCC-M0.6.

Plugin inventory -> PluginCapabilityRegistry -> validate / normalize -> CapabilityDescriptor(kind=plugin) -> MCC-M0.6 Capability Pager -> Cockpit policy gate -> Worker binding

## Registry entry

Each entry records identity (id, plugin_ref, provider, display_name), routing (capability, layers, consumers, fallbacks), control (status, availability, cost_class, permissions, prerequisites, risk_tags), and evidence metadata.

Status values:

- active: eligible for normal compilation and routing
- candidate: tracked but excluded unless explicitly requested
- disabled: retained as history but not compiled

Layers:

- build
- research
- visual
- qa
- growth
- publish
- operations

Permissions are deliberately coarse: read, write, external_action. This is routing metadata, not an OAuth scope model.

## Compilation

Default compilation emits only active entries that are not unavailable. Candidate plugins require include_candidates=True.

Compiled descriptors preserve registry version, plugin reference, provider, layers, plugin status, permissions, consumers, fallbacks, and evidence kinds in descriptor metadata.

## Initial October 2026 fixture

Active: GitHub, Context7, Superpowers, OpenAI Developers, Google Drive, Figma, tldraw, Canva, Adobe, PostHog.

Candidate: Firecrawl, Google Calendar.

## Fail-closed rules

The registry rejects duplicate IDs, missing identity fields, empty layer sets, unknown layers, unknown status or availability values, unknown cost classes, and unknown permission values.

## Golden fixtures

The tests verify 12 normalized entries, 10 default compiled active descriptors, explicit candidate opt-in, provenance preservation, deterministic layer/status views, duplicate rejection, and enum validation.

## Next milestone

MPC-M0.1 should add a Plugin Inventory Scanner / Sync Adapter that compares observed ChatGPT plugin state with the registry. Newly observed plugins remain candidates until deliberately promoted.
