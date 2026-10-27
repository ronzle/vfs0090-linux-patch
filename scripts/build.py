#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Build the pinned VFS0090 driver without modifying the host installation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def checkout(url, commit, destination):
    run('git', 'clone', '--no-checkout', url, str(destination))
    run('git', '-C', str(destination), 'checkout', '--detach', commit)
    actual = subprocess.check_output(['git', '-C', str(destination), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != commit:
        raise RuntimeError('Unexpected upstream revision')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--openssl-pc-dir', default='/usr/lib/openssl-1.1/pkgconfig')
    parser.add_argument('--native-file', type=Path, help='Optional Meson native file')
    parser.add_argument('--libfprint-url', help='Optional local clone/cache; the commit is still checked')
    parser.add_argument('--driver-url', help='Optional local clone/cache; the commit is still checked')
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Build as a regular user, not root.')
    for tool in ('git', 'meson', 'ninja', 'cc', 'pkg-config', 'readelf'):
        if not shutil.which(tool):
            parser.error(f'Missing build tool: {tool}; see README.md')
    work = ROOT / 'build'
    if work.exists():
        parser.error('build/ already exists. Move or remove it before starting a fresh build.')
    env = os.environ.copy()
    env['PKG_CONFIG_PATH'] = str(Path(args.openssl_pc_dir).resolve())
    version = subprocess.check_output(['pkg-config', '--modversion', 'openssl'], env=env, text=True).strip()
    if not version.startswith('1.1.'):
        parser.error(f'OpenSSL 1.1 is required by this driver; pkg-config found {version}')
    refs = json.loads((ROOT / 'upstream.json').read_text())
    work.mkdir()
    source = work / 'libfprint'
    checkout(args.libfprint_url or refs['libfprint']['url'], refs['libfprint']['commit'], source)
    driver = source / 'libfprint/drivers/vfs0090'
    if driver.exists():
        driver.rmdir()  # A fresh checkout contains an empty submodule directory.
    checkout(args.driver_url or refs['vfs0090']['url'], refs['vfs0090']['commit'], driver)
    for patch in sorted((ROOT / 'patches').glob('*.patch')):
        target = source if patch.name.startswith('0000') else driver
        run('git', '-C', str(target), 'apply', '--check', str(patch))
        run('git', '-C', str(target), 'apply', str(patch))
    out = work / 'meson'
    native = ['--native-file', str(args.native_file.resolve())] if args.native_file else []
    run('meson', 'setup', str(out), str(source), *native,
        '-Ddrivers=vfs0090', '-Dintrospection=false', '-Ddoc=false',
        '-Dinstalled-tests=false', '-Dudev_rules=disabled', '-Dudev_hwdb=disabled', env=env)
    run('meson', 'compile', '-C', str(out), env=env)
    run('meson', 'test', '-C', str(out), '--suite', 'unit-tests', '--print-errorlogs', env=env)
    stage = work / 'stage'
    run('meson', 'install', '-C', str(out), '--destdir', str(stage), '--no-rebuild', env=env)
    matches = list(stage.rglob('libfprint-2.so.2.0.0'))
    if len(matches) != 1:
        raise RuntimeError('Expected exactly one staged driver library')
    dynamic = subprocess.check_output(['readelf', '-d', str(matches[0])], text=True)
    if '(RPATH)' in dynamic or '(RUNPATH)' in dynamic:
        raise RuntimeError('Refusing a library with a build-directory runtime search path')
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    artifact = dist / matches[0].name
    shutil.copy2(matches[0], artifact)
    (dist / 'build.json').write_text(json.dumps({
        'upstream': refs, 'openssl': version,
        'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest(),
        'patches': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted((ROOT / 'patches').glob('*.patch'))}
    }, indent=2) + '\n')
    print('Build and unit tests passed. Artifact: dist/libfprint-2.so.2.0.0')


if __name__ == '__main__':
    main()
