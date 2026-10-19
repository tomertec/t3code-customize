import importlib.machinery
import importlib.util
import json
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
import subprocess
import zipfile
from unittest.mock import patch

from test_macos import write_asar

REPO = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('windows_tool', str(REPO / 't3code-customize'))
spec = importlib.util.spec_from_loader(loader.name, loader)
tool = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = tool
loader.exec_module(tool)
import windows


def fixture(root, version='0.0.46-nightly.1'):
    app = root / 'T3 Code'
    app.mkdir(parents=True)
    (app / 'T3 Code (Nightly).exe').write_bytes(b'MZfixture')
    write_asar(app / 'resources/app.asar', {
        'package.json': json.dumps({'name': 't3code', 'version': version,
                                   't3codeCommitHash': 'abcdef123456'}).encode(),
        'apps/desktop/dist-electron/boot.cjs': b'boot',
        'apps/desktop/dist-electron/main.cjs': b'stock desktop',
        'native.node': b'native desktop'})
    write_asar(app / 'resources/server.asar', {
        'apps/server/dist/bin.mjs': b'stock server',
        'apps/server/dist/client/index.html': b'stock web',
        'native.node': b'native server'})
    return app


class WindowsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = fixture(self.root)
        self.data = self.root / 'data'
        self.original = windows.fingerprint(self.app)

    def prepared(self):
        backup = windows.ensure_backup(self.app, self.data)
        stage = self.data / 'prepared'
        stage.mkdir()
        for name in windows.archives(self.app):
            (stage / name).write_bytes((self.app / 'resources' / name).read_bytes() + b'custom')
        manifest = {'source': self.original, 'backup': str(backup),
                    'output': windows.archive_hashes(stage), 'recipe': 'test'}
        windows.save_json(stage / 'manifest.json', manifest)
        return stage, manifest

    def test_split_metadata_and_exact_restore(self):
        self.assertEqual(windows.metadata(self.app)['commit'], 'abcdef123456')
        stage, manifest = self.prepared()
        with patch.object(windows, 'assert_closed'):
            windows.replace(self.app, self.data, stage, manifest)
            self.assertNotEqual(windows.fingerprint(self.app), self.original)
            windows.restore(self.app, self.data)
        self.assertEqual(windows.fingerprint(self.app), self.original)

    def test_changed_source_refuses_apply(self):
        stage, manifest = self.prepared()
        (self.app / 'T3 Code (Nightly).exe').write_bytes(b'new version')
        with patch.object(windows, 'assert_closed'), self.assertRaisesRegex(windows.Error, 'changed'):
            windows.replace(self.app, self.data, stage, manifest)

    def test_corrupt_backup_refuses_restore(self):
        stage, manifest = self.prepared()
        with patch.object(windows, 'assert_closed'):
            windows.replace(self.app, self.data, stage, manifest)
            (Path(manifest['backup']) / 'app.asar').write_bytes(b'corrupt')
            with self.assertRaisesRegex(windows.Error, 'backup'):
                windows.restore(self.app, self.data)

    def test_newer_version_is_never_restored(self):
        stage, manifest = self.prepared()
        with patch.object(windows, 'assert_closed'):
            windows.replace(self.app, self.data, stage, manifest)
            write_asar(self.app / 'resources/app.asar', {'package.json': json.dumps({
                'name': 't3code', 'version': '0.0.46-nightly.2',
                't3codeCommitHash': '123456abcdef'}).encode()})
            with self.assertRaisesRegex(windows.Error, 'changed|different'):
                windows.restore(self.app, self.data)

    def test_interrupted_multi_archive_replacement_recovers_stock(self):
        stage, manifest = self.prepared()
        actual = windows.copy_atomic
        calls = []
        def fail_second(source, destination):
            if destination.parent == self.app / 'resources':
                calls.append(destination)
                if len(calls) == 2:
                    raise OSError('simulated interruption')
            actual(source, destination)
        with patch.object(windows, 'assert_closed'), patch.object(windows, 'copy_atomic', fail_second):
            with self.assertRaises(OSError):
                windows.replace(self.app, self.data, stage, manifest)
        with patch.object(windows, 'assert_closed'):
            windows.recover(self.app, self.data)
        self.assertEqual(windows.fingerprint(self.app), self.original)

    def test_unknown_partial_modification_preserves_recovery(self):
        stage, manifest = self.prepared()
        with patch.object(windows, 'assert_closed'):
            windows.replace(self.app, self.data, stage, manifest)
            (self.app / 'resources/server.asar').write_bytes(b'unknown')
            with self.assertRaisesRegex(windows.Error, 'changed|unknown'):
                windows.restore(self.app, self.data)
        self.assertTrue((self.data / 'active.json').exists())

    def test_running_application_refuses_replacement(self):
        stage, manifest = self.prepared()
        with patch.object(windows, 'assert_closed', side_effect=windows.Error('running')):
            with self.assertRaisesRegex(windows.Error, 'running'):
                windows.replace(self.app, self.data, stage, manifest)
        self.assertEqual(windows.fingerprint(self.app), self.original)

    def test_split_overlay_keeps_native_entries(self):
        build = self.root / 'build'
        for name, data in {
            'apps/server/dist/bin.mjs': b'claude_observed',
            'apps/server/dist/client/index.html': b'web',
            'apps/server/dist/client/main.js': b'statsForNerds',
            'apps/desktop/dist-electron/main.cjs': b'statsForNerds',
            'apps/desktop/dist-electron/compileCache.cjs': b'cache',
            'apps/desktop/dist-electron/boot.cjs': b'boot'}.items():
            p = build / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        stage = self.root / 'stage'
        windows.stage_archives(self.app, stage, build, {}, tool)
        for name in windows.archives(self.app):
            a = tool.Archive(stage / name)
            try:
                self.assertIn(a.read('native.node'), (b'native desktop', b'native server'))
            finally:
                a.close()
        a = tool.Archive(stage / 'app.asar')
        try:
            self.assertIn(b'T3CODE_DISABLE_AUTO_UPDATE', a.read('apps/desktop/dist-electron/boot.cjs'))
            self.assertIn(b'--no-maglev', a.read('apps/desktop/dist-electron/compileCache.cjs'))
        finally:
            a.close()
        self.assertEqual((build / 'apps/desktop/dist-electron/compileCache.cjs').read_bytes(), b'cache')

    def test_integrity_enabled_executable_is_rejected(self):
        (self.app / 'T3 Code (Nightly).exe').write_bytes(
            b'dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX' + bytes([1, 9]) + b'100110011')
        with self.assertRaisesRegex(windows.Error, 'integrity'):
            windows.check_integrity(self.app)

    def test_supported_executable_integrity_policy(self):
        (self.app / 'T3 Code (Nightly).exe').write_bytes(
            b'dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX' + bytes([1, 9]) + b'101100011')
        windows.check_integrity(self.app)

    def test_missing_stock_record_refuses_marked_installation(self):
        write_asar(self.app / 'resources/app.asar', {
            'package.json': json.dumps({'name': 't3code', 'version': '0.0.46-nightly.1',
                                       't3codeCommitHash': 'abcdef123456'}).encode(),
            'apps/desktop/dist-electron/boot.cjs': windows.MARKER})
        args = type('Args', (), {'command': 'off', 'app': str(self.app)})()
        with patch.object(tool, 'DATA', self.root / 'storage'), patch.object(tool, 'CONFIG', self.root / 'config'):
            with self.assertRaisesRegex(windows.Error, 'no recorded stock backup'):
                windows.dispatch(args, tool)

    def test_windows_node_target(self):
        with patch.object(tool.sys, 'platform', 'win32'), patch.object(tool.host_platform, 'machine', return_value='AMD64'):
            self.assertEqual(tool.node_target(), ('win', 'x64', '.zip'))

    @unittest.skipUnless(sys.platform == 'win32', 'Windows command wrapper')
    def test_cmd_wrapper_preserves_path_and_argument_spaces(self):
        batch = self.root / 'tool with spaces.cmd'
        batch.write_text('@echo off\r\necho %~1\r\nexit /b 7\r\n')
        result = tool.run([str(batch), 'value with spaces'], check=False, capture=True)
        self.assertEqual(result.strip(), 'value with spaces')
        with self.assertRaisesRegex(tool.Stop, r'\(7\)'):
            tool.run([str(batch), 'value with spaces'], capture=True)

    def test_cli_help_starts_without_unix_modules(self):
        result = subprocess.run([sys.executable, str(REPO / 't3code-customize'), 'install', '--help'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--build-only', result.stdout)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows logging handles')
    def test_build_log_drains_both_streams_without_losing_output(self):
        log = self.root / 'build.log'
        with log.open('w', encoding='utf-8') as output:
            tool.run(['node', '-e', "for(let i=0;i<64;i++){console.log('O'.repeat(4096));console.error('E'.repeat(4096));}"], log=output)
        contents = log.read_text(encoding='utf-8')
        self.assertEqual(contents.count('O'), 64 * 4096)
        self.assertEqual(contents.count('E'), 64 * 4096)

    def test_cleanup_rejects_paths_outside_owned_directory(self):
        with self.assertRaisesRegex(windows.Error, 'outside'):
            windows.remove_owned(self.app, self.data)
        self.assertTrue(self.app.exists())

    def test_restore_is_idempotent_and_prepared_build_can_be_reapplied(self):
        stage, manifest = self.prepared()
        with patch.object(windows, 'assert_closed'):
            windows.replace(self.app, self.data, stage, manifest)
            windows.restore(self.app, self.data)
            windows.restore(self.app, self.data)
            self.assertEqual(windows.fingerprint(self.app), self.original)
            windows.replace(self.app, self.data, stage, manifest)
        self.assertEqual(windows.fingerprint(self.app), windows.expected_custom(manifest))

    def test_recovery_does_not_overwrite_unknown_interrupted_changes(self):
        stage, manifest = self.prepared()
        actual = windows.copy_atomic
        count = 0
        def fail_second(source, destination):
            nonlocal count
            if destination.parent == self.app / 'resources':
                count += 1
                if count == 2:
                    raise OSError('interrupted')
            actual(source, destination)
        with patch.object(windows, 'assert_closed'), patch.object(windows, 'copy_atomic', fail_second):
            with self.assertRaises(OSError):
                windows.replace(self.app, self.data, stage, manifest)
        (self.app / 'resources/server.asar').write_bytes(b'unknown external change')
        with patch.object(windows, 'assert_closed'), self.assertRaisesRegex(windows.Error, 'Unknown'):
            windows.recover(self.app, self.data)
        self.assertTrue((self.data / 'transaction.json').is_file())

    def test_rebuilding_without_wsl_stops_before_touching_the_app(self):
        args = type('Args', (), {})()
        with patch.object(windows.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(windows.Error, 'require WSL'):
                windows.build_with_wsl(args, tool, self.root, self.original, {}, None)
        self.assertEqual(windows.fingerprint(self.app), self.original)

    def test_wsl_build_result_must_match_the_verified_source_commit(self):
        source = self.root / 'source'
        source.mkdir()
        args = type('Args', (), {'resume': False, 'wsl_distro': 'Ubuntu'})()
        def fake_build(*args, **kwargs):
            tool.save(source / 'wsl-build-result.json', {'head': 'wrong-source'})
        with (self.root / 'log.txt').open('w') as log:
            with patch.object(tool, 'SOURCE', source), patch.object(tool, 'ensure_commit', return_value='target'), \
                    patch.object(tool, 'prepare'), patch.object(tool, 'git', return_value='verified-head'), \
                    patch.object(tool, 'run', side_effect=fake_build), \
                    patch.object(windows.shutil, 'which', return_value='wsl.exe'), \
                    patch.object(windows.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '/mnt/c/path with spaces\n', '')):
                with self.assertRaisesRegex(windows.Error, 'Source changed'):
                    windows.build_with_wsl(args, tool, self.root, self.original, {}, log)
        self.assertEqual(windows.fingerprint(self.app), self.original)

    def bundle(self, entries=None, **changes):
        entries = entries or {'apps/server/dist/bin.mjs': b'checked server'}
        manifest = {'target': 'abcdef123456', 'version': self.original['metadata']['version'],
                    'recipe': 'recipe', 'checksPassed': True,
                    'files': {name: hashlib.sha256(data).hexdigest() for name, data in entries.items()}}
        manifest.update(changes)
        path = self.root / 'bundles.zip'
        with zipfile.ZipFile(path, 'w') as bundle:
            for name, data in entries.items():
                bundle.writestr(name, data)
            bundle.writestr('bundle-manifest.json', json.dumps(manifest))
        return path

    def test_checked_portable_bundle_is_bound_to_installed_version_and_recipe(self):
        path = self.bundle()
        output = self.root / 'output'
        windows.import_bundles(path, output, self.original, 'recipe', 'abcdef123456')
        self.assertEqual((output / 'apps/server/dist/bin.mjs').read_bytes(), b'checked server')
        with self.assertRaisesRegex(windows.Error, 'do not match'):
            windows.import_bundles(path, self.root / 'wrong', self.original, 'different-recipe', 'abcdef123456')
        self.assertFalse((self.root / 'wrong').exists())

    def test_unchecked_portable_bundle_is_refused(self):
        path = self.bundle(checksPassed=False)
        with self.assertRaisesRegex(windows.Error, 'passed checks'):
            windows.import_bundles(path, self.root / 'output', self.original, 'recipe', 'abcdef123456')

    def test_portable_traversal_is_rejected_before_any_writes(self):
        path = self.bundle({'apps/server/dist/bin.mjs': b'server',
                            'apps/server/dist/../../../../escaped.txt': b'unsafe'})
        with self.assertRaisesRegex(windows.Error, 'Unsafe'):
            windows.import_bundles(path, self.root / 'output', self.original, 'recipe', 'abcdef123456')
        self.assertFalse((self.root / 'output').exists())

    def test_portable_checksum_mismatch_is_refused(self):
        path = self.bundle(files={'apps/server/dist/bin.mjs': 'wrong-hash'})
        with self.assertRaisesRegex(windows.Error, 'checksum'):
            windows.import_bundles(path, self.root / 'output', self.original, 'recipe', 'abcdef123456')
        self.assertFalse((self.root / 'output').exists())

    def test_source_edits_during_checks_never_create_a_validation_cache(self):
        source = self.root / 'source'
        for name in tool.load(REPO / 'checks.json')['tests']:
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('')
        (source / 'pnpm-lock.yaml').write_text('lock')
        dirty = False
        def fake_git(*args):
            if args[0] == 'rev-parse':
                return 'source-head'
            return ' M source.ts' if dirty else ''
        def fake_check(*args, **kwargs):
            nonlocal dirty
            dirty = True
            return subprocess.CompletedProcess([], 0)
        with patch.object(tool, 'SOURCE', source), patch.object(tool, 'CACHE', self.root / 'cache'), \
                patch.object(tool, 'git', side_effect=fake_git), patch.object(tool, 'pnpm', return_value=['pnpm']), \
                patch.object(tool, 'run', side_effect=fake_check):
            with self.assertRaisesRegex(tool.Stop, 'changed during verification'):
                tool.checks({}, None)
        self.assertFalse((self.root / 'cache/checks/source-head.json').exists())

    def test_browser_checks_use_web_project_and_keep_every_required_test(self):
        source = self.root / 'source'
        spec = tool.load(REPO / 'checks.json')
        for name in spec['tests']:
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('')
        (source / 'pnpm-lock.yaml').write_text('lock')
        def fake_git(*args):
            return 'source-head' if args[0] == 'rev-parse' else ''
        with patch.object(tool, 'SOURCE', source), patch.object(tool, 'CACHE', self.root / 'cache'), \
                patch.object(tool, 'git', side_effect=fake_git), \
                patch.object(tool, 'pnpm', return_value=['pnpm']), \
                patch.object(tool, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            tool.checks({}, None)
        seen = []
        for call in run.call_args_list:
            args = call.args[0]
            if args[:3] != ['vp', 'test', 'run']:
                continue
            cwd = call.kwargs['cwd']
            for name in args[3:]:
                seen.append((cwd / name).relative_to(source).as_posix())
                if '.browser.test.' in name:
                    self.assertEqual(cwd, source / 'apps/web')
        self.assertCountEqual(seen, spec['tests'])



if __name__ == '__main__':
    unittest.main()
