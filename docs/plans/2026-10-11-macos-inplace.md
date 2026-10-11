# macOS In-place Customization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add reversible macOS install/reinstall commands to the fork and validate them against the installed Nightly.

**Architecture:** Keep shared patch/build logic in t3code-customize; put macOS packaging and transaction management in macos.py. Stage and verify builds before touching the installation; use version-bound full backups and a recovery journal.

**Tech Stack:** Python standard library, unittest, Node 24+, pnpm, git, ditto, codesign.

**Spec:** docs/plans/2026-10-11-macos-inplace-design.md

## Global constraints
- No T3 user data modifications; no automatic process termination.
- Preserve all patches and required checks. Build native JavaScript only; reuse shipped native assets.
- Refuse unknown/customized source without verified backup, older-version restore, running app, unexpected app changes and unsafe replacement paths.
- Keep Linux AppImage workflow and let the fork installer fetch this fork.

### Task 1: macOS bundle and transaction behavior
Files: macos.py, tests/test_macos.py.
1. Write fixture tests for discovery, ASAR header integrity, marked apps requiring backup, matching restore, newer update refusal, atomic failure rollback, running app and unsafe path refusal.
2. Run `python3 -m unittest discover -s tests -v`; expect failures for missing implementation.
3. Implement metadata, fingerprints, backup validation, transactional replacement and recovery helpers. Test real filesystem effects, with external signing/process checks mocked only at their boundary.
4. Run the full Python suite; expect zero failures. Commit.

### Task 2: shared builder and macOS CLI
Files: t3code-customize, macos.py, install.sh, tests/test_cli.py, tests/test_macos.py.
1. Add failing tests for macOS command routing, --app path, Node darwin/arm64 download selection and install/reinstall idempotence with staged artifacts.
2. Implement the shared archive build seam, macOS staging/signing, source checks, marker, auto-update disabling at boot, cache reuse and all lifecycle commands. Keep default Linux behavior.
3. Run full Python tests and CLI help/status. Expect zero failures and accurate unpatched status.
4. Commit implementation.

### Task 3: real build and packaging validation
Files: patches/* and checks.json only if upstream requires porting.
1. Build installed Nightly with --build-only --no-pull. Run all checks.json tests and typechecks.
2. Resolve any genuine patch conflicts without weakening tests; export the adapted patches.
3. Verify main and nested signatures, ASAR integrity and isolated-profile desktop launch. Exercise restore and reapply on a test copy first.
4. Once the actual app is closed, install cached validated build and verify status. If the app remains in use, leave staged build ready and report the exact one-command installation.

### Task 4: documentation, CI and review
Files: README.md, AGENTS.md, .github/workflows/verify.yml.
1. Document Mac commands, stock-update-reinstall workflow, local-signing limits, location of backups and recovery.
2. Add Python tests on Linux/macOS; keep upstream patch checks.
3. Run fresh Python suite, shell syntax, git diff check, staged build signature check and branch review in a fresh agent.
4. Address important review findings with regression tests. Commit and push verified changes to the user's fork.

## Review focus
Check interruption windows, recovery journal durability, stock/custom fingerprints, symlink/path traversal, reuse after Nightly update, partial signing, auto-updater behavior, Apple-only entitlements, source changes during build and commands that delete recovery data.
