#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Plan or apply an isolated fprintd driver installation on Arch/Omarchy."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LIB = Path('/usr/local/lib/vfs0090-linux-repair/libfprint-2.so.2')
CONF = Path('/etc/systemd/system/fprintd.service.d/90-vfs0090-linux-repair.conf')
STATE = Path('/var/lib/vfs0090-linux-repair/state.json')
BACKUPS = Path('/var/backups/vfs0090-linux-repair')
PAM_FILES = {Path('/etc/pam.d/sudo'), Path('/etc/pam.d/polkit-1'),
             Path('/etc/pam.d/omarchy-lock-fingerprint')}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def atomic_write(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_identity(path):
    identity = json.loads(path.read_text())
    if set(identity) != {'product_name', 'product_serial'}:
        raise ValueError('Pairing configuration must contain product_name and product_serial only')
    for value in identity.values():
        if not isinstance(value, str) or not value.strip() or len(value) > 254:
            raise ValueError('Pairing values must be nonempty strings of at most 254 characters')
        if any(ord(char) < 32 or ord(char) > 126 for char in value):
            raise ValueError('Pairing values must contain printable ASCII characters only')
        if value != value.strip() or value.startswith('REPLACE_'):
            raise ValueError('Replace the example values with the exact pairing identity')
    return identity


def systemd_quote(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def dropin(identity):
    values = {'LD_LIBRARY_PATH': str(LIB.parent),
              'VFS0090_PRODUCT_NAME': identity['product_name'],
              'VFS0090_PRODUCT_SERIAL': identity['product_serial']}
    return ('[Service]\n' + ''.join('Environment=' + systemd_quote(k + '=' + v) + '\n'
                                   for k, v in values.items())).encode()


def add_fingerprint_pam(data):
    text = data.decode()
    if any('pam_fprintd.so' in line and not line.lstrip().startswith('#')
           for line in text.splitlines()):
        return data
    return b'auth sufficient pam_fprintd.so\n' + data


class FileTransaction:
    """Keep exact file contents/modes for rollback, refusing symbolic links."""
    def __init__(self, backup):
        self.backup = backup
        self.entries = []

    def write(self, path, data, mode=0o644):
        if path.is_symlink():
            raise ValueError(f'Refusing to replace a symbolic link: {path}')
        entry = {'path': str(path), 'existed': path.exists(), 'installed_sha256': digest(data)}
        if path.exists():
            if not path.is_file():
                raise ValueError(f'Expected a regular file: {path}')
            entry['mode'] = path.stat().st_mode & 0o777
            entry['backup'] = str(len(self.entries))
            shutil.copy2(path, self.backup / entry['backup'])
        self.entries.append(entry)
        atomic_write(path, data, mode)

    def rollback(self):
        restore_entries(self.entries, self.backup)


def restore_entries(entries, backup):
    for entry in reversed(entries):
        path = Path(entry['path'])
        if entry['existed']:
            atomic_write(path, (backup / entry['backup']).read_bytes(), entry['mode'])
        else:
            path.unlink(missing_ok=True)


def planned_files(pairing, enable_pam):
    identity = load_identity(pairing)
    artifact = ROOT / 'dist/libfprint-2.so.2.0.0'
    manifest = json.loads((ROOT / 'dist/build.json').read_text())
    if digest(artifact.read_bytes()) != manifest['sha256']:
        raise ValueError('Driver checksum does not match dist/build.json; rebuild it')
    if manifest['upstream'] != json.loads((ROOT / 'upstream.json').read_text()):
        raise ValueError('Built upstream revisions do not match this checkout')
    expected = {p.name: digest(p.read_bytes()) for p in (ROOT / 'patches').glob('*.patch')}
    if manifest['patches'] != expected:
        raise ValueError('Patches changed since the last build; rebuild it')
    files = [(LIB, artifact.read_bytes(), 0o755), (CONF, dropin(identity), 0o644)]
    if enable_pam:
        if not Path('/etc/pam.d/omarchy-lock-password').is_file():
            raise ValueError('--enable-pam supports the current Omarchy shell only')
        for path in sorted(PAM_FILES):
            if path.name == 'omarchy-lock-fingerprint':
                if not path.exists():
                    files.append((path, b'#%PAM-1.0\nauth required pam_fprintd.so\n'
                                  b'account include system-local-login\n', 0o644))
            else:
                old = path.read_bytes()
                new = add_fingerprint_pam(old)
                if old != new:
                    files.append((path, new, path.stat().st_mode & 0o777))
    return files


def require_host():
    if not Path('/usr/lib/fprintd').is_file():
        raise ValueError('Install fprintd first; see README.md')
    found = False
    for device in Path('/sys/bus/usb/devices').iterdir():
        try:
            found |= ((device / 'idVendor').read_text().strip() == '138a' and
                      (device / 'idProduct').read_text().strip() == '0090')
        except FileNotFoundError:
            continue
    if not found:
        raise ValueError('No 138a:0090 sensor detected')
    for base in ('/etc', '/run', '/usr/lib'):
        for path in (Path(base) / 'systemd/system/fprintd.service.d').glob('*.conf'):
            if path != CONF and 'LD_LIBRARY_PATH' in path.read_text():
                raise ValueError(f'Another driver override exists: {path}; see migration notes')
    enabled = subprocess.run(['systemctl', 'is-enabled', 'fprintd.service'], capture_output=True, text=True)
    if enabled.stdout.strip().startswith('masked'):
        raise ValueError('fprintd is masked; resolve that explicitly before installation')
    dependencies = run('ldd', str(ROOT / 'dist/libfprint-2.so.2.0.0'),
                       capture_output=True, text=True).stdout
    if 'not found' in dependencies:
        raise ValueError('Missing runtime libraries:\n' + dependencies)


def install(args):
    files = planned_files(args.pairing, args.enable_pam)
    print('Install the private VFS0090 library and fprintd-only override.')
    for path, _, _ in files:
        print(f'  {path}')
    if not args.apply:
        print('Plan only. Repeat with sudo and --apply to install.')
        return
    if STATE.exists():
        state = json.loads(STATE.read_text())
        baseline = {entry['path']: entry for entry in state['entries']}
        same = all(path.is_file() and not path.is_symlink() and digest(path.read_bytes()) == digest(data)
                   and str(path) in baseline and baseline[str(path)]['installed_sha256'] == digest(data)
                   for path, data, _ in files)
        if same:
            print('This build/configuration is already installed. No files changed.')
            return
        raise ValueError('A different installation is managed here; uninstall it before replacing it')
    require_host()
    backup = BACKUPS / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    backup.mkdir(parents=True, mode=0o700)
    tx = FileTransaction(backup)
    was_active = subprocess.run(['systemctl', 'is-active', '--quiet', 'fprintd.service']).returncode == 0
    run('systemctl', 'stop', 'fprintd.service')
    try:
        for path, data, mode in files:
            tx.write(path, data, mode)
        run('systemctl', 'daemon-reload')
        run('systemctl', 'start', 'fprintd.service')
        run('python3', str(ROOT / 'scripts/check_sensor.py'))
        atomic_write(STATE, json.dumps({'backup': str(backup), 'entries': tx.entries}, indent=2).encode(), 0o600)
    except Exception:
        subprocess.run(['systemctl', 'stop', 'fprintd.service'])
        tx.rollback()
        run('systemctl', 'daemon-reload')
        if was_active:
            run('systemctl', 'start', 'fprintd.service')
        raise
    print(f'Installed; previous files saved in {backup}')
    print('Enroll as your normal user: sudo fprintd-enroll -f right-index-finger "$USER"')


def uninstall(args):
    if not STATE.exists():
        print('No managed installation found.')
        return
    state = json.loads(STATE.read_text())
    allowed = {LIB, CONF} | PAM_FILES
    for entry in state['entries']:
        path = Path(entry['path'])
        if path not in allowed or path.is_symlink() or not path.is_file():
            raise ValueError(f'Unexpected or missing managed file: {path}')
        if digest(path.read_bytes()) != entry['installed_sha256']:
            raise ValueError(f'File changed since installation; refusing to overwrite it: {path}')
    backup = Path(state['backup'])
    if backup.parent != BACKUPS or backup.is_symlink():
        raise ValueError('Invalid backup location')
    for entry in state['entries']:
        if entry['existed'] and (not str(entry['backup']).isdigit() or not (backup / entry['backup']).is_file()):
            raise ValueError('Missing or invalid backup')
    print('Restore all managed files to their pre-installation contents. Fingerprints are preserved.')
    if not args.apply:
        print('Plan only. Repeat with sudo and --apply to uninstall.')
        return
    run('systemctl', 'stop', 'fprintd.service')
    restore_entries(state['entries'], backup)
    run('systemctl', 'daemon-reload')
    run('systemctl', 'start', 'fprintd.service')
    STATE.unlink()
    print('Previous configuration restored. Backups retained.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    inst = commands.add_parser('install')
    inst.add_argument('--pairing', type=Path, required=True)
    inst.add_argument('--enable-pam', action='store_true', help='Opt in to sudo/polkit/Omarchy PAM integration')
    inst.add_argument('--apply', action='store_true')
    uninst = commands.add_parser('uninstall')
    uninst.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.apply and os.geteuid() != 0:
        parser.error('Run apply operations with sudo.')
    try:
        (install if args.command == 'install' else uninstall)(args)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Error: {error}\n')


if __name__ == '__main__':
    main()
