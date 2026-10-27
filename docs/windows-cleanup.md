# Removing temporary Windows passthrough

The helper targets an Omarchy-managed `dockurr/windows` container and recognizes
these exact additions to the usual Compose file:

```yaml
      ARGUMENTS: "-rtc base=localtime,clock=host,driftfix=slew -device usb-host,vendorid=0x138a,productid=0x0090"
    device_cgroup_rules:
      - "c 189:* rwm"
    volumes:
      - /dev/bus/usb:/dev/bus/usb
```

It also recognizes the earlier `devices` entry `      - /dev/bus/usb`.
Unrelated settings, including disks, ports and credentials, are preserved.
Other USB passthrough formats or devices cause the helper to stop without edits.
This intentionally narrow text transformation is not a general Compose editor.

Changing the Compose file alone does not update a stopped container's saved
configuration. Applying the helper validates the new Compose file, gracefully
stops a running container and recreates it in a stopped state. It verifies that
USB mounts, host-device arguments and USB cgroup access are absent afterward.

The helper uses the Compose project label from the existing container. Defaults
are `omarchy-windows`, service `windows`, and
`/var/lib/omarchy/windows/docker-compose.yml`. All three can be supplied explicitly
through `--container`, `--service` and `--compose`.

Use a normal single-file Compose setup for this helper. If your setup depends on
additional override files, profiles or an externally supplied environment, review
and recreate it yourself with those same inputs. Stop on validation errors.

A restricted backup of the original Compose file is retained under
`/var/backups/vfs0090-linux-repair/`. It may contain VM credentials and must not be
attached to an issue. If recreation fails, the USB-free configuration is retained
and the helper reports an error; it does not restart the old USB-enabled VM.

No Windows files, fingerprint records or firmware are removed. The disk survives
container recreation. Leaving the Windows driver installed is harmless once
hardware passthrough has been removed.
