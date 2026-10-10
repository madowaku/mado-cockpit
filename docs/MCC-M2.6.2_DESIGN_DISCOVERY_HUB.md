# MCC-M2.6.2 Design Discovery Hub / Agent-Native UI Resource Pipeline

This milestone creates a metadata-only, locally review-gated design reference registry for the existing MADO Cockpit Python control plane. It does **not** import external CSS, React code, screenshots, fonts, icons, videos, or design archives. It also does not claim that MCC-M2.6 Living UI Spec is already implemented in this repository.

## Initial source registry

Thirty-six curated reference sources are built into `mado_cockpit.design_discovery.CATALOG`:

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
| affectui | https://affectui.com/ | UI components (live availability not verified) |
| inspora | https://inspora.design/ | Curated visual design inspiration |
| 21st-dev | https://21st.dev/ | React components and agent-ready prompts |
| bestfreefonts | https://bestfreefonts.com/ | Free-font discovery; individual licenses vary |
| spline | https://spline.design/ | Interactive 3D design |
| unicorn-studio | https://unicorn.studio/ | Shaders and interactive web effects |
| paper | https://paper.design/ | Agent-connected canvas and MCP workflows |
| theatrejs | https://theatrejs.com/ | Web animation sequencing |
| annnimate | https://annnimate.com/animations | GSAP animation components for React/Vue; mostly paid |
| uselayouts | https://uselayouts.com/ | React layouts and interaction components |
| arc-ui | https://uiarc.dev/ | React/shadcn components and blocks; free MIT and separate Pro licensing |
| kobra-systems | https://kobra.systems/ | AI agent UI, forms, content, and feedback components |
| bencho | https://bencho.dev/ | Interactive React components and microinteractions |
| hyperiux-vault | https://vault.hyperiux.com/ | React/Next.js interaction effects; free and Pro tiers |
| libraries-dev | https://libraries.dev/ | Agent-ready React visual effects libraries; free MIT npm packages and paid Studio |
| beui | https://beui.dev/ | Animated React/Next.js components; free MIT and Pro options |
| beautifului | https://beautifului.dev/ | AI-native component primitives and agent interfaces |
| ui-maxxing | https://uimaxx.ing/ | User-supplied resource; site availability/content unverified |
| remotion | https://remotion.dev/ | React-based video composition/rendering; source-available, custom license |
| motion-dev | https://motion.dev/ | React and JavaScript UI animations, transitions and gestures |
| lottiefiles | https://lottiefiles.com/ | Animated Lottie/dotLottie assets; asset-specific terms |
| rive | https://rive.app/ | State-machine driven interactive vector animations; exports may require paid tier |
| gsap | https://gsap.com/ | JavaScript animation engine, timelines and scroll effects; GSAP Standard License |
| threejs | https://threejs.org/ | WebGL 3D animation and rendering; MIT library |
| lucide | https://lucide.dev/ | SVG icon system; ISC icon license |
| reactbits | https://reactbits.dev/ | Animated React components; MIT library |

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

## Catalog expansion (MCC-M2.6.2a, 10 → 18)

Existing registries created with the **exact prior ten-source catalog fingerprint** are upgraded by rerunning:

```sh
python -m mado_cockpit.design_discovery --root . bootstrap
```

The upgrade verifies each frozen reference digest and bound review receipt before making any change; it replaces only `source_catalog_sha256`, retaining candidate IDs, review decisions, audit log and approvals. It appends a single `design.discovery.catalog_upgraded` event to the Event Spine. Repeating bootstrap is idempotent.

An unknown or modified catalog fingerprint, invalid schema, or tampered reference **fails closed**. `pack`, `add` and `references` continue to require a current catalog. Nothing is fetched from external sites during migration.

Sources are research links, not a blanket right to reuse code, fonts, videos, shaders, or assets. In particular:

* 21st.dev includes community-authored resources with potentially different component licenses. Inspect each before use.
* Best Free Fonts is a discovery catalog; verify the license of each individual font before redistribution or bundling.
* Spline and Unicorn Studio offer free and paid usage tiers, with publishing and commercial-use restrictions. No automatic exports are enabled.
* Paper has a free tier and official MCP/Codex workflows, but this module does not connect external accounts or enable editing.
* Affect UI's live availability was not verified when this entry was added. It remains a metadata-only bookmark.

## Component library expansion (MCC-M2.6.2b, 18 → 28)

Rerun `python -m mado_cockpit.design_discovery --root . bootstrap` after updating the repository. Both known 10-source and 18-source catalog fingerprints migrate directly to the new 28-source catalog without clearing the existing registry or review audit.

Only known historical fingerprints can migrate. The upgrade checks the SHA-256 of every existing reference and confirms that each source belonged to its historical catalog. Pending, rejected, and approved references stay intact. Unknown fingerprints, tampering, and impossible historical source IDs fail closed. The operation is idempotent and emits one upgrade event.

This is a **bookmark/reference registry, not a component installer**. Do not execute installation commands embedded in component metadata. Before importing any asset or source code, independently verify: the selected component's license, dependency versions, provenance, React compatibility, keyboard/touch accessibility, reduced-motion behavior, and performance in browser QA. Arc UI free and Pro portions, beUI free and Pro portions, Annnimate paid products, and Hyperiux Vault paid effects must not be treated as having identical rights.

Live verification found nine working sites or pages; `uimaxx.ing` was inaccessible in the current research environment, so its bookmark is preserved with an unverified description rather than asserting that its component downloads work. `libraries.dev` is an agent-ready React effects product (MIT-licensed free libraries), not a general-purpose package registry.

## Motion graphics expansion (MCC-M2.6.2c, 28 → 36)

This increment adds the eight user-supplied sources above without installing packages, importing content, downloading Lottie animations, fetching icons, creating new subscriptions, or executing third-party code. The catalog is a metadata-only **research index**. References require explicit human review for inclusion in Codex context packs.

### Upgrade existing registries

Existing 10-source, 18-source and 28-source registries can migrate directly to 36 sources by rerunning:

```sh
python -m mado_cockpit.design_discovery --root . bootstrap
python -m mado_cockpit.design_discovery --root . sources --query video
python -m mado_cockpit.design_discovery --root . sources --query animation
python -m mado_cockpit.design_discovery --root . sources --query 3d
```

The upgrade recognizes only exact historical catalog fingerprints. It validates every stored reference digest, review binding and the source's membership in its historical catalog before committing the new fingerprint. It preserves reference IDs and review audit logs and emits one `design.discovery.catalog_upgraded` event. Unknown fingerprints, impossible historical records and altered reference data are rejected without migration. Re-running `bootstrap` is idempotent.

### Choosing a tool, with rights awareness

* **Remotion** is source-available and is *not* OSI-open-source. Its Free License is available for individuals and teams of up to three, subject to specific terms; a Company License may be required for larger or automation-product use. Official agent skills are available, but are not installed here.
* **Motion** is useful for app UI motion. Inspect production dependencies and their licenses before shipping.
* **LottieFiles** offers free assets under a Lottie Simple License and other paid offerings; the asset and creator rights must be checked before download, caching, modification, redistribution, or embedding.
* **Rive** free plans support learning/design, while export and deployment rights can require paid plans. Rive runtime libraries and the editor's commercial/asset rights are separate concerns.
* **GSAP** tools, including formerly premium plugins, are offered without charge under its Standard License. “Free” does not imply OSI-approved open source or unlimited redistribution of the library.
* **Three.js** is MIT licensed, and **Lucide** SVG icons are ISC licensed, subject to attribution/notice obligations.
* **React Bits** distributes its component library under the MIT License; nevertheless, inspect exact dependencies and any individual asset licenses.

For a later production bridge, classify candidates into `video`, `motion`, `motion-assets`, `interactive-motion`, `3d`, `icons` and `components`. The separate MAF license-evidence and Cockpit execution policy gates must approve actual installation and rendering. Browser QA must cover reduced-motion preferences, frame performance, keyboard accessibility, font/embed licensing and deterministic render evidence. Publishing a video requires additional review of its input assets and codec conditions.

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

Acceptance covers 36-source catalog and migration from exact legacy 10-, 18-, or 28-source fingerprints, no automatic download, allowlisted domain checks, immutable reference identity, explicit human review, pending/rejected exclusion, digest tamper detection, rights-evidence requirement, Cockpit event logging and CLI context-pack export.
