import hashlib
import json
import os
from pathlib import Path
import plistlib
import struct
import tempfile
import unittest
from unittest.mock import patch

try:
    import macos
except ImportError:
    macos = None


def write_asar(path, files):
    tree = {'files': {}}
    body = b''
    for key, data in files.items():
        node = tree
        parts = key.split('/')
        for part in parts[:-1]:
            node = node['files'].setdefault(part, {'files': {}})
        node['files'][parts[-1]] = {'size': len(data), 'offset': str(len(body))}
        body += data
    raw = json.dumps(tree, separators=(',', ':')).encode()
    padding = b'\0' * (-len(raw) % 4)
    header = struct.pack('<II', 4 + len(raw + padding), len(raw)) + raw + padding
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack('<II', 4, len(header)) + header + body)
    return raw


def app_fixture(root, version='0.0.46-nightly.1', content=b'original'):
    app = root / 'T3 Code (Nightly).app'
    resources = app / 'Contents/Resources'
    resources.mkdir(parents=True)
    executable = app / 'Contents/MacOS/T3 Code (Nightly)'
    executable.parent.mkdir()
    executable.write_bytes(content)
    executable.chmod(0o755)
    info = {'CFBundleIdentifier': 'com.t3tools.t3code',
            'CFBundleExecutable': executable.name, 'CFBundleShortVersionString': version}
    (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    write_asar(resources / 'app.asar', {'package.json': json.dumps(
        {'version': version, 't3codeCommitHash': 'abcdef123456'}).encode()})
    return app


class MacTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(macos, 'macOS support has not been implemented')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.app = app_fixture(self.root)
        self.data = self.root / 'data'

    def test_discovery_ignores_alpha_and_finds_nightly(self):
        alpha = app_fixture(self.root / 'alpha', version='0.0.46-preview.1')
        alpha.rename(self.root / 'T3 Code (Alpha).app')
        self.assertEqual(macos.find_app(search=[self.root]), self.app)

    def test_symlink_installation_is_rejected(self):
        link = self.root / 'Other.app'
        link.symlink_to(self.app)
        with self.assertRaisesRegex(macos.Error, 'symlink'):
            macos.find_app(explicit=link)

    def test_integrity_hashes_raw_json_header_not_entire_archive(self):
        raw = write_asar(self.app / 'Contents/Resources/app.asar', {'hello.txt': b'world'})
        macos.update_integrity(self.app)
        info = plistlib.loads((self.app / 'Contents/Info.plist').read_bytes())
        self.assertEqual(info['ElectronAsarIntegrity']['Resources/app.asar']['hash'],
                         hashlib.sha256(raw).hexdigest())

    def test_marker_without_backup_refuses_repatch(self):
        macos.set_marker(self.app, {'stockDigest': 'deadbeef'})
        with self.assertRaisesRegex(macos.Error, 'backup'):
            macos.resolve_stock(self.app, self.data)

    def test_backup_is_preserved_and_restore_returns_exact_stock(self):
        digest = macos.bundle_digest(self.app)
        backup = macos.ensure_backup(self.app, self.data)
        stage = app_fixture(self.root / 'stage', content=b'custom')
        macos.set_marker(stage, {'stockDigest': digest})
        with patch.object(macos, 'assert_closed'):
            macos.replace_app(self.app, stage, self.data, expected=digest)
        macos.record_build(self.app, self.data, backup, recipe='test')
        self.assertEqual(macos.resolve_stock(self.app, self.data), backup)
        with patch.object(macos, 'assert_closed'):
            macos.restore(self.app, self.data)
        self.assertEqual(macos.bundle_digest(self.app), digest)
        self.assertTrue(backup.exists())

    def test_new_nightly_is_never_replaced_by_old_restore(self):
        backup = macos.ensure_backup(self.app, self.data)
        macos.record_build(self.app, self.data, backup, recipe='test')
        newer = app_fixture(self.root / 'new', version='0.0.46-nightly.2', content=b'newer')
        import shutil
        shutil.rmtree(self.app)
        newer.rename(self.app)
        digest = macos.bundle_digest(self.app)
        with patch.object(macos, 'assert_closed'):
            macos.restore(self.app, self.data)
        self.assertEqual(macos.bundle_digest(self.app), digest)
        self.assertEqual(macos.read_metadata(self.app)['version'], '0.0.46-nightly.2')

    def test_changed_app_during_build_refuses_replacement(self):
        expected = macos.bundle_digest(self.app)
        (self.app / 'Contents/MacOS/T3 Code (Nightly)').write_bytes(b'new update')
        stage = app_fixture(self.root / 'stage', content=b'custom')
        with patch.object(macos, 'assert_closed'), self.assertRaisesRegex(macos.Error, 'changed'):
            macos.replace_app(self.app, stage, self.data, expected=expected)
        self.assertEqual((self.app / 'Contents/MacOS/T3 Code (Nightly)').read_bytes(), b'new update')

    def test_failed_replacement_rolls_back_original(self):
        expected = macos.bundle_digest(self.app)
        stage = app_fixture(self.root / 'stage', content=b'custom')
        real_replace = os.replace
        def fail_install(src, dst):
            if Path(src).name.endswith('.staging.app'):
                raise OSError('simulated disk failure')
            return real_replace(src, dst)
        with patch.object(macos, 'assert_closed'), patch.object(macos.os, 'replace', side_effect=fail_install):
            with self.assertRaisesRegex(OSError, 'disk failure'):
                macos.replace_app(self.app, stage, self.data, expected=expected)
        self.assertEqual(macos.bundle_digest(self.app), expected)

    def test_modified_backup_refuses_restore(self):
        digest = macos.bundle_digest(self.app)
        backup = macos.ensure_backup(self.app, self.data)
        stage = app_fixture(self.root / 'stage', content=b'custom')
        macos.set_marker(stage, {'stockDigest': digest})
        with patch.object(macos, 'assert_closed'):
            macos.replace_app(self.app, stage, self.data, expected=digest)
        macos.record_build(self.app, self.data, backup, recipe='test')
        (backup / 'Contents/MacOS/T3 Code (Nightly)').write_bytes(b'corruption')
        with self.assertRaisesRegex(macos.Error, 'backup'):
            macos.resolve_stock(self.app, self.data)

    def test_running_app_is_detected_from_executable_path(self):
        with patch.object(macos.subprocess, 'check_output', return_value=f'123 {self.app}/Contents/MacOS/T3 Code (Nightly)\n'):
            with self.assertRaisesRegex(macos.Error, 'Quit'):
                macos.assert_closed(self.app)

    def test_external_symlink_is_rejected(self):
        (self.app / 'Contents/outside').symlink_to('/tmp')
        with self.assertRaisesRegex(macos.Error, 'symlink'):
            macos.bundle_digest(self.app)

    def test_interrupted_transaction_restores_original(self):
        digest = macos.bundle_digest(self.app)
        rollback = self.app.with_name('.customize-rollback.app')
        stage = self.app.with_name('.customize.staging.app')
        self.data.mkdir()
        macos.save_json(self.data / 'transaction.json', {'app': str(self.app), 'rollback': str(rollback),
                                                       'staging': str(stage), 'expected': digest})
        self.app.rename(rollback)
        macos.recover_transaction(self.app, self.data)
        self.assertEqual(macos.bundle_digest(self.app), digest)
        self.assertFalse((self.data / 'transaction.json').exists())


if __name__ == '__main__':
    unittest.main()
