# Changelog

## 0.1.0 — 20 October 2026

First explicitly versioned release. The original repository publication was unversioned; this release includes its field guide and the following issue-driven hardening.

### Safety and functionality

- Home reload requires all expected owned read-only mounts before closing Home, retries failed launches within bounded attempts, handles TERM errors, avoids duplicate accepted launches and checks preexisting app identities. Final failure gives concrete recovery instructions. (#1, #2)
- Missing Home checkpoint directories fail closed with visible states. A boot-reload failure attempts cleanup of only newly created, still-owned read-only binds and visible recovery with original snapshots allowed; it does not remove preexisting layers or the persistent hook. (#3)
- Added individually opt-in `acr`, `advertising` and `voice` groups, exact-key `--list-features` JSON, and `--version` with the pinned target profile. `collection` is not ACR. (#4, #11)
- Pinned the original voiceinput unit digest and added genuinely read-only service `--check`; no custom-unit override or broader device allowlist. (#6)
- DNS apply keeps configuration verification separate from a bounded fixed-name resolution probe and its limitations, with no automatic rollback. (#8)
- Audit includes allowlisted service states, fixed-target mount counts/modes, known public hook states/hashes and boolean SSH/telnet preference flags. It is private output, not comprehensive foreign-hook discovery or ownership proof. (#11)
- Native Windows permits portable/read-only-to-stdout paths; private files and mutations require POSIX/WSL. POSIX-only tests skip explicitly, and hosted CI includes portable Windows checks. (#9)

### Publication and guidance

- Hardened text/index/history checks for contextual identifiers, user paths, IPv4, bounded compressed PNG metadata and commit messages/attribution. The scanner remains a backstop, not an anonymizer. (#5)
- Added the SDX/admanager dependency failure explanation, voiceconductor distinction, concrete recovery playbooks, systemd evidence, privacy coverage matrix, DNS-recipient/local alternative trade-offs and hosts provenance. The generic localhost alias is not presented as a tracking domain. (#7, #8, #10)
- Enabled the repository's private vulnerability reporting, documented its direct form, added topics, and introduced this explicit version/changelog. (#12)
- Prevented bytecode creation by read-only/no-action helper imports; regression-tested with the environment bytecode flag unset.

### Evidence and remaining limits

The expanded public audit and service `--check` ran on the source TV in read-only mode. Generated helper syntax/getter preflight checks are separate from installing the refactored runtime. Public setters/installers, launch-retry/boot-failure behavior and broader hardware compatibility remain offline-tested, not live failure-injected.

A later post-start readback retained masks/DNS/owned preview overlays, but **HbbTV was on**. Boot identity did not change, so physical cold-boot persistence and the HbbTV cause remain unresolved. No reapply, Home reload or reboot was performed. Full video-playback/remote regression and a physical cold boot remain unperformed. See [validation](docs/validation.md) and [coverage](docs/privacy-matrix.md).
