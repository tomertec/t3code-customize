# Nightly Context Meter Implementation Plan

**Goal:** Port every patch to the installed October 15 Nightly and improve the bottom context meter.

**Architecture:** Keep the existing provider telemetry and compact action. Share a smooth meter between footer and popover, deriving the marker from the effective threshold and known window size.

**Tech Stack:** React, TypeScript, Tailwind, Vite Plus, Python installer, WSL.

1. Resolve the CodexAdapterV2.test.ts insertion conflict by retaining both upstream session approvals and customization throughput tests; continue all six commits. Done; 789 tests pass on the initial port.
2. Add meaningful threshold-position cases to ComposerStats.logic.test.ts; run the focused suite and observe the new cases fail. Implement the finite, in-window threshold calculation in ComposerStats.logic.ts.
3. Update ComposerStats.tsx with a continuous rounded track, subtle quarter ticks, threshold marker, provider/warning tones, tabular percentage, and reduced-motion transitions. Keep existing segmented helper tests and all unrelated telemetry behavior.
4. Fold the UI changes into the last patch commit with fixup/autosquash. Run all checks in checks.json using the installer resume workflow. Inspect the actual component in dark/light and narrow previews.
5. Export patches for the new upstream base, prepare verified Windows archives with build --resume --build-only --no-pull, and leave the cached source clean. Report exact verification and installation status. If the local toolchain crashes, use the checked portable build route.
