# Validation record and honest limits

## Evidence levels

The tested source profile is **LG OLED65CX6LA, firmware 04.64.00, webOS 5.6.2-21, `/etc/version` 20260421173614**, with Linux `4.4.84-219.jcl4tvmr.6`. Original observations were collected on 19 October 2026. Do not treat a matching version as universal compatibility.

### Historical starting point

Root via SlopBro and Homebrew Channel 0.7.3 were reported by the original operator's setup record. The public project did not repeat the exploit or reinstall HBC/Dropbear. It preserves those as prerequisites and links upstream, rather than presenting a fabricated bootstrap test.

### Original live-device changes

- A dedicated key-authenticated SSH session was verified before ordinary telnet was disabled. The upstream emergency/failsafe path was left intact.
- The original service hook produced effective masked/inactive voiceinput and contentminer states. The original voice-unit override was tested for non-stacking behavior and a masked start was refused after effective masking had been established.
- Native setting readbacks verified the collection/HbbTV/update preferences. SDX authentication and other app-launch dependencies were preserved; EULA withdrawal was not performed.
- The original optional YouTube producer guard was exercised with real Home reload, hidden reload, restoration/reapply and visual UI inspection. Snapshot bypass was scoped to Home. The startup path was simulated, **not physically cold-booted**.
- The original Ethernet DNS change was read back as stored/effective AdGuard servers. A bounded test set completed **24 DNS checks with zero errors**, with a synthetic filtering check and destination metadata. Plex identity/selected HTTP checks and system invariants were retained. These were not video playback tests. [Sanitized DNS receipt](../assets/evidence/dns-verification.json)

### Tests of this public refactor

Run entirely without a TV, credentials or private fixtures:

```sh
python3 -B -m unittest discover -s tests -v
python3 tvctl.py --help
python3 tools/check_publication.py
```

The suite covers settings/DNS planning and explicit consent, exact version/schema refusals, private exclusive checkpoints, partial/failed readbacks, drift-sensitive rollback, automatic-DNS recovery refusal, host-key public-only parsing, service-mask error/idempotence/foreign-layer guards, optional preview mount/hook ownership and Home reload checks, synthetic per-launchpoint QML behavior, bounded metadata parsing, publication detection and copy/paste shell syntax.

The public generator was additionally exercised **in memory against the real privately held original QML**. Its original and resulting digests matched the pinned pair. Neither original nor generated vendor source is part of the publication set. Synthetic tests alone would not establish that match.

### Authorized read-only tests on the source TV

The public `tvctl.py audit` successfully ran against the actual source TV: the exact build matched, SDX was authenticated, all selected settings were off, and one active Ethernet service had matching stored/effective AdGuard lists. This tests the public SSH/PTY/Luna parsing and audit path, not its write paths.

All four generated Python helpers were compiled **in the TV's existing Python 2.7.15 without writing files**, and the public Home reload helper's read-only `--preflight` successfully checked native schemas/running processes. No mount, hook install, service stop, application close/launch or reload was invoked by that check. It exposed and fixed a Python-2-incompatible shell-quoting call before delivery.

### Publication checks

The package uses a fresh allowlisted source tree, not the private project or its Git history. The offline checker inspects textual identifiers, release filenames, local links and available Git history; manual review covers evidence pixels, metadata, vendor-source boundaries and attribution. It is a backstop, not a guarantee that a secret detector recognizes every possible secret. Original source code and firmware-derived local state are separated explicitly.

Three real-data evidence panels were rendered locally from [allowlisted JSON](../assets/evidence/cx-internals.json) and visually checked for legibility and identifiers. They are **reformatted observations, not terminal screenshots**. [Gallery](gallery.md)

## Not completed or not supported

- A physical cold-start persistence/early-boot test, full streaming playback regression and every physical remote-control path.
- Reinstalling/applying/rolling back the public refactor on the running source TV. Prior original-device tests and public offline tests are separate evidence.
- Atomic isolation from another administrator or the TV settings UI. Native setters are unconditional; an exclusive owner-controlled administration window is required and reported in command results. Automatic checkpoint rollback is same-boot only, with manual native-UI recovery documented after a reboot.
- Automatic/DHCP DNS restoration through ConnMan CLI. The public setter refuses an empty baseline/restoration rather than guessing reset syntax; use the original TV network UI choice instead.
- Other models, firmware/builds, Wi-Fi-only mutation, multiple active Ethernet services, native PowerShell recipes, a full firewall or LAN isolation.
- Complete telemetry/microphone prevention, comprehensive encrypted-traffic interpretation, quantified before/after bandwidth reduction or reliable YouTube in-video ad removal.

## Hosted verification

The pinned workflow runs offline tests on Python 3.9, 3.11 and 3.13, without a TV or device credentials. Check [GitHub Actions](https://github.com/Resnais-Beefhair/webos-under-the-hood/actions/workflows/offline.yml) for the result and exact commit of each hosted run. Local tests are **not** a hosted run, and hosted tests do not establish the unperformed device checks above. A repository publication is not a tagged release or a claim of broader compatibility.

Use [recovery.md](recovery.md) for the reader's verification checklist. Unknowns are stop conditions, not reasons to weaken guards.
