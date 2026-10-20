# Instructions for agents operating this repository

This is a device-maintenance project, not permission to control a household.
Read README.md, docs/compatibility.md, docs/connection.md and docs/recovery.md before proposing changes. Follow the owner's latest instruction over examples here.

## Operating contract

1. Ask the owner to identify the exact TV, ownership, model/firmware, host SSH alias and recovery route. Do not scan the LAN to pick a target or infer consent from a discovered device.
2. Start with `python3 tvctl.py --help`, the offline tests and a read-only audit. Keep audit/checkpoint data in ignored `.local-state/`, outside Git and public chat.
3. Confirm actual root identity, pinned host key, supported versions, native settings schemas and expected source hashes. A mismatch is a STOP, not a reason to add `--force`, guess a key or bypass a guard.
4. Present a small feature-by-feature plan, expected losses and exact rollback. Obtain explicit owner consent before adding keys, disabling telnet, changing security settings, stopping services, changing DNS recipient, installing persistent hooks or reloading Home. No blanket “do everything” interpretation.
5. Use separate checkpoints and readbacks. A successful setter or SSH exit is not verification. If a write succeeded but parsing failed, read the real state before deciding anything; do not rerun a mutation or blindly restore stale state.
6. Keep YouTube Home-preview customization OFF unless separately chosen. It is cosmetic, firmware-hash-specific and requires an approved Home reload window. It does not modify the YouTube icon, app or network access.
7. Never disable `sdx`, `admanager` or `voiceconductor`, replace binaries with null files, delete CRIU snapshots, change global preloading, restart SAM or upgrade firmware as a shortcut. Never reboot, factory-reset or change a router/other device without a separate, explicit instruction.
8. Never read private keys, ask for passwords in chat, export pairing credentials or weaken SSH host-key checking. Do not close a working fallback until a new independent SSH session is verified. Do not re-enable telnet merely to make automation easier.
9. A DNS provider is an external recipient. Explain it and obtain consent; only the selected TV's Ethernet resolver list may change. No global/router DNS or implicit paid service.
10. Rooting, recovery exploits and third-party app installation are separate owner-approved work. Review upstream instructions and exact compatibility; this repo does not automate an exploit or promise eligibility. Do not use `--curl-insecure` or disable TLS verification by default.
11. No publication or upload of raw diagnostics, TV screenshots, private addresses, MACs, identifiers, account history, key lines or backups. Public evidence here is a deliberate allowlist, not a sanitizer for arbitrary files.
12. Stop on foreign hooks, unexpected mount ownership, changed firmware, concurrent state changes or partial apply. Preserve the checkpoint and report what is known. No broad cleanup of someone else's resources.
13. Arrange an owner-controlled exclusive administration window before settings/DNS writes or rollback: no other agent, administrator or TV settings-UI changes at the same time. These native setters have no atomic compare-and-set. Pre-write/readback checks detect some drift but cannot protect against an intervening writer; never describe them as transaction isolation. Same-boot rollback is deliberate; follow the manual recovery policy after a reboot.

## Verification and handoff

Run the offline tests after code changes. Inspect the diff, the no-write defaults and error paths. Describe original live-device evidence separately from tests of this public refactor. State clearly if full playback, physical remote, real cold boot or live installation of the public tool was not tested. Close only task-owned temporary files/processes. Do not leave a packet collector or daemon running.

A complete handoff names the changed feature, actual readback, checkpoint path, rollback, untouched invariants and remaining manual test. Do not claim all telemetry blocked or all LG models supported.
