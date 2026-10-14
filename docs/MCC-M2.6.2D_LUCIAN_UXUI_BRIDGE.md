# MCC-M2.6.2d Lucian UX/UI Catalog / Component Implementation Bridge

Lucian UX/UI Prompt is registered as source **44** in Design Discovery Hub. Its upstream repository contains 200 MIT-licensed interactive examples in 14 categories. The bridge imports only **locally supplied pinned metadata** and creates **data-only Codex tasks** after the existing human review and license-evidence gates.

Upstream: https://github.com/Seokwoooo/lucian-uxui-prompt
Pinned example commit: `42396145b375a17712fd738ca0e1d977556c0b73`
Live gallery: https://lucianlabs.dev/uxui-prompt/

## Workflow

1. Run `python -m mado_cockpit.design_discovery bootstrap` after upgrading. Prior 43-source registries migrate without losing reviewed references.
2. Download `api/v1/index.json`, `api/v1/en/catalog.tsv`, selected `api/v1/en/e/NNN.txt`, and `api/v1/en/tokens.css` **manually from the pinned GitHub commit**. Verify the downloaded files actually correspond to that commit; the CLI records the asserted commit and file SHA-256 but cannot prove their Git origin.
3. Run `python -m mado_cockpit.lucian_bridge intake --index index.json --catalog catalog.tsv --commit 42396145b375a17712fd738ca0e1d977556c0b73`.
4. Run `python -m mado_cockpit.lucian_bridge search --query approval` or `--category workflow-systems`.
5. Add and human-approve a **single element demo URL** in Design Discovery using `--source lucian-uxui`, then nominate the resulting reference ID with `python -m mado_cockpit.component_foundry nominate`.
6. Put the actual MIT license text and dependency/rights evidence in the nomination's `evidence/license.txt`; use `component_foundry license` to attest rights for the selected use. This human actor string is an audit assertion, **not authenticated identity**.
7. Run:

```bash
python -m mado_cockpit.lucian_bridge handoff 180 \
  --reference-id dref_<id> --selection-id component_<id> \
  --target src/components/ApprovalSignoff.tsx \
  --element-file 180.txt --tokens-file tokens.css
```

The generated `lucian-180-codex-task.json` includes the upstream revision, pinned snapshot digest, actual local element and token digests, selected target path, review/license references, and instructions to preserve MIT attribution and existing UI behavior. It does **not** contain or execute untrusted HTML/JS.

## Gates and limitations

- Metadata snapshot is immutable and SHA-256 verified on read; upgrading a catalog requires a new controlled workspace.
- The handoff is blocked without approved Discovery reference, matching Component Foundry selection, and human-attested license evidence with modification rights.
- No external HTTP requests, package installation, Codex execution, browser automation or automatic UI insertion occurs.
- Source element `hash` in the upstream TSV is a 10-character revision, **not** independently verified by this bridge against the element file. Local SHA-256 digests protect the supplied files after intake; upstream provenance must be established by manual or later automated Git blob verification.
- Existing `component_foundry` visual QA and human review remain mandatory before release. Check keyboard, touch, reduced motion, theme switching and responsive behavior.
- The original `--ux-*` token CSS and each component's MIT attribution comment must be retained or mapped with a clear license notice.

This milestone is a safe discovery-to-implementation **handoff**, not an autonomous third-party code installer.
