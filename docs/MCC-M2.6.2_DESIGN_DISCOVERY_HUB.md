# MCC-M2.6.2 Design Discovery Hub / Agent-Native UI Resource Pipeline

This milestone creates a metadata-only, locally review-gated design reference registry for the existing MADO Cockpit Python control plane. It does **not** import external CSS, React code, screenshots, fonts, icons, videos, or design archives. It also does not claim that MCC-M2.6 Living UI Spec is already implemented in this repository.

## Initial source registry

Ten curated reference sources are built into `mado_cockpit.design_discovery.CATALOG`:

| ID | Official source | Scope |
|---|---|---|
| designeer | https://designeer.xyz/ | Design resource discovery |
| prompt-motion | https://prompt-motion.com/ | Motion reference |
| shotreel | https://shotreel.app/ | Showcase rendering |
| evilbuttons | https://evilbuttons.com/ | Animated buttons |
| drawably | https://drawably.dev/ | Illustrated UI components |
| alcove | https://tryalcove.com/ | Mac UX inspiration |
| appllama | https://appllama.io/ | iOS screen and flow reference |
| designbookmark | https://designbookmark.com/ | Design discovery |
| amicons | https://amicons.design/ | Icons |
| graphical | https://graphicalui.com/ | Agent-ready design systems |

All entries initially declare `mode=manual_link_only` and `rights=unverified`. Listing a source implies no license grant, API compatibility, official relationship, or endorsement.

## Startup

An existing initialized Cockpit can use this module directly. For a new repository:

```sh
mado-cockpit init --project-id design --name "Design Research" --root .
python -m mado_cockpit.design_discovery --root . bootstrap
python -m mado_cockpit.design_discovery --root . sources --query motion
python -m mado_cockpit.design_discovery --root . pack --query ios --output design-context.json
```

The generated `design-context.json` has two distinct sections: matching discovery sources, and **only human-reviewed** references. The output is advisory context to a Codex worker, not a command or an automatic runtime capability.

## Reference intake and review

Add a human-selected page URL:

```sh
python -m mado_cockpit.design_discovery --root . add \
  --source evilbuttons \
  --title "Button inspiration" \
  --url https://evilbuttons.com/ \
  --note "Explore animation patterns for Cockpit; reference only" \
  --rights reference_only
```

This creates a SHA-256-bound `dref_...` entry in `pending` state. Nothing is promoted automatically.

Review an exact entry (using the ID returned by the previous command):

```sh
python -m mado_cockpit.design_discovery --root . review dref_<digest> \
  --decision approve \
  --actor human:owner \
  --note "I inspected the reference and approved research-only usage"
```

```sh
python -m mado_cockpit.design_discovery --root . pack \
  --query button --output design-context.json
```

Review actions require an explicit human-prefixed actor string and a meaningful note. This is an **audit assertion**, not authenticated human identity: production UIs must bind it to the existing Human Control Lease and authenticated user context before allowing autonomous callers to invoke review.

## Rights and integration boundary

* External URLs must use HTTPS and match the selected source host (or one of its subdomains). Login credentials, custom ports, cross-domain URLs, local paths, and insecure URLs are rejected.
* Candidate content is hashed. Changed text generates a new candidate ID; mutation of stored content is detected before a context pack is issued.
* `licensed_asset` is only a **claim** and requires an evidence URL. Approval still means `approved_reference`, **not** authority to copy or bundle assets. The MAF license evidence gate must separately decide ingestion.
* Prompts, labels and notes from remote sites are treated as untrusted data; never execute them as instructions or tool actions.
* No HTTP client, site spider, content scraper, browser automation or paid-service API calls are implemented here.
* Appllama explicitly restricts automated scraping and bulk extraction. If authorized in a later phase, prefer its licensed, official MCP and consume results for a specific research task, without bulk harvesting or storing expiring media.
* Graphical's `GUI.md` must be supplied by an authorized user or export, not scraped and redistributed by this module.

## Storage and governance

```text
.mado/cockpit/design_discovery/
├── registry.json
└── reviews.jsonl
```

The Cockpit Event Spine receives `design.discovery.initialized`, `design.reference.created`, and `design.reference.reviewed`. Reviews bind to an immutable candidate digest. Rejected and pending candidates never enter an agent context pack.

MCC-M2.6.2 intentionally stops before component installation, screenshot comparison, and showcase-video rendering. Future milestones can consume the approved reference JSON to drive Living UI Spec, Codex implementation tasks, Browser Visual QA, and Shotreel showcase exports, with separate tool and policy gates.

## Acceptance

```sh
pytest -q tests/test_design_discovery.py
pytest -q
```

Acceptance covers 10-source catalog, no automatic download, allowlisted domain checks, immutable reference identity, explicit human review, pending/rejected exclusion, digest tamper detection, rights-evidence requirement, Cockpit event logging and CLI context-pack export.
