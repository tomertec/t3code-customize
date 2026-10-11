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


if __name__ == '__main__':
    unittest.main()

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
