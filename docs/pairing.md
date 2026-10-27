# Pairing identity

The sensor contains a pairing state created during initialization. This driver
derives its key from a product name and serial number. These values must match
the host identity used during pairing, even when Linux is running on a different
host identity outside the VM.

For Windows, the following PowerShell commands show the guest identity:

```powershell
(Get-CimInstance Win32_ComputerSystem).Model
(Get-CimInstance Win32_BIOS).SerialNumber
```

For physical Linux DMI values:

```sh
cat /sys/class/dmi/id/product_name
sudo cat /sys/class/dmi/id/product_serial
```

Read the guest's actual values rather than assuming a default. In the tested
setup, QEMU's SMBIOS serial matched the physical host serial, while its product
name differed. That observation is not a rule for every VM.

The serial is an input to the existing protocol, not a replacement for a secret
or an authentication credential. It is nevertheless device-identifying data;
keep your local configuration out of public commits and issue reports.

The initial repair required Windows to initialize the sensor. Attempts with the
Linux initializer failed on that device. This project starts **after successful
pairing** and does not include a general initialization procedure or Windows VM
setup. A fingerprint reset can invalidate the working state. Reinstalling Linux
alone did not require resetting the sensor in the tested workflow.

Neither your fingerprint templates nor 1Password data are part of this repository.
After reinstalling Linux, enroll your finger again using fprintd.
