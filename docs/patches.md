# Patch design and validation

Patches apply to the exact commits in `upstream.json`, in filename order.

## 0000: OpenSSL dependency selection

The parent fork first requests OpenSSL 3.x before falling back. This driver uses
OpenSSL 1.1 APIs. The build checks the selected pkg-config version before allowing
configuration, and the Meson patch makes it respect that selection. It does not
claim OpenSSL 3 compatibility or change the system cryptography installation.

## 0001: Pairing identity and DMI parsing

`VFS0090_PRODUCT_NAME` and `VFS0090_PRODUCT_SERIAL` override the corresponding
DMI fields. Unset values fall back to DMI. Reading entire lines preserves spaces
in names such as a QEMU machine model. Empty identities are rejected.

## 0002: Image scaling

The driver tests `HAVE_PIXMAN` but did not include the generated `config.h`.
Consequently, the intended 2x image resize was compiled out even with Pixman
available. The fix includes the configuration header and uses `#if HAVE_PIXMAN`.

On the test device, the broken path produced 144x144 images, enrollment samples
with only 4–8 extracted minutiae and five comparisons scoring 0/12. Rebuilding
with scaling and enrolling again produced successful verification. The matching
threshold remains unchanged; lowering it is not the fix.

## 0003: Cancellation ordering

The observed crash passed a NULL `PK11SlotInfo` into `PK11_ImportSymKey` while a
delayed image/LED state was still running. The original cancellation path could
call `NSS_Shutdown` directly or start deactivation alongside an active scan.

The patch makes cancellation a request processed by the owning state machine:

- Delayed activation, scan, database, image, error and reactivation states check
  for cancellation before issuing another operation.
- An interrupt read can be cancelled immediately. An in-flight bulk request and
  its reply complete before deactivation sends a new command.
- Scan sub-state machines complete before the top-level scan callback starts
  deactivation or another enrollment stage.
- Activation errors no longer proceed into scanning.
- USB callbacks release the cancellable on both success and cancellation; newly
  allocated cancellables no longer receive an extra unbalanced reference.
- The cancel callback does not deinitialize NSS or free the shared device buffer.

The patch addresses the observed lifecycle bug; it is not a comprehensive audit
of all error handling in this legacy driver.

## Validation record

Locally tested on the T460s / 138a:0090, running Omarchy/Arch Linux with kernel
`7.2.6-arch2-1` (`uname -r`):

- All three enabled libfprint unit suites passed.
- Sixteen hardware cancellations: 0, 1, 10, 50, 100, 250, 500 and 1000 ms after
  starting verification, each repeated twice, with close/reopen between trials.
- A real successful match immediately cancelled in the match callback, followed
  by close/reopen, passed without the observed crash or USB timeouts.
- The corrected library was installed and a sensor open/release check passed.

Management-script tests additionally cover input validation, systemd quoting,
PAM idempotence, exact file/mode rollback, symlink refusal, selective Compose
cleanup and detection of stale USB container access. CI does not use hardware.

Before proposing upstream patches, reproduce the issue and fix independently,
test normal enrollment after the lifecycle change, and test cancellation during
image processing and enrollment on additional hardware. These broader tests are
not claimed by this repository.
