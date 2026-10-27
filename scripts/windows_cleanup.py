#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Detach the sensor from the specific dockurr/Omarchy repair configuration."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def clean_compose(text):
    """Recognize only the repair recipe; reject ambiguous USB passthrough."""
    result = text.replace(' -device usb-host,vendorid=0x138a,productid=0x0090', '')
    result = result.replace('      - /dev/bus/usb:/dev/bus/usb\n', '')
    result = result.replace('      - /dev/bus/usb\n', '')
    result = result.replace('    device_cgroup_rules:\n      - "c 189:* rwm"\n', '')
    if any(token in result.lower() for token in ('usb-host', '/dev/bus/usb', '189:', '138a')):
        raise ValueError('Unrecognized USB configuration; review it manually instead')
    return result


def detached(container):
    return (not container['State']['Running']
            and not any('/dev/bus/usb' in mount.get('Source', '') for mount in container.get('Mounts', []))
            and not any('usb-host' in item or '138a' in item.lower()
                        for item in container['Config'].get('Env', []))
            and not any('/dev/bus/usb' in str(item) for item in container['HostConfig'].get('Devices', []))
            and not any('189:' in item for item in container['HostConfig'].get('DeviceCgroupRules') or []))


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compose', type=Path, default=Path('/var/lib/omarchy/windows/docker-compose.yml'))
    parser.add_argument('--container', default='omarchy-windows')
    parser.add_argument('--service', default='windows')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.apply and os.geteuid() != 0:
        parser.error('Run --apply with sudo.')
    path = args.compose.resolve()
    original = path.read_text()
    cleaned = clean_compose(original)
    print('Remove the known sensor USB passthrough; recreate the container in a stopped state.')
    print('The VM disk and unrelated Compose settings are retained.')
    if not args.apply:
        print('Plan only. Repeat with --apply to change the container. No credentials are printed.')
        return
    info = json.loads(run('docker', 'inspect', args.container, capture_output=True, text=True).stdout)[0]
    labels = info['Config'].get('Labels') or {}
    project = labels.get('com.docker.compose.project')
    if not project or labels.get('com.docker.compose.service') != args.service:
        raise ValueError('Container does not belong to the expected Compose service')
    if original == cleaned and detached(info):
        print('Container is already stopped and detached. No changes needed.')
        return
    backup = Path('/var/backups/vfs0090-linux-repair') / ('windows-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))
    backup.mkdir(parents=True, mode=0o700)
    shutil.copy2(path, backup / 'docker-compose.yml')
    fd, name = tempfile.mkstemp(prefix='.fingerprint-compose-', suffix='.yml', dir=path.parent)
    candidate = Path(name)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(cleaned)
        run('docker', 'compose', '-p', project, '-f', str(candidate), 'config', '--quiet')
        if info['State']['Running']:
            run('docker', 'stop', '--time', '120', args.container, stdout=subprocess.DEVNULL)
        os.chmod(candidate, path.stat().st_mode & 0o777)
        os.replace(candidate, path)
        try:
            run('docker', 'compose', '-p', project, '-f', str(path), 'create',
                '--pull', 'never', '--force-recreate', args.service)
        except subprocess.CalledProcessError:
            print(f'Container recreation failed. The USB-free Compose file is retained; backup: {backup}')
            raise
        after = json.loads(run('docker', 'inspect', args.container, capture_output=True, text=True).stdout)[0]
        if not detached(after):
            raise RuntimeError('Container verification failed; inspect its USB configuration manually')
        print(f'Container stopped and detached. Original Compose file: {backup}')
    finally:
        candidate.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'Error: {error}')
