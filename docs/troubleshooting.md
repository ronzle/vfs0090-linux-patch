# Troubleshooting

## Sensor opens, but enrollment is denied

If Polkit cannot display an authentication challenge, enrollment may fail even
though verification is allowed. From your normal terminal session, use:

```sh
sudo fprintd-enroll -f right-index-finger "$USER"
```

Do not omit the username when running enrollment as root, or you may enroll for
the root account. Do not add broad Polkit allow rules to work around a missing
agent. On Omarchy, an unlocked shell restart can restore a failed agent.

## ECDSA key generation fails

Check the pairing identity. The product name and BIOS serial used by the VM can
differ from those of the physical laptop. Do not reset the sensor as a first
troubleshooting step; this repository cannot recreate its pairing.

## Verification always returns no-match

Re-enroll after the image-scaling patch. Compare the same finger, position and
contact. A successful scan alone does not establish a successful match.

## USB resets, timeouts or crashes

The driver explicitly resets the USB connection when initializing the device.
That reset is not a factory reset and does not erase fingerprints. Repeated
transfer timeouts, segfaults or failures to reopen the device still deserve
investigation.

Useful read-only checks:

```sh
journalctl -u fprintd.service --since '10 minutes ago' --no-pager
coredumpctl list /usr/lib/fprintd
```

Never publish a raw core dump, fingerprint template, USB trace, full Compose
file, pairing configuration or unrestricted debug log. A crash dump contains
process memory, and GDB can print cryptographic key bytes in function arguments.
Use `set print frame-arguments none` before collecting a stack trace and review
its contents manually. Report a redacted stack, versions and reproduction steps.

## Reinstallation or package updates

A local library override is not managed by pacman. Check `fprintd-verify` after
major upgrades, and rebuild if dependencies or ABI compatibility change. Keep a
known-working recovery copy outside the disk being reinstalled. A Git clone of
this repository is not a backup of your pairing state, enrolled fingerprints or
password manager.
