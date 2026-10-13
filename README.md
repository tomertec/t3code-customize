# t3code-customize

Your 5 hour and weekly usage, context and tokens per second, right under the T3 Code composer.

Unofficial. Not affiliated with T3 Tools. For T3 Code Nightly on Windows, macOS and Linux (AppImage).

This fork adds macOS support to [btsouth/t3code-customize](https://github.com/btsouth/t3code-customize). macOS modifies the existing app with a full stock backup; Linux uses a separate customized launcher.

## What you get

- **Usage meters** for your 5 hour and weekly limits, from the limits T3 already gets from your providers.
- **Context** used in the thread. Hover it for the window size, the auto-compaction threshold and a Compact now button.
- **Tokens per second** for the last response, with turn time and token details on hover. Claude rates are measured from the stream; Codex rates are labeled approximate.
- **Cache rate** for the last turn.

The patches retain T3 Connect public configuration. The macOS signing and update differences are described below.

## Install on Windows

For a checked GitHub Actions build, download the **t3code-windows-bundles** artifact, extract it to get `customized-bundles.zip`, then quit T3 Code and run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 install --bundles "C:\Downloads\customized-bundles.zip" --no-pull
```

This route needs Git for Windows and Python, and does not require WSL. The bundle must match your exact Nightly and the installer recipe. The installer verifies file hashes, feature markers, retained native files and public Connect config before applying it. The **Build Windows customization bundles** workflow builds at the provided installed commit/version and runs every check in `checks.json` before emitting the artifact. Only public Connect configuration belongs in its JSON input.

### Build locally

Extract the Windows package, open PowerShell in its directory, quit T3 Code fully, then run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 install --no-pull
```

Open your existing T3 Code shortcut and enable **Settings > General > Stats for nerds**. Building requires Git for Windows, Python 3.9+, and WSL with a Linux distro containing Git and Python 3 (Ubuntu works). The JavaScript build runs on the Linux filesystem because the native Windows Vite toolchain crashes on the tested machine. It downloads a private Linux Node 24 runtime if needed. Applying a cached build needs only Windows Python; it does not change global Node or T3's shipped runtime. The initial source build can take 5–15 minutes; allow at least 6 GB plus archive backups and prepared builds. The execution-policy setting above applies only to that PowerShell process.

To build while T3 Code is open:

```powershell
.\t3code-customize.ps1 install --build-only --no-pull
# After the build finishes, quit T3 Code fully, then:
.\t3code-customize.ps1 install --no-pull
```

The installer detects `%LOCALAPPDATA%\Programs\t3code`. For another location, provide `--app "C:\path\to\t3code"` once. It rebuilds for the installed app's exact source commit, supports separate desktop/server archives, preserves the executable and native helpers, and verifies backups and rebuilt archives. It never modifies T3 user data or closes running processes.

It uses your default WSL distro. Select another with `--wsl-distro Ubuntu-24.04` on build/install/reinstall. The Linux build checkout is `~/.cache/t3code-customize/windows-build/source`; only compiled JavaScript is copied back to Windows. Required patch tests and typechecks run in that checkout, or reuse a successful Windows check result for the identical source commit, check specification and lockfile. WSL Node subprocesses have a 3 GB heap budget. If the local toolchain crashes, use the Actions bundle route above.

This version customizes the **native Windows backend**. WSL sessions use T3's separate compiled Linux runtime, which is retained as shipped; the added metrics are not supported for those sessions.

The Windows preload disables V8's Maglev compiler in the desktop main process and native backend to avoid a reproduced startup crash with customized bundles. Other JIT compilation remains enabled. Restoring stock removes this workaround.

### Windows commands and updates

```powershell
.\t3code-customize.ps1 status
.\t3code-customize.ps1 off       # restore stock before updating
.\t3code-customize.ps1 reinstall # rebuild after an official Nightly update
.\t3code-customize.ps1 on        # reapply a compatible build
.\t3code-customize.ps1 uninstall # restore stock, remove this app's backups/builds
```

Quit T3 Code before applying or restoring archives. Restore stock with `off`, open T3 Code and update normally, then quit it and run `reinstall`. Automatic updates are disabled in the customized build. Some new Nightlies require porting the patches first; failed builds leave the installed app unchanged. `--skip-checks` is refused on Windows.

Backups and prepared builds live under `%LOCALAPPDATA%\t3code-customize\windows\<app-path-id>`. An interrupted replacement keeps a recovery journal; quit the app and rerun `install` or `off`. Unknown changes, corrupt backups, and version mismatches stop recovery rather than overwrite your app. Do not delete recovery files while customized. The tool refuses executables that enforce embedded ASAR integrity; it never changes the executable or its Authenticode signature. Modified archives contain unofficial code.

Uninstall retains source, tools, logs and installer scripts, including the WSL build cache. Keep the extracted package for future commands. The download/bootstrap form of `install.ps1` requires Windows support to be published to this repository; local packages work before publication.

## Install on macOS

Quit T3 Code fully, then run:

```sh
bash -c "$(curl -fsSL https://raw.githubusercontent.com/tomertec/t3code-customize/main/install.sh)"
```

Open your existing **T3 Code (Nightly)** app normally and enable **Settings > General > Stats for nerds**. No separate app or launcher is needed.

Requires git, Python 3.9+, and the macOS `codesign`, `ditto`, and `xattr` tools. Supports Apple Silicon and Intel Node downloads; the installed app supplies the native Electron runtime. The first build downloads source and dependencies and may take 5–15 minutes. Allow at least 6 GB plus space for full app backups and staged builds.

Alternatively, clone this fork and run `./t3code-customize install`. If the app is not in `/Applications` or `~/Applications`, provide its path once:

```sh
./t3code-customize install --app "/path/to/T3 Code (Nightly).app"
```

To build while T3 Code is open, use `./t3code-customize install --build-only`. Once it completes, quit the app and run `t3code-customize install` to apply the cached build. If `~/.local/bin` is not on your PATH, use `~/.local/bin/t3code-customize` or the script in your clone. Do not run the whole installer with sudo. The installed app and its parent directory must be writable.

### Updating Nightly on macOS

1. Quit T3 Code and run `t3code-customize off` to restore the official app and signature.
2. Open T3 Code and update Nightly normally.
3. Quit it again and run `t3code-customize reinstall`.
4. Open the same app and continue working.

The tool reads the new app's exact commit and rebuilds for it. Repeated installation of an unchanged build is a no-op. A newer Nightly is never overwritten with an older stock backup. Some upstream changes require porting the patches before reinstallation can succeed.

### macOS commands

```text
t3code-customize install       build and patch the installed app (also the default)
t3code-customize reinstall     reapply after a Nightly update
t3code-customize status        show version, patch status, backup and prepared build
t3code-customize off           restore the matching official app before updating
t3code-customize on            reapply the compatible cached build, or rebuild
t3code-customize uninstall     restore stock, remove this app's backups and builds
```

`restore` is an alias for `off`. `--force` rebuilds instead of using the cache. `--skip-checks` is refused on macOS. Uninstall retains the downloaded source, logs and build tools; it removes the CLI link when no other app has recorded builds. It never deletes T3 user data.

### macOS signing and recovery

This is a reversible app patch, not an official T3 plugin. Before changing your installation, the tool makes a verified full stock backup and stages the rebuilt JavaScript in a copy. It refreshes Electron ASAR integrity and ad-hoc signs the outer app. Nested shipped binaries retain their original signatures. The main executable must be re-signed, so it is no longer signed or notarized by T3 Tools.

Certificate-only entitlements (including shared Keychain groups and associated domains) are removed from the local signature. Keychain may request access again; passkey features that depend on T3 Tools' entitlements are not guaranteed. Restore stock to use the official signature. Automatic updates are disabled in the customized build; use the update workflow above.

Build failures leave the installed app alone. Replacement requires the app to be closed and checks that it has not changed during the build. A rename failure rolls back immediately. If the process is interrupted during replacement, rerunning `install` or `off` recovers from the transaction journal. Specify the same `--app` path if needed. Do not delete the backup/recovery directories while the app is customized. If the tool reports an unknown modification or corrupt backup, it stops and keeps recovery files rather than overwriting the app.

Backups and build manifests live under `~/.local/share/t3code-customize/macos/<app-path-id>/` (or `$XDG_DATA_HOME/t3code-customize/macos/`). Logs and source use `~/.cache/t3code-customize`.

## Install on Linux

```sh
bash -c "$(curl -fsSL https://raw.githubusercontent.com/tomertec/t3code-customize/main/install.sh)"
```

Or clone it anywhere and run `./t3code-customize`.

The first run downloads T3 Code's source and build tools, so give it 5 to 15 minutes. Then quit T3 Code fully, open **T3 Code (Customized)** from your app launcher and turn on **Settings > General > Stats for nerds**.

You need git and Python 3. If your Node is older than 24, it fetches its own copy. It uses about 6 GB of disk. If your AppImage isn't in `~/Applications` or `~/Downloads`, run it once with `--appimage /path/to/T3-Code.AppImage`.

## After every T3 Code update on Linux

```sh
t3code-customize
```

That's it. It pulls the latest patches, rebuilds for your new version and tells you when to reopen. Until you run it, the launcher opens stock T3 Code and tells you why.

## When a nightly breaks the patches

Upstream moves fast, and sometimes a nightly changes the code the patches touch. When that happens:

- If you have Claude Code or Codex installed, it offers to port the patches for you right there.
- Otherwise, wait a bit: this repo usually catches up within a day. Then run `t3code-customize` again.
- Or point any coding agent at this repo and ask it to follow [AGENTS.md](AGENTS.md).

A failed build leaves your installed app untouched.

## How it works on Linux

T3 Code is open source (MIT). This repo holds three patches and one script. The script:

1. reads your installed AppImage: its exact upstream commit and the public config T3 Connect needs,
2. applies the patches to that commit and runs their tests,
3. rebuilds the web, server and desktop JavaScript,
4. lays it over a copy of your app, keeping every native part as shipped, and checks the result byte for byte.

Everything runs on your machine. Your AppImage and your T3 data are never modified.

## Linux commands

```
t3code-customize             update the patches and build for your installed T3 Code
t3code-customize status      show what the next launch opens
t3code-customize off | on    switch between stock and the customized build
t3code-customize uninstall   remove it, its launcher, builds and caches
```

## Good to know

- **Bugs:** before reporting anything to T3 Code, run `t3code-customize off`, reopen and check it happens on stock too. Report customization problems here.
- **Windows and macOS:** supported by this fork; see their update and recovery workflows above.
- **Files:** builds live in `~/.local/share/t3code-customize`, the source checkout and logs in `~/.cache/t3code-customize`.

## License

MIT, same as T3 Code.

## Development checks

```sh
python3 -m unittest discover -s tests -v
./t3code-customize verify
```

The Python suite uses temporary app bundles to test backup/restore, interrupted replacement, version changes, idempotent install and command handling. On Windows run `python -m unittest discover -s tests -p test_windows.py -v`; macOS bundle durability tests require a Unix filesystem. `verify` applies the patches to `patches/base.txt` and runs every test and typecheck in `checks.json`. CI runs the shared suite on macOS and Linux, Windows lifecycle tests on Windows, and patch checks on Linux.

### Pi local-model token speed

Install the Pi extension in the same Pi environment used by T3:

    pi install npm:pi-token-speed

Restart Pi sessions after installing, then enable **Settings > General > Stats for nerds**.
The customization forwards the extension's tokenSpeed footer into the main-agent stats line, including when Pi uses a local model. The rate carries an approximation mark: live values may count streaming chunks, and final values depend on extension settings and provider usage availability. T3 does not substitute whole-turn wall time or invent token counts when usage is absent. Claude and Codex retain their existing measurements. Pi sessions using the separately shipped WSL backend are outside this Windows customization.
