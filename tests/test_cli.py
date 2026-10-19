import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_macos import app_fixture
import macos

REPO = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('customize_tool', str(REPO / 't3code-customize'))
spec = importlib.util.spec_from_loader(loader.name, loader)
tool = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = tool
loader.exec_module(tool)


class CliTests(unittest.TestCase):
    def test_commit_probe_is_quiet_for_present_and_missing_commits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test',
                            '-c', 'user.email=test@example.com', 'commit',
                            '--allow-empty', '-qm', 'baseline'], check=True)
            script = (
                'import runpy, sys; from pathlib import Path; '
                'module = runpy.run_path(sys.argv[1]); '
                'probe = module["has_commit"]; '
                'probe.__globals__["SOURCE"] = Path(sys.argv[2]); '
                'assert probe("HEAD"); '
                'assert not probe("0" * 40)'
            )
            result = subprocess.run([sys.executable, '-c', script,
                                     str(REPO / 't3code-customize'), str(root)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertEqual(result.stderr, '')

    def test_install_help_accepts_app_path_and_staging(self):
        result = subprocess.run([sys.executable, str(REPO / 't3code-customize'), 'install', '--help'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--app ', result.stdout)
        self.assertIn('--build-only', result.stdout)

    def test_node_download_selects_darwin_arm64(self):
        self.assertTrue(hasattr(tool, 'node_target'), 'Node downloads have no macOS selection')
        with patch.object(tool.sys, 'platform', 'darwin'), patch.object(tool.os, 'uname') as uname:
            uname.return_value.machine = 'arm64'
            self.assertEqual(tool.node_target(), ('darwin', 'arm64', '.tar.gz'))

    def test_linux_node_selection_remains_linux_x64(self):
        self.assertTrue(hasattr(tool, 'node_target'), 'Node target selection is not implemented')
        with patch.object(tool.sys, 'platform', 'linux'), patch.object(tool.os, 'uname') as uname:
            uname.return_value.machine = 'x86_64'
            self.assertEqual(tool.node_target(), ('linux', 'x64', '.tar.xz'))

    def test_status_reports_stock_mac_app_without_appimage(self):
        self.assertTrue(hasattr(macos, 'dispatch'), 'macOS command handling is not implemented')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            app = app_fixture(root)
            args = type('Args', (), {'command': 'status', 'app': str(app)})()
            with patch.object(tool, 'DATA', root / 'data'), patch.object(tool, 'CONFIG', root / 'config'):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    macos.dispatch(args, tool)
            self.assertIn('stock', out.getvalue().lower())
            self.assertIn('0.0.46-nightly.1', out.getvalue())

    def test_packaged_boot_disables_auto_update(self):
        self.assertTrue(hasattr(macos, 'disable_updates'), 'macOS builds do not disable auto-update')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'boot.cjs'
            path.write_text('console.log(process.env.T3CODE_DISABLE_AUTO_UPDATE);')
            macos.disable_updates(path)
            result = subprocess.run(['node', str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'true')

    def test_ad_hoc_entitlements_drop_apple_team_capabilities(self):
        self.assertTrue(hasattr(macos, 'local_entitlements'), 'local signing entitlements not implemented')
        original = {'com.apple.security.cs.allow-jit': True,
                    'com.apple.application-identifier': 'TEAM.app',
                    'com.apple.developer.team-identifier': 'TEAM',
                    'com.apple.developer.associated-domains': ['webcredentials:example.com'],
                    'keychain-access-groups': ['TEAM.app']}
        self.assertEqual(macos.local_entitlements(original), {'com.apple.security.cs.allow-jit': True})

class InstallLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.app = app_fixture(self.root)
        from test_macos import write_asar
        package = b'{"version":"0.0.46-nightly.1","t3codeCommitHash":"abcdef123456"}'
        config = b','.join(key.encode() + b':"public-' + str(i).encode() + b'"'
                           for i, key in enumerate(tool.PUBLIC_CONFIG))
        write_asar(self.app / 'Contents/Resources/app.asar', {
            'package.json': package, 'native.node': b'shipped-native',
            'apps/server/dist/client/main.js': config,
            'apps/server/dist/bin.mjs': b'original-server',
            'apps/desktop/dist-electron/main.cjs': b'original-desktop'})
        self.stock_digest = macos.bundle_digest(self.app)
        for name, value in [('DATA', self.root / 'data'), ('CONFIG', self.root / 'config'),
                            ('CACHE', self.root / 'cache'), ('SOURCE', self.root / 'source'),
                            ('BIN', self.root / 'bin/t3code-customize')]:
            ctx = patch.object(tool, name, value)
            ctx.start()
            self.addCleanup(ctx.stop)
        for name in ['verify_signature', 'sign_app', 'assert_closed']:
            ctx = patch.object(macos, name)
            ctx.start()
            self.addCleanup(ctx.stop)
        self.args = type('Args', (), dict(command='install', app=str(self.app), no_pull=True,
                                         resume=False, force=False, skip_checks=False,
                                         fix=None, build_only=False))()
        self.build_count = 0
        def build(args, version, commit, stock, config, log):
            self.build_count += 1
            for relative, body in {
                'apps/server/dist/client/main.js': b'statsForNerds public-0 public-1 public-2 public-3',
                'apps/server/dist/client/index.html': b'<html></html>',
                'apps/server/dist/bin.mjs': b'claude_observed',
                'apps/desktop/dist-electron/main.cjs': b'statsForNerds',
                'apps/desktop/dist-electron/boot.cjs': b'console.log("boot");',
            }.items():
                path = tool.SOURCE / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            return commit, False
        ctx = patch.object(tool, 'build_for_version', side_effect=build)
        ctx.start()
        self.addCleanup(ctx.stop)

    def run_install(self):
        with contextlib.redirect_stdout(io.StringIO()):
            macos.dispatch(self.args, tool)

    def test_install_off_on_uses_same_app_and_exact_backup(self):
        self.run_install()
        self.assertTrue(macos.read_metadata(self.app)['marker'])
        archive = tool.Archive(self.app / 'Contents/Resources/app.asar')
        try:
            self.assertEqual(archive.read('native.node'), b'shipped-native')
            self.assertIn(b'T3CODE_DISABLE_AUTO_UPDATE', archive.read('apps/desktop/dist-electron/boot.cjs'))
        finally:
            archive.close()
        data = macos.app_data(tool, self.app)
        self.assertTrue(macos.restore(self.app, data))
        self.assertEqual(macos.bundle_digest(self.app), self.stock_digest)
        self.run_install()
        self.assertTrue(macos.read_metadata(self.app)['marker'])
        self.assertEqual(self.build_count, 1)

    def test_reinstall_is_idempotent_when_already_patched(self):
        self.run_install()
        digest = macos.bundle_digest(self.app)
        self.args.command = 'reinstall'
        self.run_install()
        self.assertEqual(self.build_count, 1)
        self.assertEqual(macos.bundle_digest(self.app), digest)

    def test_build_only_leaves_installed_app_unchanged(self):
        self.args.build_only = True
        self.run_install()
        self.assertEqual(macos.bundle_digest(self.app), self.stock_digest)
        state = macos.load_json(macos.app_data(tool, self.app) / 'state.json')
        self.assertTrue(Path(state['artifact']).is_dir())
        self.assertTrue(tool.BIN.is_symlink())

    def test_reinstall_after_new_nightly_makes_new_version_backup(self):
        self.run_install()
        data = macos.app_data(tool, self.app)
        macos.restore(self.app, data)
        import shutil
        shutil.rmtree(self.app)
        new = app_fixture(self.root / 'new', version='0.0.46-nightly.2')
        new.rename(self.app)
        from test_macos import write_asar
        config = b','.join(key.encode() + b':"public-' + str(i).encode() + b'"'
                           for i, key in enumerate(tool.PUBLIC_CONFIG))
        write_asar(self.app / 'Contents/Resources/app.asar', {
            'package.json': b'{"version":"0.0.46-nightly.2","t3codeCommitHash":"abcdef123456"}',
            'apps/server/dist/client/main.js': config,
            'apps/server/dist/bin.mjs': b'new-server',
            'apps/desktop/dist-electron/main.cjs': b'new-desktop'})
        new_digest = macos.bundle_digest(self.app)
        self.args.command = 'reinstall'
        self.run_install()
        self.assertEqual(self.build_count, 2)
        macos.restore(self.app, data)
        self.assertEqual(macos.bundle_digest(self.app), new_digest)
        self.assertTrue((data / 'backups' / self.stock_digest / 'stock.app').exists())

class ReviewRegressionTests(unittest.TestCase):
    def test_private_node_download_uses_osx_index_and_darwin_archive(self):
        import hashlib
        import tarfile
        import gzip
        tar_buffer = io.BytesIO()
        node = b'#!/bin/sh\necho 24.8.0\n'
        with tarfile.open(fileobj=tar_buffer, mode='w') as bundle:
            entry = tarfile.TarInfo('node-v24.8.0-darwin-arm64/bin/node')
            entry.size = len(node)
            entry.mode = 0o755
            bundle.addfile(entry, io.BytesIO(node))
        archive = gzip.compress(tar_buffer.getvalue())
        def urlopen(url, **kwargs):
            if url.endswith('index.json'):
                return io.BytesIO(b'[{"version":"v24.8.0","files":["osx-arm64-tar","osx-x64-tar","linux-x64"]}]')
            return io.BytesIO((hashlib.sha256(archive).hexdigest() + '  node-v24.8.0-darwin-arm64.tar.gz\n').encode())
        def download(url, destination):
            Path(destination).write_bytes(archive)
        with tempfile.TemporaryDirectory() as temp, patch.object(tool, 'CACHE', Path(temp)), \
                patch.object(tool.shutil, 'which', return_value=None), patch.object(tool.sys, 'platform', 'darwin'), \
                patch.object(tool.os, 'uname') as uname, patch.object(tool.urllib.request, 'urlopen', side_effect=urlopen), \
                patch.object(tool.urllib.request, 'urlretrieve', side_effect=download):
            uname.return_value.machine = 'arm64'
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    node_bin = tool.ensure_node(None)
            except StopIteration:
                self.fail('No macOS release matched the real osx-arm64-tar index identifier')
            self.assertEqual(tool.node_major(str(node_bin / 'node')), 24)

    def test_status_cannot_enter_recovery_while_install_lock_is_held(self):
        import fcntl
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            app = app_fixture(root)
            cache = root / 'cache'
            cache.mkdir()
            with (cache / 'lock').open('w') as held:
                fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.object(tool, 'CACHE', cache), patch.object(tool, 'DATA', root / 'data'), \
                     patch.object(tool, 'CONFIG', root / 'config'), patch.object(tool.sys, 'platform', 'darwin'), \
                     patch.object(tool.sys, 'argv', ['t3code-customize', 'status', '--app', str(app)]):
                    with self.assertRaisesRegex(tool.Stop, 'already running'):
                        with contextlib.redirect_stdout(io.StringIO()):
                            tool.main()

    def test_auto_discovery_is_saved_for_missing_app_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            app = app_fixture(root)
            args = type('Args', (), {'command': 'status', 'app': None})()
            with patch.object(tool, 'DATA', root / 'data'), patch.object(tool, 'CONFIG', root / 'config'), \
                 patch.object(macos, 'find_app', return_value=app):
                macos.locate(args, tool)
            saved = tool.load(root / 'config/config.json', {})
            self.assertEqual(saved.get('app'), str(app), 'Discovery was not saved before potential replacement')

    def test_tracked_source_edit_during_build_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            source = root / 'source.ts'
            source.write_text('validated code')
            subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                            'commit', '-qm', 'baseline'], check=True)
            head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
            args = type('Args', (), {'resume': False, 'skip_checks': False, 'fix': None})()
            with patch.object(tool, 'SOURCE', root), patch.object(tool, 'ensure_node', return_value=None), \
                    patch.object(tool, 'ensure_commit', return_value=head), patch.object(tool, 'prepare'), \
                    patch.object(tool, 'install_dependencies'), patch.object(tool, 'checks'), \
                    patch.object(tool, 'build_bundles', side_effect=lambda *a: source.write_text('unvalidated edit')):
                with self.assertRaisesRegex(tool.Stop, 'source checkout changed'):
                    with contextlib.redirect_stdout(io.StringIO()):
                        tool.build_for_version(args, 'nightly.1', head, root, {}, None)


if __name__ == '__main__':
    unittest.main()
