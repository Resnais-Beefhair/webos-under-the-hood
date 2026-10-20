# Contributing

Keep changes small, reversible and observable. Do not widen a firmware/hash allowlist without an owner-approved device test and a redacted report. Tests using synthetic devices must be labeled as such, not presented as measurements.

Run:

```sh
python3 -m unittest discover -s tests -v
python3 tools/check_publication.py
```

Do not include `.local-state`, private keys or public authorized-key lines, passwords, pair keys, cookies, raw Luna dumps, MAC/serial/device IDs, home addresses, viewing history or complete vendor QML. The scanner is a backstop, not an anonymizer; manually inspect images and every unpublished commit before publication.

A compatibility report should include model, region if relevant, firmware/webOS/build, exact native schema or QML hash, features explicitly tested, successful readbacks, rollback outcome, whether real cold boot/playback was tested, and known limitations. Remove identifiers first. Do not suggest that a service name or IP address proves recording or malicious behavior.

Agent-authored changes need the same code review and real tests as human-authored changes. Never put a TV connection, secret or real LAN scan in CI. Open an issue with redacted evidence before proposing destructive or broad service changes.
