# Windows customization design

Approved scope: a PowerShell entry point that builds the same stats customization for the exact installed T3 Code Nightly, with verified backups, restore and reinstall commands.

Use the shared Python builder with Windows tool discovery, locking and Node downloads. Add a Windows packaging module that discovers the per-user installation or accepts --app. Preserve the executable, native dependencies and user data. Support split app.asar/server.asar packaging and older combined archives. Refuse an executable with enabled embedded ASAR integrity rather than modifying its signature.

Stage rebuilt JavaScript and disable automatic updates in boot.cjs. Validate every replaced entry, retained stock entry, feature marker and public Connect setting. Record source fingerprints and verified original archives under LOCALAPPDATA. Apply only when the app is closed and its executable and archives still match the source snapshot. Journal multi-archive replacement and recover interrupted operations. Never restore backups over a different Nightly or discard an unknown modification.

Commands: install/reinstall/build, --build-only, status, off/restore, on and uninstall. Provide install.ps1 and t3code-customize.ps1. First build requires Git, Python 3.9+ and downloads Node 24 if necessary. Restore stock before official updates, then reinstall. Do not terminate the running app.

Validation: Windows fixture tests for split packaging, archive preservation, compatible cached builds, process refusal, corrupt backup, newer version, partial replacement recovery and command handling. Run shared tests and checks.json, build against the installed Nightly and verify staged archive contents. Applying to the running host is deferred until it is closed.

Implementation refinement: the native Windows Vite build crashed across several private Node versions. Use the installed WSL distro for checked JavaScript builds on its Linux filesystem, then package and verify on Windows. WSL is required only for rebuilding, not applying a cached build. This targets the native Windows backend; the separately compiled Linux runtime used by WSL sessions remains shipped by T3 and its added metrics are outside this version's scope.

Local WSL also suffered memory pressure and a Vite segmentation fault. Provide an on-demand GitHub Actions build and a --bundles installer input. Portable bundles bind exact upstream commit, installed version and normalized patch/build recipe; include passed-check metadata and SHA-256 for each output. Validate ZIP paths, all hashes and complete manifests before extraction, then apply the same stock/native/config overlay verification. Publishing the branch and starting Actions remains a separate approval boundary.
