"""Build platform-neutral Windows app JavaScript in the installed WSL distro.

The native Windows Vite toolchain can crash V8. This keeps dependency installs
and compilation on the Linux filesystem, then returns only verified JS outputs.
"""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    repo, windows_source, head, stock, version, config_file, log_file = sys.argv[1:]
    loader = importlib.machinery.SourceFileLoader('wsl_customize', str(Path(repo) / 't3code-customize'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    tool = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = tool
    loader.exec_module(tool)
    destination = Path(windows_source)
    tool.CACHE = Path.home() / '.cache/t3code-customize/windows-build'
    tool.SOURCE = tool.CACHE / 'source'
    # Do not accidentally run inherited Windows Node/npm shims from WSL.
    os.environ['PATH'] = ':'.join(p for p in os.environ['PATH'].split(':') if not p.startswith('/mnt/'))
    with Path(log_file).open('a', encoding='utf-8') as log:
        if not (tool.SOURCE / '.git').exists():
            tool.SOURCE.parent.mkdir(parents=True, exist_ok=True)
            tool.run(['git', 'clone', '--shared', '--no-checkout', windows_source, str(tool.SOURCE)], log=log)
        elif tool.git('status', '--porcelain', '--untracked-files=no').strip():
            raise tool.Stop('The WSL build checkout has uncommitted changes; preserving it.')
        tool.git('fetch', '--quiet', 'origin', head, capture=False, log=log)
        tool.git('checkout', '--quiet', '--detach', head, capture=False, log=log)
        env = tool.build_env(tool.ensure_node(log))
        # Stay within the user's existing WSL memory budget; no VM settings change.
        env['NODE_OPTIONS'] = '--max-old-space-size=3072'
        tool.install_dependencies(env, log)
        validated = tool.load(destination.parent / 'checks' / (head + '.json'), {})
        expected = {'head': head, 'spec': tool.sha256(Path(repo) / 'checks.json'),
                    'lock': tool.sha256(tool.SOURCE / 'pnpm-lock.yaml'), 'platform': 'win32'}
        if validated == expected:
            tool.say('Using passed Windows patch tests/typechecks for this exact source commit and lockfile.')
        else:
            tool.checks(env, log)
        tool.build_bundles(env, version, Path(stock), tool.load(Path(config_file)), log, target_platform='win32')
        if tool.git('rev-parse', 'HEAD').strip() != head or tool.git('status', '--porcelain', '--untracked-files=no').strip():
            raise tool.Stop('The WSL source checkout changed during verification/build.')
        for relative in ('apps/server/dist', 'apps/desktop/dist-electron'):
            target = destination / relative
            if not target.resolve().is_relative_to(destination.resolve()):
                raise tool.Stop('Refusing a redirected build output directory.')
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(tool.SOURCE / relative, target)
        tool.save(destination / 'wsl-build-result.json', {'head': head, 'node': tool.run(
            ['node', '-p', 'process.versions.node'], env=env, capture=True).strip()})
    tool.say('WSL checks and JavaScript build completed.')


if __name__ == '__main__':
    main()
