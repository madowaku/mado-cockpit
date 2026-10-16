# MCC-M2.8 ChatGPT Sites Deployment Lab / Multi-App Publishing Gate

## Goal

Present the MADO collection as a **visual read-only directory**, with an honest distinction between a public GitHub repository and a verified deployed Site. This milestone adds an attractive and portable static portal without introducing credentials, external APIs, databases, authentication, or automated production deployment.

The authoritative source is `madowaku/mado-cockpit`, not `madowaku-cockpit` (a different local-first handoff project). The portal is additive and leaves existing MADO Cockpit Python UI, HTTP/MCP endpoints, evidence and human-approval gates untouched.

## What is implemented

- Twelve public GitHub repositories checked on 2026-10-16, with category search, keyboard search (`/`), responsive cards, and source links.
- Release state per entry: `source_only`, `preview_pending`, or `published_verified`. Never fabricate preview links, Sites IDs, deployments or successful QA.
- Explicit allowlist of reviewed public repository slugs, including a safety test that rejects `neon-brainstorm` and `search-forest` (private on 2026-10-16).
- A deterministic Python build that copies four reviewed static assets and emits a SHA-256 build receipt with `deployment_verified=false`.
- Gate tests for schema, duplicate IDs, release evidence, unsafe links, sensitive fields, and build integrity.
- CI builds a *review-only artifact* and uploads it for manual inspection. **CI never deploys**.

## Local build and review

```sh
pip install -e ".[dev]"
pytest -q tests/test_sites_portal.py
python -m mado_cockpit.sites_portal --output build/sites-portal
python -m http.server 8765 --directory build/sites-portal
```

Then browse `http://localhost:8765/`. Do not open `index.html` directly using `file://`, because the browser must fetch `catalog.json` from the same origin. Check desktop, narrow mobile, dark mode, keyboard search and external links. The default deployment artifact is `build/sites-portal/`; no dependency install is needed after building.

## Sites deployment workflow (manual release gate)

Sources: [Create a site](https://learn.chatgpt.com/docs/sites/creating-a-site), [Publish and share](https://learn.chatgpt.com/docs/sites/publishing-and-sharing), [Sites overview](https://learn.chatgpt.com/docs/sites).

1. In ChatGPT web or desktop, open **Sites** (`chatgpt.com/sites` or `@Sites`). Ask it to create a website from the four static files in the generated `build/sites-portal/` artifact or a compatible local project. **Ask Sites to check artifact compatibility before any publish attempt.** The GitHub integration alone does not register or deploy a Sites project.
2. Save a **version only, without deploying**. Inspect layout at desktop and mobile widths, test search, category filters, source links, empty state, and errors. Check the Site sharing audience. Confirm no private repository names or unpublished operational records leaked.
3. For production release, request a separate human approval and review the compiled output. A Site deployment URL is production, not a staging URL. Choose the narrowest audience, deploy explicitly, then test the real URL as an intended viewer (including a signed-out viewer if public).
4. Register the real public URL in the catalog **only after deployment and post-deploy verification**. Set `publication.state=published_verified`, `url`, `evidence_url` (a reviewed public GitHub evidence issue/PR), `audience=public`, and `verified_on` (YYYY-MM-DD). Have a reviewer verify the evidence is genuine, not just syntactically valid. Rebuild and review.
5. Continue one Site at a time. D1/R2, GitHub APIs, personal data and sign-in remain out of scope until a real use case requires them and access is server-side enforced.

### Multi-app publication contract

Each catalog entry has a stable `id` and a source GitHub repository. `source_only` means the source is indexed, not that the app runs. `preview_pending` means a version or deployment candidate may be undergoing review; it has **no public Site URL**. `published_verified` requires an explicit HTTPS public URL, a public GitHub evidence link, verification date and public audience designation. The build gate is necessary but *not sufficient* to prove either public accessibility or human review.

The portal itself starts with all entries `source_only`, which is intentional. A central index may be valuable before any independent app gets a verified hosted version.

## Known limits / next gate

- Sites publication cannot be initiated by this GitHub-only integration. No Sites project ID, version, deployment or runtime verification has been created by this milestone.
- Public/private allowlist is a dated human-reviewed snapshot; new repositories require a fresh visibility check and a code review.
- The receipt hashes static input/output bytes, not the platform's hosted version. Only a real Site review and post-deploy URL inspection can close the release gate.
- Automated browser screenshots and accessibility audits, signed reviewer identity, cross-app GitHub sync and continuous freshness checks are separate follow-ups.

**Decision gate:** keep release in `review_only` until real Sites compatibility, saved-version review, audience selection and production URL verification are complete. No automatic green light.
