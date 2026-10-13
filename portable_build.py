"""Produce checked, source-bound JavaScript bundles for a Windows installation."""
import argparse
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{7,40}', args.commit):
        parser.error('commit must be a Git commit hash')
    repo = Path(__file__).resolve().parent
    loader = importlib.machinery.SourceFileLoader('portable_customize', str(repo / 't3code-customize'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    tool = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = tool
    loader.exec_module(tool)
    config = tool.load(args.config)
    if not isinstance(config, dict) or set(config) - set(tool.PUBLIC_CONFIG.values()) or any(
            not isinstance(value, str) or len(value) > 200 for value in config.values()):
        parser.error('config must contain only public T3 Connect build fields')
    tool.CACHE.mkdir(parents=True, exist_ok=True)
    log_path = tool.CACHE / 'portable-build.log'
    with log_path.open('w', encoding='utf-8') as log, tempfile.TemporaryDirectory() as stock:
        target = tool.ensure_commit(args.commit, args.version, log)
        tool.prepare(target, log)
        env = tool.build_env(tool.ensure_node(log))
        tool.install_dependencies(env, log)
        head = tool.git('rev-parse', 'HEAD').strip()
        tool.checks(env, log)
        tool.build_bundles(env, args.version, Path(stock), config, log, target_platform='win32')
        if tool.git('rev-parse', 'HEAD').strip() != head or tool.git('status', '--porcelain', '--untracked-files=no').strip():
            raise tool.Stop('Source changed during the portable build.')
        files = {}
        for prefix in ('apps/server/dist', 'apps/desktop/dist-electron'):
            for path in sorted((tool.SOURCE / prefix).rglob('*')):
                if path.is_symlink():
                    raise tool.Stop('Unexpected symlink in portable output.')
                if path.is_file():
                    files[path.relative_to(tool.SOURCE).as_posix()] = tool.sha256(path)
        manifest = {'target': target, 'version': args.version, 'recipe': tool.recipe_hash(),
                    'head': head, 'checksPassed': True, 'files': files}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix('.new')
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
            for name in files:
                bundle.write(tool.SOURCE / name, name)
            bundle.writestr('bundle-manifest.json', json.dumps(manifest, indent=2))
        temporary.replace(args.output)
    tool.say('Checked Windows JavaScript bundles: ' + str(args.output))


if __name__ == '__main__':
    main()
