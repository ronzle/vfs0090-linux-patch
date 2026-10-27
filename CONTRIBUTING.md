# Contributing

Keep changes focused on the VFS0090 repair workflow and use English for code
comments, documentation and issue reports. Preserve upstream attribution.

Run the Python tests, then build and run the enabled libfprint unit tests. Driver
changes need hardware testing; describe the exact device, distribution, driver
revision and scenarios tested. Separate measured results from hypotheses.

Do not include device serial numbers, usernames, account identifiers, pairing
files, templates, firmware, Windows installers, logs with key material or core
dumps. Use placeholders in examples. Build outputs and personal configuration
belong in ignored directories.

The patch series is intended to be reviewable for an eventual upstream proposal.
Changing matching thresholds to make a failing test pass is not an acceptable
substitute for understanding image acquisition or processing failures.
