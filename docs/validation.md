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

### Later read-only post-start observation

On 20 October 2026 the owner reported starting the TV after leaving it off overnight. Pinned SSH still worked and ordinary telnet refused; effective voice/content-mining masks, stored/effective filtering DNS, all three exact owned read-only preview binds and the expected guarded QML digest were present. Home had no CRIU snapshot marker. Collection, device-ID, ACR/voice/ad and update-preference values still read `"off"`; SDX was authenticated. These are current-state readbacks, not proof of application playback or visual presentation.

**Exception: `option.hbbTV` read `"on"`, unlike the earlier `"off"` observation.** It was not written again during the check. The native enum also exposes `onByUser`/`offByUser`, but their persistence semantics were not established and no experimental replacement was made. Recheck this value explicitly; do not claim the original HbbTV change stayed disabled or silently add a recurring setter.

The current boot ID equalled the preserved pre-start baselines. Uptime/start metadata was collected privately, but these observations do **not** independently prove a physical cold boot or explain its identity behavior. The cold-boot criterion remains open. [Allowlisted post-start receipt](../assets/evidence/post-start-verification.json) omits raw boot IDs, PIDs, timestamps, addresses, hook paths and other private diagnostics. The public service payload's `--check` also ran in read-only mode; no hook was installed/replaced, no mount or setting changed, and no Home reload/reboot was requested.

### Publication checks

The package uses a fresh allowlisted source tree, not the private project or its Git history. The offline checker inspects textual identifiers, release filenames, local links and available Git history; manual review covers evidence pixels, metadata, vendor-source boundaries and attribution. It is a backstop, not a guarantee that a secret detector recognizes every possible secret. Original source code and firmware-derived local state are separated explicitly.

Three real-data evidence panels were rendered locally from [allowlisted JSON](../assets/evidence/cx-internals.json) and visually checked for legibility and identifiers. They are **reformatted observations, not terminal screenshots**. [Gallery](gallery.md)

### Version 0.1.0 audit expansion

The current four generated helpers were again compiled in the TV's Python 2.7.15 **in memory**, and the current reload helper's native getter/schema `--preflight` passed, with helper imports held in `sys.modules` and bytecode disabled. The pinned transformation of the privately preserved original QML matched the expected output digest. No helper was deployed and no mount, app close/launch, reload, setting or reboot occurred. Large verification source was streamed over pinned SSH stdin, not installed as a TV file.

The expanded public audit was exercised again read-only on the source TV after integration. It returned masked/inactive voiceinput/contentminer, active `voiceconductor`, exact-target mount counts/modes, fixed public-hook states/hashes and SSH/telnet preference booleans. In this source setup the optional hook used a legacy/custom name, so the fixed public preview-hook path correctly reported absent; that is not proof of no persistence. Existing stacked hosts layers were reported as counts, not adopted or changed. The new `acr`/`advertising`/`voice` setters, DNS probe after apply and new Home-retry/boot-recovery paths were not live-invoked.

### Rooting/bootstrap documentation evidence

The source TV was already rooted when the original maintenance work began. The expanded [rooting guide](rooting.md) was checked against SlopBro commit `21023d56ca424607bb03d2939609cc658c655fc7` and HBC 0.7.3 startup/UI source, with pinned citations. Its host `--help` and the non-exploit simple HTTP handler were exercised without a TV. Documentation tests execute the actual public-key wrapping and single-target TCP-check snippets with synthetic public data/mocked sockets, test the existing-checkout refusal, and parse shell recipes. These are not execution of an exploit or evidence of a newly rooted/factory-fresh TV. The public guide includes necessary owner-chosen bootstrap restart decisions but no restart was performed during this publication.

### Optional screensaver evidence

The original moving-rings component was rendered locally with Qt/OpenGL and exercised in a separately approved private deployment on the source CX. Native DISPLAY captures at 1920 × 1080 and an installed-hash readback confirmed that visual; two animation phases and process/journal samples were inspected. The public visual template separately passed 15 host Qt/OpenGL render/lifecycle checks. A locally generated package from the pinned private originals passed its 9-file hash check, and its three Python helpers were imported, `--help` exercised and no-argument refusals checked in an isolated network-disabled Python 2.7.18 container. The final lifecycle helper also passed a real directory-lock contention and atomic journal write/read/delete smoke check in that container, without mounts. Linux regressions exercise real cross-process `flock` plus simulated mount interruption/recovery, committed-state preservation and mismatched/stacked refusal; POSIX device cases skip explicitly on Windows. This is not the TV's embedded Python 2.7.15 or native Qt/SAM stack. Those observations are distinct from a **live public screensaver installation**, which has not been installed, reloaded or failure-injected on the TV during this publication work. No TV connection or mutation is needed to run its public tests.

The [gallery](screensavers.md) and [capture provenance](../assets/evidence/screensavers.json) preserve native PNGs and an explicitly identified crop. They do not establish panel luminance, energy use, burn-in protection or physical remote behavior. The [module guide](../optional-screensaver/README.md) lists the generation, ownership, no-write and recovery guards and remaining live checks. No physical cold start was performed.

## Not completed or not supported

- A physical cold-start persistence/early-boot test, full streaming playback regression and every physical remote-control path.
- Reinstalling/applying/rolling back the public refactor on the running source TV. Prior original-device tests and public offline tests are separate evidence.
- Atomic isolation from another administrator or the TV settings UI. Native setters are unconditional; an exclusive owner-controlled administration window is required and reported in command results. Automatic checkpoint rollback is same-boot only, with manual native-UI recovery documented after a reboot.
- Automatic/DHCP DNS restoration through ConnMan CLI. The public setter refuses an empty baseline/restoration rather than guessing reset syntax; use the original TV network UI choice instead.
- Other models, firmware/builds, Wi-Fi-only mutation, multiple active Ethernet services, native PowerShell recipes, a full firewall or LAN isolation.
- Complete telemetry/microphone prevention, comprehensive encrypted-traffic interpretation, quantified before/after bandwidth reduction or reliable YouTube in-video ad removal.

## Hosted verification

The pinned workflow runs offline tests on Linux with Python 3.9, 3.11 and 3.13, plus a Windows portable-host job that explicitly skips POSIX-only cases, without a TV or device credentials. Check [GitHub Actions](https://github.com/Resnais-Beefhair/webos-under-the-hood/actions/workflows/offline.yml) for the result and exact commit of each hosted run. Local tests are **not** a hosted run, and hosted tests do not establish the unperformed device checks above. A repository publication is not a tagged release or a claim of broader compatibility.

Use [recovery.md](recovery.md) for the reader's verification checklist. Unknowns are stop conditions, not reasons to weaken guards.
