# VFS0090 Linux repair

Patches and recovery tools for the **Validity `138a:0090` fingerprint sensor**, tested on a **ThinkPad T460s running Omarchy/Arch Linux**.

This project addresses three problems encountered with the community libfprint driver:

1. A sensor paired inside a Windows VM needs that VM's product name and serial number when Linux opens it.
2. A missing `config.h` include silently disables the intended image scaling and can produce unusable fingerprint templates.
3. Cancelling verification can tear down NSS or start deactivation while a delayed scan operation is still running, causing USB timeouts or a crash.

The repository contains a patch series and scripts, not a replacement firmware or a new implementation of the driver. **The sensor must already be initialized and paired.** A BIOS fingerprint reset, factory reset or replacement sensor can invalidate that pairing. These tools do not reset or initialize it.

## Status and scope

| Component | Validation |
| --- | --- |
| Enrollment and verification | Successful on the test T460s |
| sudo, screen unlock, resume from suspend | Confirmed on the test system |
| 1Password system authentication and browser passkeys | Confirmed on the test system |
| Cancellation | 16 timed hardware cancellations, plus cancellation immediately after a successful match; close/reopen passed |
| libfprint unit tests | All three enabled unit suites passed |
| Public management scripts | Unit-tested, including rollback and refusal of unexpected configuration |

This is a community repair for one tested hardware/software combination, not an official Lenovo, Omarchy or libfprint release. Other sensors, distributions and PAM stacks are not validated. The public installer has not been applied over the original private recovery installation; the tested driver changes are the same.

The driver still depends on **OpenSSL 1.1**, an obsolete dependency inherited from this driver version. No OpenSSL binaries or automatic dependency installers are included. Review how you obtain and maintain that dependency before using this project.

## Build

Use an ordinary user account. On an up-to-date Arch/Omarchy installation, install the build and runtime dependencies:

```sh
sudo pacman -S --needed base-devel git meson ninja pkgconf glib2-devel libgusb pixman nss fprintd python-gobject
```

Install OpenSSL 1.1 headers, libraries and pkg-config files separately from a source you trust. The build expects Arch's usual `/usr/lib/openssl-1.1/pkgconfig` layout; it refuses OpenSSL 3.x. It does not replace the system OpenSSL.

```sh
python3 scripts/build.py
```

The build checks out exact upstream commits from `upstream.json`, applies the patches, runs the three libfprint unit suites and stages the library with its build-directory search path removed. Output is written to ignored `build/` and `dist/` directories. A second build requires moving or removing `build/` first.

For a different OpenSSL 1.1 installation:

```sh
python3 scripts/build.py --openssl-pc-dir /path/to/openssl11/lib/pkgconfig
```

The corresponding `libcrypto.so.1.1` must also be discoverable by the runtime linker. `--libfprint-url` and `--driver-url` accept local Git caches for offline builds; the pinned commits are still checked. `--native-file` is available for a custom Meson toolchain.

## Configure the pairing identity

```sh
mkdir -p local
cp examples/pairing.example.json local/pairing.json
```

Edit `local/pairing.json` with the **product name and serial number used when the sensor was paired**. The example QEMU product name is not universal. Do not guess the serial number or substitute the USB sensor serial.

If pairing happened on the physical machine, these may be the machine's DMI values. If it happened in a VM, use the guest's values. See [pairing notes](docs/pairing.md). `local/` and files named `pairing.json` are ignored by Git.

## Install

Stop any VM with access to the fingerprint sensor. Review the installation plan first:

```sh
python3 scripts/manage.py install --pairing local/pairing.json
sudo python3 scripts/manage.py install --pairing local/pairing.json --apply
```

The installer checks the sensor, artifact checksums, dependencies and conflicting driver overrides. It then:

- installs the library under `/usr/local/lib/vfs0090-linux-repair/`;
- adds a **fprintd-only** systemd override with the pairing identity and library path;
- restarts fprintd and opens/releases the sensor without enrollment;
- records previous file contents and permissions for rollback and uninstall.

The packaged `/usr/lib/libfprint*` files remain untouched. No firmware or biometric templates are included or changed. Backups are stored in restricted directories under `/var/backups/vfs0090-linux-repair/`.

For the current Omarchy shell, opt in to PAM integration with `--enable-pam` on both commands. This adds fingerprint authentication to `sudo` and `polkit-1` if it is absent, and creates the fingerprint-specific Omarchy lock service if needed. Existing password authentication stays in place. Other desktop/PAM configurations require manual integration.

**Migrating from the private recovery kit:** its override is deliberately detected as a conflict. Do not stack both installations. Back up and remove its `90-vfs0090-vm-pairing.conf` override before applying this installer. Keep the old recovery kit available for rollback. This repository does not modify that private installation during preparation.

## Enroll and test

Run these from your normal user session:

```sh
sudo fprintd-enroll -f right-index-finger "$USER"
fprintd-verify -f right-index-finger
```

Expect `enroll-completed` and `verify-match`. If you enrolled before applying the image-scaling fix, enroll that finger again. The matching threshold is unchanged.

With PAM integration enabled:

```sh
sudo -k
sudo true
omarchy system lock
```

Test suspend/resume separately. The current Omarchy lock screen detects enrolled fingerprints automatically. This project does not change display-manager autologin, cold-boot login or disk encryption.

## 1Password and passkeys

Enable **Settings → Security → Unlock using system authentication** in the 1Password desktop app. Lock it, unlock once with the account password, then test the fingerprint button. After fully restarting the app, the account password is needed first.

Enable the desktop/browser connection in both the app and extension. The fingerprint unlocks 1Password; **1Password stores and uses the passkey**. The sensor itself is not a FIDO2 security key.

If system-authentication requests silently fail while fingerprint verification works, check that a Polkit agent is registered. On the tested system, restarting the unlocked Omarchy shell with `omarchy restart shell` restored its agent after a registration conflict.

Official references:

- [System authentication on Linux](https://support.1password.com/system-authentication-linux/)
- [Connect the browser extension and desktop app](https://support.1password.com/connect-1password-browser-app/)
- [Save and use passkeys](https://support.1password.com/save-use-passkeys/)

## Detach the Windows VM

The optional helper understands only the specific Omarchy/dockurr passthrough recipe described in [Windows cleanup](docs/windows-cleanup.md). It refuses unrecognized USB configurations rather than guessing.

```sh
sudo python3 scripts/windows_cleanup.py
sudo python3 scripts/windows_cleanup.py --apply
```

The first command is a read-only plan; root may be needed to read the Compose file. Applying it removes the sensor argument and associated USB mount/cgroup rule, stops the container and recreates it **without starting or pulling an image**. Existing VM storage remains intact. The Windows driver can remain installed because it can no longer access the sensor.

## Uninstall and updates

```sh
sudo python3 scripts/manage.py uninstall
sudo python3 scripts/manage.py uninstall --apply
```

Uninstall restores saved pre-installation files and refuses to overwrite files edited since installation. Backups and enrolled fingerprints are retained. The original driver may not open the paired sensor afterward.

The private driver is not updated by the distribution package manager. Recheck compatibility after major fprintd/libfprint updates. To install a different build, uninstall the managed version first, rebuild, then install again. Reapplying an identical installation is a no-op.

Normal USB reset messages can appear when this driver opens the sensor. A segfault or repeated transfer timeout is not considered normal; see [troubleshooting](docs/troubleshooting.md).

## Development

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q scripts tests
```

GitHub Actions runs the management-script tests. It does not claim hardware coverage or build the legacy OpenSSL dependency. See [patch design and validation](docs/patches.md) for the driver-level changes and manual regression checks.

## License and credits

LGPL-2.1-or-later; see [LICENSE](LICENSE) and [NOTICE](NOTICE). The patches modify the existing community driver. Its original authors and contributors retain their attribution. No Windows installers, firmware, built libraries, device identities, fingerprint templates or crash dumps are distributed here.
