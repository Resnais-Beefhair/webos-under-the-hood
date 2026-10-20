# Compatibility, risks and prerequisites

## Tested source environment

- LG OLED65CX6LA (CX, European model).
- Firmware **04.64.00**; webOS **5.6.2**, build **21**.
- `/etc/version`: `20260421173614`; kernel `4.4.84-219.jcl4tvmr.6`.
- Root, Homebrew Channel and its Dropbear SSH server already existed before the later privacy/DNS work.
- Existing TV tools: `luna-send`, `systemctl`, ConnMan/`connmanctl`, `mount`, `sha256sum`, `script` and embedded Python 2.7. Do not install a replacement Python on the TV.
- Host: Python 3.9 or later, OpenSSH client and a POSIX shell. Linux and macOS are documented; on Windows use WSL for the shell recipes. Native PowerShell redirection and quote rules are different and are not a tested drop-in replacement.

The exact versions above were read back from the source device. The evidence is in [the gallery](gallery.md). The public CLI, optional Home module and [optional screensaver module](../optional-screensaver/README.md) have their own offline tests; that does **not** imply the refactored installers have been run on every device.

## Stop conditions

Stop if the TV is not yours, is not already rooted, has a different firmware/build, uses a different Home QML hash/schema, lacks a recovery path, has unknown pre-existing hooks or mounts, or if another person is using an affected feature. Read-only investigation is appropriate; bypassing the guard is not.

This is not an assertion that other CX sizes or firmware cannot work. They have not been validated. Submit a redacted compatibility report rather than silently widening a version/hash allowlist.

## Deliberate trade-offs

- Disabling `voiceinput` affects voice-input functionality. Treat losing voice commands as a feature choice, not a free optimization.
- Disabling collection/ACR-related components may reduce personalized features; it is not proof of complete capture prevention.
- Turning HbbTV off removes interactive broadcast/hybrid services (often the red-button experience). Ordinary broadcast reception was intended to remain available; individual broadcasters still need user testing.
- Turning automatic updates off can preserve a root setup while leaving security vulnerabilities unpatched. It is **optional and not a blanket security recommendation**. Hosts/startup/DNS blocking cannot guarantee the firmware will never update.
- A filtered public DNS provider sees your DNS questions and may block a required hostname. Resolver settings are not LAN isolation. IPv6, direct IPs, encrypted DNS and hard-coded resolvers can bypass this layer.
- The optional Home overlay bypasses only Home's saved CRIU state to load new QML. Startup speed was not benchmarked; real early-boot timing was not tested.
- Optional screensaver replacement is a cosmetic experiment, not a privacy feature or an OLED safety certification. It changes two pinned QML components, keeps a black background and moving geometry, and omits the native wake-up text. Picture settings, native input handling and panel-protection settings are not changed. Physical remote dismissal, idle activation, long-run behavior and cold-boot persistence still need device-owner verification. Enable persistence only as a separate choice after a successful temporary test.
- Root changes the device's trust and support model. Homebrew Channel removal, Developer Mode interactions, firmware changes or factory resets may remove access or affect persistence. Consult upstream before changing these.

## Things deliberately outside the automated path

Root exploits, acquiring someone else's credentials, warranty advice, firmware downloads, installing Developer Mode, router VLAN/firewall changes, EULA withdrawal, application removal, flashing partitions and unscheduled TV/Home/service restarts.

The [complete manual rooting guide](rooting.md) supplies the initial-access steps for the documented source profile, including owner-chosen bootstrap restarts, while keeping them separate from the automated toolkit. It is source-reviewed and host-tested, not a universal one-command root or a freshly rerun root of an untouched TV.
