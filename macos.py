"""macOS bundle packaging and reversible, version-bound installation."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import struct
import subprocess
import sys
import time
from types import SimpleNamespace
import uuid

MARKER = 'T3CodeCustomization'


class Error(RuntimeError):
    """An unsafe or unsuccessful macOS operation."""


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def sync_bundle(app):
    """Persist copied files before the last recovery copy can be removed."""
    for base, _, files in os.walk(app, topdown=False, followlinks=False):
        for name in files:
            path = Path(base) / name
            if not path.is_symlink():
                with path.open('rb') as source:
                    os.fsync(source.fileno())
        sync_directory(base)


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.new')
    with temp.open('w') as out:
        json.dump(value, out, indent=2)
        out.write('\n')
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, path)
    sync_directory(path.parent)


def load_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def read_info(app):
    return plistlib.loads((app / 'Contents/Info.plist').read_bytes())


def write_info(app, info):
    (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))


def raw_header(archive):
    with archive.open('rb') as source:
        _, size, _, json_size = struct.unpack('<4I', source.read(16))
        data = source.read(json_size)
        if len(data) != json_size:
            raise Error('Truncated app.asar header.')
        return data, 8 + size


def read_metadata(app):
    info = read_info(app)
    if info.get('CFBundleIdentifier') != 'com.t3tools.t3code':
        raise Error('This is not a T3 Code app bundle.')
    archive = app / 'Contents/Resources/app.asar'
    header, offset = raw_header(archive)
    entry = json.loads(header)['files']['package.json']
    with archive.open('rb') as source:
        source.seek(offset + int(entry['offset']))
        package = json.loads(source.read(entry['size']))
    version = package['version']
    if 'nightly' not in version:
        raise Error(f'T3 Code {version} is not Nightly. Install T3 Code Nightly first.')
    if info.get('CFBundleShortVersionString') != version:
        raise Error('T3 Code bundle and archive versions disagree.')
    return {'version': version, 'commit': package.get('t3codeCommitHash', ''),
            'marker': info.get(MARKER)}


def find_app(explicit=None, search=None):
    if explicit:
        path = Path(explicit).expanduser().absolute()
        if path.is_symlink():
            raise Error('Refusing a symlink installation; use the actual .app path.')
        if not path.is_dir() or path.suffix != '.app':
            raise Error(f'No app bundle at {path}.')
        read_metadata(path)
        return path.resolve()
    folders = search if search is not None else [Path('/Applications'), Path.home() / 'Applications']
    for folder in folders:
        for app in sorted(folder.glob('T3 Code*.app')):
            if app.is_symlink():
                continue
            try:
                read_metadata(app)
                return app.resolve()
            except (Error, OSError, ValueError, KeyError, struct.error):
                continue
    raise Error('Could not find T3 Code Nightly. Use --app /path/to/T3-Code.app.')


def bundle_digest(app):
    """Hash names, modes, contents and internal symlinks without following them."""
    app = app.absolute()
    if app.is_symlink() or not app.is_dir():
        raise Error(f'Invalid or symlink app bundle: {app}')
    digest = hashlib.sha256()
    for base, dirs, files in os.walk(app, followlinks=False):
        dirs.sort()
        files.sort()
        for name in sorted(dirs + files):
            path = Path(base) / name
            mode = path.lstat().st_mode
            digest.update(path.relative_to(app).as_posix().encode() + b'\0')
            digest.update(str(stat.S_IMODE(mode)).encode() + b'\0')
            if path.is_symlink():
                if not path.resolve().is_relative_to(app.resolve()):
                    raise Error(f'External symlink inside app: {path}')
                digest.update(b'L' + os.readlink(path).encode() + b'\0')
            elif path.is_file():
                digest.update(b'F')
                with path.open('rb') as source:
                    for chunk in iter(lambda: source.read(1 << 20), b''):
                        digest.update(chunk)
            elif path.is_dir():
                digest.update(b'D')
            else:
                raise Error(f'Unsupported file in app: {path}')
    return digest.hexdigest()


def copy_app(source, destination):
    if destination.exists() or destination.is_symlink():
        raise Error(f'Refusing to overwrite staging path {destination}.')
    if sys.platform == 'darwin':
        subprocess.run(['ditto', str(source), str(destination)], check=True)
    else:
        shutil.copytree(source, destination, symlinks=True)


def update_integrity(app):
    raw, _ = raw_header(app / 'Contents/Resources/app.asar')
    info = read_info(app)
    info.setdefault('ElectronAsarIntegrity', {})['Resources/app.asar'] = {
        'algorithm': 'SHA256', 'hash': hashlib.sha256(raw).hexdigest()}
    write_info(app, info)


def set_marker(app, marker):
    info = read_info(app)
    info[MARKER] = marker
    write_info(app, info)


def assert_closed(app):
    processes = subprocess.check_output(['ps', '-axo', 'pid=,comm='], text=True)
    prefix = str(app) + '/Contents/'
    if any(line.strip().partition(' ')[2].lstrip().startswith(prefix)
           for line in processes.splitlines()):
        raise Error('Quit T3 Code fully before installing or restoring. '
                    'Your prepared build is cached; run t3code-customize install again.')


def ensure_backup(app, data):
    metadata = read_metadata(app)
    if metadata['marker']:
        return resolve_stock(app, data)
    digest = bundle_digest(app)
    folder = data / 'backups' / digest
    backup = folder / 'stock.app'
    manifest = folder / 'manifest.json'
    if manifest.exists():
        if bundle_digest(backup) != digest:
            raise Error('The stock backup is corrupt; refusing to overwrite it.')
        return backup
    if folder.exists():
        raise Error(f'Incomplete stock backup at {folder}. Preserve it and inspect before retrying.')
    folder.parent.mkdir(parents=True, exist_ok=True)
    temporary = folder.with_name('.' + digest + '-' + uuid.uuid4().hex)
    temporary.mkdir()
    try:
        copy_app(app, temporary / 'stock.app')
        if bundle_digest(temporary / 'stock.app') != digest:
            raise Error('The app changed while making its stock backup. Retry after updating finishes.')
        save_json(temporary / 'manifest.json', {
            'app': str(app), 'stockDigest': digest, **metadata, 'customDigests': []})
        sync_bundle(temporary)
        os.replace(temporary, folder)
        sync_directory(folder.parent)
        sync_directory(folder.parent.parent)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return backup


def resolve_stock(app, data):
    metadata = read_metadata(app)
    marker = metadata['marker']
    if not marker:
        state = load_json(data / 'state.json', {})
        if (state.get('version') == metadata['version'] and state.get('commit') == metadata['commit']
                and bundle_digest(app) != state.get('stockDigest')):
            raise Error('Unmarked app was modified outside this tool; backups are retained. '
                        'Restore a known official Nightly installation before retrying.')
        return app
    digest = marker.get('stockDigest', '')
    if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise Error('Customized app has no valid stock backup identifier.')
    folder = data / 'backups' / digest
    manifest = load_json(folder / 'manifest.json', {})
    backup = folder / 'stock.app'
    if (manifest.get('app') != str(app) or manifest.get('stockDigest') != digest
            or manifest.get('version') != metadata['version']
            or manifest.get('commit') != metadata['commit'] or not backup.is_dir()):
        raise Error('Matching stock backup is missing; refusing to patch or restore this app.')
    if bundle_digest(backup) != digest:
        raise Error('Matching stock backup is corrupt; refusing to restore it.')
    if bundle_digest(app) not in manifest.get('customDigests', []):
        raise Error('The customized app changed outside this tool; preserve it and its stock backup.')
    return backup


def record_build(app, data, backup, recipe, artifact=None):
    artifact = artifact or app
    manifest_path = backup.parent / 'manifest.json'
    manifest = load_json(manifest_path)
    custom = bundle_digest(artifact)
    if custom not in manifest['customDigests']:
        manifest['customDigests'].append(custom)
    save_json(manifest_path, manifest)
    save_json(data / 'state.json', {
        'app': str(app), 'stockDigest': manifest['stockDigest'], 'customDigest': custom,
        'version': manifest['version'], 'commit': manifest['commit'],
        'recipe': recipe, 'artifact': str(artifact)})


def recover_transaction(app, data):
    journal = data / 'transaction.json'
    transaction = load_json(journal)
    if not transaction:
        return
    if transaction['app'] != str(app):
        raise Error('Recovery journal belongs to a different app.')
    rollback, staging = (Path(transaction[k]) for k in ('rollback', 'staging'))
    for path in (rollback, staging):
        if (path.parent != app.parent or not path.name.startswith('.customize')
                or path.suffix != '.app' or path.is_symlink()):
            raise Error('Unsafe recovery path in transaction journal.')
    assert_closed(app)
    expected = transaction['expected']
    if not app.exists():
        if not rollback.is_dir() or bundle_digest(rollback) != expected:
            raise Error('Interrupted replacement needs manual recovery; stock backup was retained.')
        os.replace(rollback, app)
        sync_directory(app.parent)
    elif bundle_digest(app) not in (expected, transaction.get('replacement')):
        raise Error('App changed after an interrupted replacement; recovery files were retained.')
    if rollback.exists():
        if bundle_digest(rollback) != expected:
            raise Error('Rollback copy changed; recovery files were retained.')
        # A replacement or restored bundle is made durable before deleting
        # the last sibling recovery copy or its journal.
        sync_bundle(app)
        sync_directory(app.parent)
        shutil.rmtree(rollback)
    if staging.exists():
        shutil.rmtree(staging)
    journal.unlink()
    sync_directory(app.parent)
    sync_directory(data)


def replace_app(app, source, data, expected):
    recover_transaction(app, data)
    assert_closed(app)
    if bundle_digest(app) != expected:
        raise Error('Installed app changed during the build; run reinstall for the new version.')
    token = uuid.uuid4().hex
    staging = app.with_name(f'.customize-{token}.staging.app')
    rollback = app.with_name(f'.customize-{token}-rollback.app')
    replacement = bundle_digest(source)
    try:
        copy_app(source, staging)
        if bundle_digest(staging) != replacement:
            raise Error('Staged app did not match its verified source.')
        sync_bundle(staging)
        sync_directory(app.parent)
        assert_closed(app)
        if bundle_digest(app) != expected:
            raise Error('Installed app changed before replacement; run reinstall.')
        save_json(data / 'transaction.json', {
            'app': str(app), 'staging': str(staging), 'rollback': str(rollback),
            'expected': expected, 'replacement': replacement})
        os.replace(app, rollback)
        sync_directory(app.parent)
        try:
            os.replace(staging, app)
            sync_directory(app.parent)
        except BaseException:
            # A failed durability barrier after the rename leaves both valid
            # copies and the journal for the next recovery pass.
            if app.exists():
                raise
            os.replace(rollback, app)
            sync_directory(app.parent)
            (data / 'transaction.json').unlink()
            sync_directory(data)
            raise
        recover_transaction(app, data)
    finally:
        if not (data / 'transaction.json').exists() and staging.exists():
            shutil.rmtree(staging)


def restore(app, data):
    recover_transaction(app, data)
    stock = resolve_stock(app, data)
    if stock == app:
        return False
    replace_app(app, stock, data, expected=bundle_digest(app))
    return True


def disable_updates(boot):
    """Set the upstream opt-out at boot, including when opened from Finder."""
    boot.write_bytes(b'process.env.T3CODE_DISABLE_AUTO_UPDATE = "true";\n' + boot.read_bytes())


def local_entitlements(original):
    # Developer ID, associated domains and keychain groups cannot be granted by
    # an ad-hoc signature. Preserve only runtime capabilities for Electron/V8.
    return {key: value for key, value in original.items() if key.startswith('com.apple.security.cs.')}


def verify_signature(app, log=None):
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)],
                   stdout=log, stderr=log, check=True)


def sign_app(app, log):
    result = subprocess.run(['codesign', '-d', '--entitlements', '-', '--xml', str(app)],
                            capture_output=True, check=True)
    original = plistlib.loads(result.stdout) if result.stdout.strip() else {}
    entitlements = app.parent / 'local-entitlements.plist'
    entitlements.write_bytes(plistlib.dumps(local_entitlements(original)))
    try:
        # Nested shipped binaries keep their original signatures. Only the
        # outer app's executable and resource seal must be signed again.
        subprocess.run(['codesign', '--force', '--sign', '-', '--options', 'runtime',
                        '--entitlements', str(entitlements), str(app)],
                       stdout=log, stderr=log, check=True)
    finally:
        entitlements.unlink(missing_ok=True)
    # A copied download may have quarantine flags, but this is a locally built
    # app. Never change extended attributes on the original stock backup.
    subprocess.run(['xattr', '-dr', 'com.apple.quarantine', str(app)],
                   stdout=log, stderr=log, check=True)
    verify_signature(app, log)


def app_data(api, app):
    return api.DATA / 'macos' / hashlib.sha256(str(app).encode()).hexdigest()[:16]


def locate(args, api):
    configured = api.load(api.CONFIG / 'config.json', {}).get('app')
    explicit = getattr(args, 'app', None) or configured
    if explicit:
        path = Path(explicit).expanduser().absolute()
        if path.is_symlink():
            raise Error('Refusing a symlink installation; use the actual .app path.')
        path = path.parent.resolve() / path.name
        # Recover a rename interrupted before the app was put back, before
        # discovery attempts to read the currently missing bundle.
        recover_transaction(path, app_data(api, path))
        explicit = path
    app = find_app(explicit=explicit)
    # Save discovery before an install can move the app out of the way. Even
    # if the bundle is temporarily missing, the next plain command can recover.
    api.save(api.CONFIG / 'config.json', {**api.load(api.CONFIG / 'config.json', {}), 'app': str(app)})
    return app, app_data(api, app)


def install_cli(api):
    api.BIN.parent.mkdir(parents=True, exist_ok=True)
    if api.BIN.exists() or api.BIN.is_symlink():
        if not api.BIN.is_symlink() or api.BIN.resolve() != api.REPO / api.NAME:
            raise Error(f'{api.BIN} already exists and belongs to another installation.')
    else:
        api.BIN.symlink_to(api.REPO / api.NAME)


def build_and_install(args, api, app, data):
    if args.skip_checks:
        raise Error('macOS installation requires the patch tests and typechecks; --skip-checks is not supported.')
    if not args.no_pull and not args.resume:
        api.pull_latest()
    recover_transaction(app, data)
    observed = bundle_digest(app)
    stock = resolve_stock(app, data)
    verify_signature(stock)
    stock = ensure_backup(stock, data) if stock == app else stock
    metadata = read_metadata(stock)
    state = load_json(data / 'state.json', {})
    recipe = api.recipe_hash()
    artifact = Path(state.get('artifact', ''))
    cached = (not args.force and not args.resume and state.get('stockDigest') == bundle_digest(stock)
              and state.get('recipe') == recipe and artifact.is_dir()
              and bundle_digest(artifact) == state.get('customDigest'))
    if not cached:
        job = data / 'builds' / (metadata['version'] + '-' + uuid.uuid4().hex)
        job.mkdir(parents=True)
        artifact = job / app.name
        logs = api.CACHE / 'logs'
        logs.mkdir(parents=True, exist_ok=True)
        log_path = logs / ('macos-' + time.strftime('%Y%m%d-%H%M%S') + '.log')
        api.say('Log: ' + str(log_path))
        with log_path.open('w') as log:
            api.step(f"Building for T3 Code {metadata['version']} ({metadata['commit']})...")
            copy_app(stock, artifact)
            resources = artifact / 'Contents/Resources'
            archive = api.Archive(resources / 'app.asar')
            try:
                config = api.read_public_config(archive)
            finally:
                archive.close()
            if len(config) != len(api.PUBLIC_CONFIG):
                raise Error('Could not read all T3 Connect public config; refusing to install an incomplete build.')
            target, ported = api.build_for_version(
                args, metadata['version'], metadata['commit'], artifact, config, log)
            disable_updates(api.SOURCE / 'apps/desktop/dist-electron/boot.cjs')
            api.step('Assembling and signing the macOS app...')
            output = job / 'app.asar'
            api.overlay(resources / 'app.asar', output, api.SOURCE, config)
            os.replace(output, resources / 'app.asar')
            update_integrity(artifact)
            if ported:
                api.export_patches(target)
            recipe = api.recipe_hash()
            set_marker(artifact, {'stockDigest': bundle_digest(stock), 'recipe': recipe,
                                  'version': metadata['version'], 'format': 1})
            sign_app(artifact, log)
        if bundle_digest(app) != observed:
            raise Error('Installed app changed while building. Run reinstall for the new version.')
        record_build(app, data, stock, recipe, artifact=artifact)
    else:
        api.say('Using the verified cached build for ' + metadata['version'] + '.')
        verify_signature(artifact)
    install_cli(api)
    if args.build_only:
        api.say('Verified build is ready: ' + str(artifact))
        api.say('Quit T3 Code, then run: t3code-customize install')
        return
    if bundle_digest(app) == load_json(data / 'state.json')['customDigest']:
        api.say('Customization is already installed for ' + metadata['version'] + '.')
        return
    replace_app(app, artifact, data, expected=observed)
    api.say('Installed in ' + str(app) + '. Open T3 Code normally.')
    api.say('Turn on Settings > General > Stats for nerds.')
    api.say('Before updating Nightly: quit T3 Code, run t3code-customize off, update, then run t3code-customize reinstall.')


def dispatch(args, api):
    app, data = locate(args, api)
    if args.command in ('build', 'install', 'reinstall', 'on'):
        if args.command == 'on':
            args = SimpleNamespace(command='install', app=str(app), no_pull=True, resume=False,
                                   force=False, skip_checks=False, fix=None, build_only=False)
        return build_and_install(args, api, app, data)
    if args.command == 'status':
        metadata = read_metadata(app)
        state = load_json(data / 'state.json', {})
        api.say('Installed T3 Code: ' + str(app))
        api.say('Version: ' + metadata['version'])
        if metadata['marker']:
            stock = resolve_stock(app, data)
            api.say('Customization: installed (locally signed; auto-update disabled)')
            api.say('Stock backup: ' + str(stock))
        else:
            api.say('Customization: off (stock app)')
        if state.get('version') == metadata['version']:
            api.say('Prepared build: ' + state.get('artifact', 'none'))
        elif state:
            api.say('Nightly changed. Run t3code-customize reinstall.')
        return
    if args.command in ('off', 'restore', 'uninstall'):
        changed = restore(app, data)
        api.say('Restored official T3 Code.' if changed else 'T3 Code is already stock; no older backup was applied.')
        if args.command == 'uninstall':
            verify_signature(app)
            if data.exists():
                shutil.rmtree(data)
            remaining = list((api.DATA / 'macos').glob('*/state.json'))
            if not remaining and api.BIN.is_symlink() and api.BIN.resolve() == api.REPO / api.NAME:
                api.BIN.unlink()
            api.say('Removed this app\'s customization, backups and cached builds. Source checkout and build tools are retained.')
        return
    if args.command == 'launch':
        subprocess.run(['open', str(app), '--args', *args.rest], check=True)
        return
    raise Error('Unknown macOS command: ' + args.command)
