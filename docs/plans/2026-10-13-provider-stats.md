# Provider Stats Implementation Plan

**Goal:** Add provider identity and matching colors to the stats footer and detail panels.
**Architecture:** Reuse existing SVG glyphs and pass local provider accent classes into footer and portal panels. Keep all metrics and actions intact.
**Tech Stack:** React, Tailwind, existing Popover and Tooltip components.

1. Modify apps/web/src/components/chat/ComposerStats.tsx in the prepared cache checkout: add local provider identity helpers, footer glyph, panel headers, and local visual styling. Use contextDriver for identity; other drivers stay neutral. No new behavior or implementation-mirroring tests.
2. Inspect diff and run formatter and scoped web typecheck. Commit as a separate UI patch to preserve the existing four patches.
3. Run .\\t3code-customize.ps1 build --build-only --no-pull --resume. This runs checks.json and builds via WSL, exports patches, and leaves the app open.
4. Review patch export and clean source state. Report checks/build and application status.

## Ledger
- Approved design; existing source checkout is clean and has all four patches applied.
- Work in the existing prepared checkout as required by AGENTS.md.
