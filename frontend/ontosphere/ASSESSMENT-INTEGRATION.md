# Ontosphere integration notices

This directory contains Ontosphere 1.8.1 by Thomas Hanke, Apache-2.0.
Upstream: https://github.com/ThHanke/ontosphere
Pinned source: `6bdcb78b531b2300d047fbcdd10246fc62611cb9`.
See `LICENSE`, `ACKNOWLEDGEMENTS.md`, and `upstream.json`.
Recordings, benchmarks and upstream documentation folders were omitted.

Local modifications (2026-11-17):

- `src/integration/assessmentBridge.ts`: same-origin, parent-window-only message bridge,
  staged authoring commit, multi-graph load/export, namespace colors, example seed layout,
  canvas layout persistence and project save shortcut. No remote frame or hosted app is used.
- `src/integration/koncludeLiterals.ts`: normalize legacy `rdf:PlainLiteral` output and
  repair sign-extended UTF-8 **only** when it exactly matches a literal in asserted input.
  This prevents corrupt Chinese inferred values and false SHACL datatype violations.
- `src/components/Canvas/ReactodiaCanvas.tsx`: install bridge, connect original Save button,
  expose layout capture/restore, correct an error/warning callback type.
- `src/main.tsx`: embed defaults (local data, assessment-system light canvas, Konclude, no automatic remote
  ontology/catalog loading or relay connection). Original preferences remain configurable.
- `src/workers/rdfManager.runtime.ts`: apply the literal compatibility normalization after
  a successful Konclude run, before rendering, SHACL validation or inference publication.
- `src/webmcp/polyfill.ts`: correct the tool input type assertion.
- `tsconfig.app.json`: include ES2021 library declarations for upstream `replaceAll` calls.
- `vite.config.ts`: isolate PostCSS from the parent Vue project's Tailwind 3 configuration.
- `index.html`: base-relative favicon assets.
- `src/integration/assessment-theme.css`: assessment-system blue/white theme and readable Chinese rail.
- `src/integration/translations-zh.ts`, `chineseUi.ts`: native Reactodia Chinese translation bundle,
  embedded UI text and accessibility-label localization. RDF cards, input values, code, and queries
  are excluded from DOM text localization; identifiers and protocol names remain intact.
- `src/integration/ChineseManual.tsx`, `README.zh-CN.md`: local Chinese help, opened in-app.
- `src/components/Canvas/LeftSidebar.tsx`, `RelaySection.tsx`: wider Chinese rail, local documentation,
  Chinese relay starter prompt and relative timestamps.
- `src/components/Canvas/TopBar.tsx`, `NodePropertyEditor.tsx`, `ReasoningReportModal.tsx`:
  Chinese dynamic reasoning states, deletion confirmation and accessible report close button.

The actual Reactodia editing, TBox/ABox, search, RDF import/export, SPARQL, layouts,
clustering, fold levels, SHACL, Konclude WASM, inference reports, diagnosis and provenance
tools are upstream implementations. External AI relay/catalog services require their own
configuration; the assessment system's model save/history is provided by its local API.

Build from the parent frontend directory:

```sh
npm --prefix ontosphere ci
npm run build:ontology
```

The pinned lockfile and upstream Reactodia patch are retained. Generated app assets are
written to `../public/ontosphere/` and excluded from version control.
