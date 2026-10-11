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
import uuid

MARKER = 'T3CodeCustomization'


class Error(RuntimeError):
    """An unsafe or unsuccessful macOS operation."""


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
        os.replace(temporary, folder)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return backup


def resolve_stock(app, data):
    metadata = read_metadata(app)
    marker = metadata['marker']
    if not marker:
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
    elif bundle_digest(app) not in (expected, transaction.get('replacement')):
        raise Error('App changed after an interrupted replacement; recovery files were retained.')
    if rollback.exists():
        if bundle_digest(rollback) != expected:
            raise Error('Rollback copy changed; recovery files were retained.')
        shutil.rmtree(rollback)
    if staging.exists():
        shutil.rmtree(staging)
    journal.unlink()


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
        assert_closed(app)
        if bundle_digest(app) != expected:
            raise Error('Installed app changed before replacement; run reinstall.')
        save_json(data / 'transaction.json', {
            'app': str(app), 'staging': str(staging), 'rollback': str(rollback),
            'expected': expected, 'replacement': replacement})
        os.replace(app, rollback)
        try:
            os.replace(staging, app)
        except BaseException:
            os.replace(rollback, app)
            (data / 'transaction.json').unlink()
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
