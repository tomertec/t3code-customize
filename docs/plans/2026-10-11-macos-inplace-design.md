# macOS customization design

Approved scope: fork t3code-customize and provide a plugin-like, reversible patch to the existing T3 Code Nightly.app. Retain Linux behavior. Reapply with one command after updates.

Build the patched JavaScript at the exact installed upstream commit. Assemble a staged copy of the installed .app, refresh ElectronAsarIntegrity, disable the staged app's auto-updater, remove certificate-only entitlements from the main executable, and ad-hoc sign the outer bundle while preserving shipped nested binaries. Verify archive contents and codesign before replacing anything.

Store a verified full stock backup per source version and app location. Record a marker in the customized Info.plist and a manifest with stock and customized fingerprints. Replace the app via sibling staging and rollback renames only after confirming no process is running from that bundle and the installed source has not changed during the build. Interrupted replacements retain a recovery journal and stock backup. Never restore an older backup over a newer app; reject unknown modifications or missing/corrupt backups.

Commands: install/reinstall/build (apply by default), --build-only (stage without touching the installed app), status, off/restore (restore stock for updating), on (reapply cached compatible build), uninstall (restore matching stock and remove tooling). Linux retains its launcher and commands. Preserve app identity, app location, T3 data and public Connect config. Local signing can affect Keychain/passkeys; do not claim official signing or seamless native updates.

Verification: Python fixture tests for discovery, ASAR metadata, integrity hash, version-aware restoration, transaction rollback, source changes, running-process refusal and symlinks. Real macOS codesign and launch smoke test on an isolated profile, then build checks from checks.json. Document first build time, update workflow and signing limitations.
