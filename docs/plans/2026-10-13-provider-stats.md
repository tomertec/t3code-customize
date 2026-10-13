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
- Implementation also passes selectedProvider from apps/web/src/components/ChatView.tsx, so new threads and provider changes show the correct account icon. Context/turn metrics retain their session identity.
- Review found and verified the provider-source correction. Scoped web typecheck and formatter passed.
- Standard WSL build passed 765 tests and nine typechecks, then Node 24.21.0 crashed during web transformation. Maglev-disabled and optimization-disabled probes did not build successfully. A JIT-less probe was incompatible with the bundler's WebAssembly use.
- Retrying the corrected patch and diagnosing with a checksum-verified private Node 24.13.1; required checks remain enabled.
- Final corrected source 56d5eb013 passed all 17 test files (765 tests) and all nine checks.json typechecks. The second standard build also failed at vp build with exit 139. Node 24.13.1 and a probe disabling Maglev, optimizing JIT, and Sparkplug did not produce a usable web build.
- Final review is clean; reverse-apply validation confirms the saved fifth patch matches the source commit. Source checkout is clean with no rebase. No upstream changes were needed. Existing patches and checks are preserved.
- Packaging remains blocked by the local V8/bundler crash. No new package was installed; the documented GitHub Actions checked-bundle fallback requires publishing this patch to the repository before it can build it.
