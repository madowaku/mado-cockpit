# MCC-M2.8.1 Live Sites Dogfood / Visual Portal QA

## Actual observation, 2026-10-16

The operator shared a screenshot of the ChatGPT Sites surface. It shows the **MADO / Project Atlas** heading, navigation, opening copy and hero CTAs inside a narrow embedded preview area (browser screenshot: 874 × 616, portal preview about 620 pixels wide). The screenshot provides *operator-supplied visual evidence*, not a device screenshot, a full-page capture, a verified source revision or proof that anonymous visitors can access the URL.

The operator also confirmed the ChatGPT project is owned by another account, while this account participates as collaborator. **Work mode branching is not assumed available**. The GitHub review process remains the source of truth for code changes; ChatGPT Sites is a separate, manually operated publication surface.

The site hostname seen in the screenshot is not independently verified via an unauthenticated browser. No project state is promoted to `published_verified` on this basis.

## Added read-only live QA

`python -m mado_cockpit.sites_live_qa` runs Chromium using a **fresh, cookie-free context** for desktop 1440×900, tablet 820×1180 and mobile 390×844. It produces full-page screenshots, per-file SHA-256 receipts, DOM observations and an honest fail-closed release gate.

Install browser automation in an isolated environment:

```sh
pip install playwright
python -m playwright install chromium
python -m mado_cockpit.sites_live_qa \
  --url "https://YOUR-REVIEWED-HOST.chatgpt.site/" \
  --output .mado/sites-live-qa/manual-run-001
```

Only operator-supplied `https://*.chatgpt.site/` roots are accepted. This program does **not** authenticate, enumerate Sites, call ChatGPT APIs, deploy, write to GitHub, modify permissions, or read cookies.

### Release gate

| Dimension | What counts | This milestone |
| --- | --- | --- |
| Screenshot observation | User sees the header and hero | observed in user-provided image |
| Browser UI | Three actual screenshots, DOM checks, no JS exceptions or horizontal overflow | pending live run |
| Interactions | Search and filtering, link navigation, focus and mobile gestures | pending human/browser test |
| Public reachability | Fresh browser independent of login | unverified |
| Site audience | Owner-reviewed Sites sharing settings | unverified |
| Source parity | Review deployment content against repository SHA | unverified |
| Release approval | Human lease and separate publication decision | **blocked** |

`evaluate_checks` and `decision_gate` are covered by unit tests. UI success explicitly does **not** grant release approval. Failures create `report.json` with the viewport errors.

## Hands-on walkthrough

1. In the owner account, open the Site and verify who can see it. Do not change audience without explicit review.
2. In this account, open the Site at a desktop browser width. Check titles, card grid, search and category filtering. Scroll to the publication protocol and footer.
3. Test on a phone-width browser. Look for clipped text, horizontal scrolling and touch-target issues.
4. Run the read-only Chromium script above in an environment where the Site is reachable. If the Site requires login or blocks automated access, record **blocked/unverified**, not a passing test.
5. Compare screenshots and page behavior to `integrations/sites/portal/` from the MCC-M2.8 branch. A matching title alone is not sufficient for source parity.
6. Collect a human sign-off separately before considering promotion in the public projects catalog.

## Follow-up

MCC-M2.8.2 could add a reviewed GitHub-hosted screenshot gallery and human QA evidence intake. It must never publish private screenshots or automatically infer that a Site is public because one collaborator can view it.
