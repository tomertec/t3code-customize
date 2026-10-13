"""Windows archive packaging and reversible, version-bound installation.

The shipped executable and native helpers are never rewritten. The transaction
journal retains both possible archive hashes so recovery rejects unknown files.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time
import zipfile


class Error(RuntimeError):
    pass


MARKER = b'/* t3code-customize-windows */'


def is_customized(app, tool):
    archive = tool.Archive(app / 'resources/app.asar')
    try:
        return MARKER in archive.read('apps/desktop/dist-electron/boot.cjs')
    finally:
        archive.close()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.new')
    with temp.open('w', encoding='utf-8') as out:
        json.dump(value, out, indent=2)
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, path)


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def archives(app):
    names = ['app.asar']
    if (app / 'resources/server.asar').is_file():
        names.append('server.asar')
    return names


def executable(app):
    candidates = [app / name for name in ('T3 Code (Nightly).exe', 'T3 Code.exe')]
    found = [p for p in candidates if p.is_file()]
    if len(found) != 1:
        raise Error('Could not identify the T3 Code executable in ' + str(app))
    return found[0]


def metadata(app):
    path = app / 'resources/app.asar'
    with path.open('rb') as source:
        _, size, _, length = struct.unpack('<4I', source.read(16))
        tree = json.loads(source.read(length))
        entry = tree['files']['package.json']
        source.seek(8 + size + int(entry['offset']))
        package = json.loads(source.read(entry['size']))
    if package.get('name') != 't3code' or 'nightly' not in package.get('version', ''):
        raise Error('Only T3 Code Nightly installations are supported.')
    return {'version': package['version'], 'commit': package.get('t3codeCommitHash', '')}


def find_app(explicit=None):
    if explicit:
        path = Path(explicit).expanduser().absolute()
        if path.suffix.lower() == '.exe':
            path = path.parent
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise Error('Use the actual installation directory, not a symlink or junction.')
        resources = path / 'resources'
        if resources.is_symlink() or getattr(resources, 'is_junction', lambda: False)():
            raise Error('Refusing a redirected resources directory.')
        for file in [executable(path), *[resources / name for name in archives(path)]]:
            if file.is_symlink():
                raise Error('Refusing symlink installation files.')
        metadata(path)
        executable(path)
        return path.resolve()
    local = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local'))
    candidates = [local / 'Programs/t3code', local / 'Programs/T3 Code (Nightly)',
                  Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'T3 Code (Nightly)']
    for path in candidates:
        if not path.is_dir():
            continue
        try:
            return find_app(str(path))
        except (Error, OSError, ValueError, KeyError, struct.error):
            continue
    raise Error('Could not find T3 Code Nightly. Use --app "C:\\path\\to\\t3code".')


def check_integrity(app):
    data = executable(app).read_bytes()
    sentinel = b'dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX'
    offset = data.find(sentinel)
    if offset < 0:
        raise Error('Cannot verify Electron ASAR integrity policy for this executable.')
    wire = data[offset + len(sentinel):]
    if len(wire) < 7 or wire[0] != 1 or wire[1] < 5 or wire[6] != ord('0'):
        raise Error('Embedded ASAR integrity is enabled or unknown; this executable cannot be patched safely.')


def archive_hashes(folder):
    return {p.name: sha256(p) for p in sorted(folder.glob('*.asar'))}


def fingerprint(app):
    exe = executable(app)
    return {'metadata': metadata(app), 'executable': exe.name, 'exeHash': sha256(exe),
            'archives': {name: sha256(app / 'resources' / name) for name in archives(app)}}


def assert_closed(app):
    # The path comes through the environment rather than interpolation into code.
    script = "$p=$env:T3_CUSTOMIZE_APP; $xs=@(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { $_.ExecutablePath -and ($_.ExecutablePath.StartsWith($p+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) }); if($xs.Count){exit 10}"
    env = dict(os.environ, T3_CUSTOMIZE_APP=str(app.resolve()))
    # Windows PowerShell cannot load PowerShell 7's inherited security/CIM modules.
    env['PSModulePath'] = str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/Modules')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            env=env, capture_output=True, text=True)
    if result.returncode == 10:
        raise Error('T3 Code is running. Quit it fully, then rerun install. Use --build-only to prepare while it is open.')
    if result.returncode:
        raise Error('Could not check running T3 Code processes: ' + result.stderr.strip())


def verify_archives(folder, expected):
    if archive_hashes(folder) != expected:
        raise Error('Archive backup or prepared build is missing, changed or corrupt: ' + str(folder))


def remove_owned(path, root):
    target, boundary = path.resolve(), root.resolve()
    if target == boundary or not target.is_relative_to(boundary):
        raise Error('Refusing cleanup outside the customization directory: ' + str(target))
    shutil.rmtree(path)


def ensure_backup(app, data):
    source = fingerprint(app)
    key = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()[:20]
    backup = data / 'backups' / key
    if backup.exists():
        record = load_json(backup / 'manifest.json')
        if not record or record['source'] != source:
            raise Error('Incomplete or incompatible stock backup: ' + str(backup))
        verify_archives(backup, source['archives'])
        return backup
    temporary = backup.with_name(key + '.new')
    temporary.mkdir(parents=True, exist_ok=True)
    for name in source['archives']:
        shutil.copy2(app / 'resources' / name, temporary / name)
    verify_archives(temporary, source['archives'])
    if fingerprint(app) != source:
        raise Error('Installed app changed while creating its backup.')
    save_json(temporary / 'manifest.json', {'source': source})
    os.replace(temporary, backup)
    return backup


def copy_atomic(source, destination):
    temporary = destination.with_name(destination.name + '.t3customize-new')
    with Path(source).open('rb') as inp, temporary.open('wb') as out:
        shutil.copyfileobj(inp, out, 1 << 20)
        out.flush()
        os.fsync(out.fileno())
    if sha256(temporary) != sha256(source):
        raise Error('Copied archive verification failed.')
    os.replace(temporary, destination)


def expected_custom(manifest):
    return {**manifest['source'], 'archives': manifest['output']}


def recover(app, data):
    journal = load_json(data / 'transaction.json')
    if not journal:
        return
    assert_closed(app)
    current = fingerprint(app)
    before, after = journal['before'], journal['after']
    if current['exeHash'] != before['exeHash'] or current['executable'] != before['executable']:
        raise Error('Executable changed during recovery. Preserve the backup and recovery journal.')
    if set(current['archives']) != set(before['archives']):
        raise Error('Archive layout changed during recovery.')
    for name, digest in current['archives'].items():
        if digest not in (before['archives'][name], after['archives'][name]):
            raise Error('Unknown archive modification during recovery; preserving all recovery files.')
    # Always roll back a partially completed transaction to its verified input.
    folder = Path(journal['rollback'])
    verify_archives(folder, before['archives'])
    for name in before['archives']:
        copy_atomic(folder / name, app / 'resources' / name)
    if fingerprint(app) != before:
        raise Error('Recovery verification failed; recovery journal retained.')
    save_json(data / 'active.json', journal['activeBefore'])
    (data / 'transaction.json').unlink()


def replace(app, data, stage, manifest):
    assert_closed(app)
    recover(app, data)
    current = fingerprint(app)
    active = load_json(data / 'active.json')
    if current not in (manifest['source'], expected_custom(manifest)):
        # Replacing an older recipe is supported only from its known customized state.
        if not active or current != expected_custom(active) or active['source'] != manifest['source']:
            raise Error('Installed app changed since this build; refusing replacement.')
    verify_archives(Path(manifest['backup']), manifest['source']['archives'])
    verify_archives(stage, manifest['output'])
    rollback = data / 'rollback'
    rollback.mkdir(parents=True, exist_ok=True)
    for p in rollback.glob('*.asar'):
        p.unlink()
    for name in current['archives']:
        copy_atomic(app / 'resources' / name, rollback / name)
    verify_archives(rollback, current['archives'])
    assert_closed(app)
    if fingerprint(app) != current:
        raise Error('Installed app changed before replacement.')
    save_json(data / 'transaction.json', {'before': current, 'after': expected_custom(manifest),
              'rollback': str(rollback), 'activeBefore': active})
    for name in manifest['output']:
        copy_atomic(stage / name, app / 'resources' / name)
    if fingerprint(app) != expected_custom(manifest):
        raise Error('Installed customization verification failed; rerun install to recover.')
    save_json(data / 'active.json', manifest)
    (data / 'transaction.json').unlink()


def restore(app, data):
    recover(app, data)
    active = load_json(data / 'active.json')
    if not active:
        return
    current = fingerprint(app)
    if current == active['source']:
        return
    if current != expected_custom(active):
        raise Error('Installed app changed or is a different Nightly; refusing to restore an older backup.')
    backup = Path(active['backup'])
    verify_archives(backup, active['source']['archives'])
    restore_manifest = {**active, 'source': current, 'output': active['source']['archives']}
    # replace() requires its backup to match its source. The verified customized
    # archives are retained as that transaction's backup, allowing recovery.
    rollback_backup = ensure_backup(app, data)
    restore_manifest['backup'] = str(rollback_backup)
    replace(app, data, backup, restore_manifest)
    save_json(data / 'active.json', active)


def stage_archives(stock, stage, build, config, tool):
    stage.mkdir(parents=True, exist_ok=True)
    boot = build / 'apps/desktop/dist-electron/boot.cjs'
    if not boot.is_file():
        raise Error('Desktop build did not produce boot.cjs.')
    original = boot.read_bytes()
    try:
        boot.write_bytes(MARKER + b'\nprocess.env.T3CODE_DISABLE_AUTO_UPDATE="true";\n' + original)
        split = 'server.asar' in archives(stock)
        for name in archives(stock):
            prefixes = (('apps/desktop/dist-electron',) if name == 'app.asar' else
                        ('apps/server/dist',)) if split else ('apps/server/dist', 'apps/desktop/dist-electron')
            tool.overlay(stock / 'resources' / name, stage / name, build, config, prefixes=prefixes)
    finally:
        boot.write_bytes(original)


def build_with_wsl(args, tool, source_root, stock_source, config, log):
    if not shutil.which('wsl.exe'):
        raise Error('Windows builds require WSL with a Linux distro (for example Ubuntu). Prepared builds can be installed without rebuilding.')
    prefix = ['wsl.exe'] + (['-d', args.wsl_distro] if getattr(args, 'wsl_distro', None) else [])
    def linux_path(path):
        result = subprocess.run([*prefix, '--exec', 'wslpath', '-a', '-u', str(path)],
                                capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode:
            raise Error('Could not access WSL: ' + result.stderr.strip())
        return result.stdout.strip()
    target = tool.ensure_commit(stock_source['metadata']['commit'], stock_source['metadata']['version'], log)
    tool.prepare(target, log, resume=getattr(args, 'resume', False))
    head = tool.git('rev-parse', 'HEAD').strip()
    config_file = source_root / 'public-config.json'
    tool.save(config_file, config)
    tool.step('Building verified JavaScript in WSL (the Windows app and native helpers are retained)...')
    result_path = tool.SOURCE / 'wsl-build-result.json'
    result_path.unlink(missing_ok=True)
    wsl_log = Path(log.name).with_name(Path(log.name).stem + '-wsl.log')
    tool.say('Detailed WSL build log: ' + str(wsl_log))
    tool.run([*prefix, '--exec', 'python3', linux_path(tool.REPO / 'wsl_build.py'),
              linux_path(tool.REPO), linux_path(tool.SOURCE), head, linux_path(source_root),
              stock_source['metadata']['version'], linux_path(config_file), linux_path(wsl_log)], log=log)
    result = tool.load(result_path, {})
    if result.get('head') != head or tool.git('rev-parse', 'HEAD').strip() != head or tool.git('status', '--porcelain', '--untracked-files=no').strip():
        raise Error('Source changed during the WSL build; installation refused.')
    return target, getattr(args, 'resume', False) or (tool.REPO / 'patches/base.txt').read_text().strip() != target


def import_bundles(path, output, stock_source, recipe, target):
    try:
        return _import_bundles(path, output, stock_source, recipe, target)
    except (zipfile.BadZipFile, KeyError, ValueError) as problem:
        raise Error('Invalid portable build archive: ' + str(problem)) from problem


def _import_bundles(path, output, stock_source, recipe, target):
    """Validate a checked portable build before extracting any output."""
    with zipfile.ZipFile(path) as bundle:
        manifest = json.loads(bundle.read('bundle-manifest.json'))
        if not isinstance(manifest, dict):
            raise Error('Portable build manifest must be an object.')
        if (manifest.get('target') != target or manifest.get('version') != stock_source['metadata']['version']
                or manifest.get('recipe') != recipe or manifest.get('checksPassed') is not True):
            raise Error('Portable bundles do not match this Nightly, patch recipe, or passed checks.')
        expected = manifest.get('files', {})
        if not isinstance(expected, dict) or not expected:
            raise Error('Portable bundle manifest has no files.')
        names = bundle.namelist()
        if len(names) != len({name.casefold() for name in names}) or set(names) != set(expected) | {'bundle-manifest.json'}:
            raise Error('Portable bundle entries differ from the verified manifest.')
        for name, digest in expected.items():
            destination = output / name
            allowed = name.startswith(('apps/server/dist/', 'apps/desktop/dist-electron/'))
            if (not allowed or '\\' in name or ':' in name
                    or not destination.resolve().is_relative_to(output.resolve())
                    or (bundle.getinfo(name).external_attr >> 16) & 0o170000 == 0o120000):
                raise Error('Unsafe file path in portable bundles: ' + name)
            if hashlib.sha256(bundle.read(name)).hexdigest() != digest:
                raise Error('Portable bundle checksum failed: ' + name)
        # All entries are validated before writing, including traversal and hashes.
        for name in expected:
            destination = output / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(bundle.read(name))
    return output


def dispatch(args, tool):
    if args.command == 'launch':
        raise Error('Open your existing T3 Code shortcut normally.')
    configured = tool.load(tool.CONFIG / 'windows.json', {})
    app = find_app(getattr(args, 'app', None) or configured.get('app'))
    identity = hashlib.sha256(str(app).lower().encode()).hexdigest()[:16]
    data = tool.DATA / 'windows' / identity
    data.mkdir(parents=True, exist_ok=True)
    if getattr(args, 'app', None):
        tool.save(tool.CONFIG / 'windows.json', {'app': str(app)})
    if args.command == 'status':
        current = fingerprint(app)
        active = load_json(data / 'active.json')
        status = ('customized' if active and current == expected_custom(active) else
                  'stock' if (not active and not is_customized(app, tool)) or active and current == active['source'] else 'changed / unrecognized')
        tool.say(f"T3 Code: {app}\nVersion: {current['metadata']['version']}\nStatus: {status}\nBackups and builds: {data}")
        if (data / 'transaction.json').exists():
            tool.say('Recovery pending: quit T3 Code and rerun install or off.')
        for p in (data / 'builds').glob('*/manifest.json'):
            tool.say('Prepared build: ' + str(p.parent))
        return
    recover(app, data)
    if args.command in ('off', 'restore', 'uninstall'):
        if not load_json(data / 'active.json') and is_customized(app, tool):
            raise Error('Customized app has no recorded stock backup; refusing restore or cleanup.')
        restore(app, data)
        tool.say('Stock T3 Code restored.')
        if args.command == 'uninstall':
            active = load_json(data / 'active.json')
            if active and fingerprint(app) != active['source']:
                raise Error('Cannot remove backups while the installed app is unrecognized.')
            remove_owned(data, tool.DATA / 'windows')
            tool.say('Removed this installation\'s backups and prepared builds. User data was retained.')
        return
    if getattr(args, 'skip_checks', False):
        raise Error('--skip-checks is refused on Windows.')
    if args.command in ('build', 'install', 'reinstall') and not getattr(args, 'no_pull', False) and not getattr(args, 'resume', False):
        tool.pull_latest()
    check_integrity(app)
    current = fingerprint(app)
    active = load_json(data / 'active.json')
    if active and current == expected_custom(active):
        stock_source = active['source']
        backup = Path(active['backup'])
        verify_archives(backup, stock_source['archives'])
    else:
        if is_customized(app, tool):
            raise Error('Customized app does not match its backup record; refusing to treat it as stock.')
        if active and current != active['source'] and current['metadata'] == active['source']['metadata']:
            raise Error('Unknown modification to this Nightly; preserving backups and refusing installation.')
        stock_source = current
        backup = ensure_backup(app, data)
    recipe = tool.recipe_hash()
    key = hashlib.sha256(json.dumps(stock_source, sort_keys=True).encode() + recipe.encode()).hexdigest()[:20]
    stage = data / 'builds' / key
    manifest = load_json(stage / 'manifest.json')
    if manifest and not getattr(args, 'force', False) and not getattr(args, 'bundles', None):
        if manifest['source'] != stock_source or manifest['recipe'] != recipe:
            raise Error('Incompatible prepared build manifest.')
        verify_archives(stage, manifest['output'])
    else:
        tool.step('Preparing Windows customization for ' + current['metadata']['version'])
        source_root = data / 'stock-build-input'
        (source_root / 'resources').mkdir(parents=True, exist_ok=True)
        for p in (source_root / 'resources').glob('*.asar'):
            p.unlink()
        for name in stock_source['archives']:
            copy_atomic(backup / name, source_root / 'resources' / name)
        archive = tool.Archive(source_root / 'resources' / ('server.asar' if 'server.asar' in stock_source['archives'] else 'app.asar'))
        try:
            config = tool.read_public_config(archive)
        finally:
            archive.close()
        # Public config must be collected from both archives for split layouts.
        archive = tool.Archive(source_root / 'resources/app.asar')
        try:
            config.update(tool.read_public_config(archive))
        finally:
            archive.close()
        build_args = type('BuildArgs', (), {'resume': getattr(args, 'resume', False),
                      'skip_checks': False, 'fix': getattr(args, 'fix', None)})()
        log_dir = tool.CACHE / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f'windows-{time.time_ns()}.log'
        tool.say('Build log: ' + str(log_path))
        with log_path.open('w', encoding='utf-8') as log:
            portable = getattr(args, 'bundles', None)
            if portable:
                target = tool.ensure_commit(stock_source['metadata']['commit'], stock_source['metadata']['version'], log)
                bundle_output = data / 'portable-output'
                if bundle_output.exists():
                    remove_owned(bundle_output, data)
                build_root = import_bundles(Path(portable), bundle_output, stock_source, recipe, target)
                ported = False
            else:
                target, ported = build_with_wsl(args, tool, source_root, stock_source, config, log)
                build_root = tool.SOURCE
            temporary = stage.with_name(key + '.new')
            if temporary.exists():
                remove_owned(temporary, data / 'builds')
            stage_archives(source_root, temporary, build_root, config, tool)
            if ported:
                tool.export_patches(target)
                recipe = tool.recipe_hash()
                key = hashlib.sha256(json.dumps(stock_source, sort_keys=True).encode() + recipe.encode()).hexdigest()[:20]
                stage = data / 'builds' / key
            manifest = {'source': stock_source, 'backup': str(backup), 'recipe': recipe,
                        'output': archive_hashes(temporary), 'target': target}
            save_json(temporary / 'manifest.json', manifest)
            if stage.exists():
                remove_owned(stage, data / 'builds')
            os.replace(temporary, stage)
        if fingerprint(app) != current:
            raise Error('Installed app changed during build; prepared files retained, installation refused.')
    if getattr(args, 'build_only', False):
        tool.say('Verified build ready: ' + str(stage) + '\nQuit T3 Code, then run .\\t3code-customize.ps1 install --no-pull to apply it.')
        return
    if fingerprint(app) == expected_custom(manifest):
        tool.say('This exact customization is already installed.')
        return
    replace(app, data, stage, manifest)
    tool.say('Customization installed. Open T3 Code normally and enable Settings > General > Stats for nerds.')
