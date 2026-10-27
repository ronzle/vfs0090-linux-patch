# SPDX-License-Identifier: LGPL-2.1-or-later
"""Exercise configuration validation, rollback and narrow VM cleanup."""
from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


manage = load('manage')
windows = load('windows_cleanup')


class ConfigurationTests(unittest.TestCase):
    def identity(self, value):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pairing.json'
            path.write_text(json.dumps(value))
            return manage.load_identity(path)

    def test_pairing_preserves_spaces(self):
        data = {'product_name': 'Standard PC (Q35 + ICH9, 2009)', 'product_serial': 'EXAMPLE-123'}
        self.assertEqual(self.identity(data), data)
        self.assertIn(data['product_name'], manage.dropin(data).decode())

    def test_pairing_rejects_placeholder_and_control_characters(self):
        for serial in ('', 'REPLACE_WITH_SERIAL', 'x\ny', 'x\x00y', ' x', 'x' * 255):
            with self.subTest(serial=repr(serial)), self.assertRaises(ValueError):
                self.identity({'product_name': 'Example', 'product_serial': serial})

    def test_systemd_escaping(self):
        self.assertEqual(manage.systemd_quote('a"b\\c%d'), '"a\\"b\\\\c%%d"')

    def test_pam_is_idempotent_and_preserves_password_path(self):
        original = b'# pam_fprintd.so is not enabled\nauth required pam_unix.so\n'
        changed = manage.add_fingerprint_pam(original)
        self.assertTrue(changed.endswith(original))
        self.assertEqual(changed.count(b'auth sufficient pam_fprintd.so'), 1)
        self.assertEqual(manage.add_fingerprint_pam(changed), changed)


class RollbackTests(unittest.TestCase):
    def test_exact_content_and_permissions_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / 'backup'
            backup.mkdir()
            existing = root / 'original'
            existing.write_bytes(b'original\x00bytes')
            existing.chmod(0o640)
            created = root / 'new'
            tx = manage.FileTransaction(backup)
            tx.write(existing, b'replacement', 0o755)
            tx.write(created, b'new data')
            tx.rollback()
            self.assertEqual(existing.read_bytes(), b'original\x00bytes')
            self.assertEqual(existing.stat().st_mode & 0o777, 0o640)
            self.assertFalse(created.exists())

    def test_symlink_refused_without_touching_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'target'
            target.write_text('keep')
            link = root / 'link'
            link.symlink_to(target)
            tx = manage.FileTransaction(root)
            with self.assertRaises(ValueError):
                tx.write(link, b'change')
            self.assertEqual(target.read_text(), 'keep')


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.lib = self.root / 'lib/driver.so'
        self.conf = self.root / 'systemd/driver.conf'
        self.state = self.root / 'state/state.json'
        for key, value in [('LIB', self.lib), ('CONF', self.conf),
                           ('STATE', self.state), ('BACKUPS', self.root / 'backups')]:
            self.stack.enter_context(mock.patch.object(manage, key, value))
        self.stack.enter_context(mock.patch.object(manage, 'require_host'))
        self.stack.enter_context(mock.patch.object(manage, 'planned_files', return_value=[
            (self.lib, b'new-library', 0o755), (self.conf, b'new-config', 0o644)]))
        self.stack.enter_context(mock.patch.object(manage.subprocess, 'run',
                                                  return_value=SimpleNamespace(returncode=0)))
        self.commands = self.stack.enter_context(mock.patch.object(manage, 'run'))
        self.args = SimpleNamespace(pairing=self.root / 'identity.json', enable_pam=False, apply=True)

    def test_dry_run_does_not_write_or_call_systemctl(self):
        self.args.apply = False
        manage.install(self.args)
        self.commands.assert_not_called()
        self.assertFalse(self.state.exists())
        self.assertFalse(self.lib.exists())

    def test_sensor_failure_restores_previous_files(self):
        self.lib.parent.mkdir()
        self.lib.write_bytes(b'old-library')
        self.lib.chmod(0o750)
        def fail_sensor(*args, **kwargs):
            if args[0] == 'python3':
                raise RuntimeError('simulated sensor open failure')
        self.commands.side_effect = fail_sensor
        with self.assertRaisesRegex(RuntimeError, 'sensor open'):
            manage.install(self.args)
        self.assertEqual(self.lib.read_bytes(), b'old-library')
        self.assertEqual(self.lib.stat().st_mode & 0o777, 0o750)
        self.assertFalse(self.conf.exists())
        self.assertFalse(self.state.exists())

    def test_install_idempotence_and_uninstall(self):
        manage.install(self.args)
        self.assertTrue(self.state.exists())
        self.commands.reset_mock()
        manage.install(self.args)
        self.commands.assert_not_called()
        manage.uninstall(self.args)
        self.assertFalse(self.lib.exists())
        self.assertFalse(self.conf.exists())
        self.assertFalse(self.state.exists())

    def test_uninstall_refuses_modified_files(self):
        manage.install(self.args)
        self.conf.write_bytes(b'edited-by-user')
        self.commands.reset_mock()
        with self.assertRaisesRegex(ValueError, 'changed since installation'):
            manage.uninstall(self.args)
        self.commands.assert_not_called()
        self.assertEqual(self.conf.read_bytes(), b'edited-by-user')


class WindowsTests(unittest.TestCase):
    fixture = ('services:\n  windows:\n    environment:\n'
               '      PASSWORD: "test-placeholder"\n'
               '      ARGUMENTS: "-rtc base=localtime -device usb-host,vendorid=0x138a,productid=0x0090"\n'
               '    device_cgroup_rules:\n      - "c 189:* rwm"\n'
               '    volumes:\n      - /dev/bus/usb:/dev/bus/usb\n      - /example/storage:/storage\n')

    def test_only_known_passthrough_removed(self):
        result = windows.clean_compose(self.fixture)
        self.assertNotIn('usb-host', result)
        self.assertNotIn('/dev/bus/usb', result)
        self.assertNotIn('189:', result)
        self.assertIn('PASSWORD: "test-placeholder"', result)
        self.assertIn('/example/storage:/storage', result)
        self.assertIn('-rtc base=localtime', result)
        self.assertEqual(windows.clean_compose(result), result)

    def test_unexpected_passthrough_fails_closed(self):
        for extra in ('      - /dev/bus/usb:/different\n', '      - "c 189:1 rw"\n',
                      '      EXTRA: "-device usb-host,vendorid=0x1234"\n'):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                windows.clean_compose(self.fixture + extra)

    def test_running_or_stale_container_is_not_detached(self):
        data = {'State': {'Running': False}, 'Config': {'Env': []}, 'HostConfig': {}, 'Mounts': []}
        self.assertTrue(windows.detached(data))
        data['State']['Running'] = True
        self.assertFalse(windows.detached(data))
        data['State']['Running'] = False
        data['HostConfig']['DeviceCgroupRules'] = ['c 189:* rwm']
        self.assertFalse(windows.detached(data))


if __name__ == '__main__':
    unittest.main()
