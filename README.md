# webOS Under the Hood

[![Offline verification](https://github.com/Resnais-Beefhair/webos-under-the-hood/actions/workflows/offline.yml/badge.svg)](https://github.com/Resnais-Beefhair/webos-under-the-hood/actions/workflows/offline.yml)

**A reversible privacy field guide for a rooted LG CX, with real evidence from inside the TV.**

![Inside a rooted LG CX: real service and filesystem observations](assets/inside-webos.png)

A smart TV is also a Linux computer. This project documents how one already-rooted LG OLED65CX6LA was inspected, given a safer management connection, and configured to reduce selected collection and recommendation features without dismantling its normal TV functions.

It contains the **rooting-to-SSH bootstrap guide, code, exact settings, checkpoints, recovery procedures and honest limits**. Start with [the complete rooting guide](docs/rooting.md) if you do not already have root. You can follow the full chain yourself or give the repository to an agent; no AI account, cloud inference or paid service is required. Upstream software downloads are linked, but the steps to use them are included here.

> **Not a universal debloater or rooting exploit.** Tested source device: **OLED65CX6LA · firmware 04.64.00 · webOS 5.6.2-21**, inspected on 19 October 2026. Other models and firmware are not validated. A valid SSH session and schema/hash matches are prerequisites, not proof that every feature is safe on another TV.

## Start here

1. Read [compatibility, risks and scope](docs/compatibility.md). Do not begin by upgrading, factory-resetting or trying random exploits.
2. **Not rooted?** Follow [the complete bootstrap](docs/rooting.md): host tools → pinned SlopBro source → harmless connectivity check → explicit root operation → HBC → first root console. Already rooted with working HBC? Skip that operation. The bootstrap is source-reviewed and host-tested, not freshly re-run on an untouched TV.
3. Follow [connection and recovery setup](docs/connection.md). Verify a **new key-authenticated, host-key-pinned SSH session before closing ordinary telnet**.
4. Run the read-only audit, then choose individual changes in the [human walkthrough](docs/walkthrough.md). Planning does not apply changes; [Home customization](optional-preview/README.md) and [screensaver replacement](optional-screensaver/README.md) remain separate opt-ins.
5. Keep your private checkpoints. Use the [verification and rollback guide](docs/recovery.md) after every feature and after a later, deliberately scheduled cold start.

**Windows:** use WSL for the commands below, private `--output` files, checkpoints, mutations and the full suite. Native Windows supports read-only `audit` to stdout and portable tests only; POSIX-only cases explicitly skip. Do not weaken checkpoint permissions to bypass this boundary.

```sh
git clone https://github.com/Resnais-Beefhair/webos-under-the-hood.git
cd webos-under-the-hood
python3 tvctl.py --help
python3 -m unittest discover -s tests -v
python3 tvctl.py --target lg-tv audit --output .local-state/audit.json
```

`lg-tv` is **your own SSH alias**, not a built-in IP address. No command knows or guesses your TV's address. Linux/macOS are the documented POSIX host paths; Windows via WSL is the documented path for private files and writes. The host CLI uses Python's standard library and OpenSSH; the TV uses its existing tools and Python 2.7. No TV package installation is required by the privacy changes.

Writes require an owner-controlled **exclusive administration window**. Native setters have no atomic compare-and-set; readback checks are not transaction isolation. Automatic checkpoint rollback is deliberately same-boot only. See [recovery](docs/recovery.md) rather than bypassing these limits.

## What you can reproduce

- **Initial root access:** a complete owner-operated, revision-pinned SlopBro → HBC → trusted first-console guide, including host setup, pairing, return-path checks, cleanup and failure stops. Upstream root software is downloaded separately, not bundled; root execution and bootstrap reboots are not automated by `tvctl.py`. [Rooting guide](docs/rooting.md)

- **Management:** a dedicated SSH key, verified host key and restricted key entry; ordinary Homebrew Channel telnet disabled only after the new connection works. [Connection guide](docs/connection.md)
- **Service masks:** correct an ineffective `/run` mask by overlaying the existing `voiceinput.service` unit with `/dev/null`, and keep `contentminer.service` masked/inactive. Do not delete binaries or disable Home dependencies. [Service-mask guide](docs/services.md)
- **Settings:** native, schema-checked string values for collection/device ID, HbbTV and optionally automatic updates, with per-feature snapshots and readbacks. [Exact change inventory](docs/changes.md)
- **DNS:** an optional change to **only the TV's active Ethernet ConnMan service**, using a chosen resolver such as AdGuard's filtering pair. Explicitly approve the new DNS recipient first. This is not a firewall or LAN isolation. [Walkthrough](docs/walkthrough.md)
- **Diagnostics:** inspect Linux services, mount layers, Luna settings, startup hooks and resolver state. [Under-the-hood gallery](docs/gallery.md)

### Optional: hide YouTube's Home preview cards

**Off unless you deliberately install it.** This is a cosmetic Home customization, not part of the core privacy workflow. The **YouTube icon, app, account and network access are left unchanged**; only the main icon's Home preview row is suppressed. Other apps and YouTube channel shortcuts keep their original path.

The [separate optional module](optional-preview/README.md) generates a tiny producer guard from **your own, exact-hash-matched firmware file**. LG's QML is not redistributed. Read-only overlays and Home-only snapshot bypasses are reversible. A separately approved Home reload window is necessary; no TV reboot or SAM restart is included.

### Optional: replace the fireworks screensaver

**Off by default, independent of the privacy changes and Home customization.** The [screensaver module](optional-screensaver/README.md) replaces only the native visual component with slowly drifting cyan, lilac and amber rings on black, without wake-up text. Its original visual code keeps the native `playing`, `liteMode`, `isPartial`, `guideString`, `looped()` and approximately 7.5-second loop interface.

The module generates a private, exact-hash-pinned package from files you extract from your own TV. Installation, application reload and optional boot persistence require separate deliberate actions; rollback restores only verified owned overlays. **Experimental:** the public runtime has offline tests, not a completed live installation or cold-boot qualification. No OLED/burn-in guarantee, picture-setting change, TV reboot or SAM restart is included.

**Before: original fireworks, full frame**

![Original LG CX fireworks screensaver](assets/screensavers/original-fireworks.png)

**After: moving light rings, full frame**

![Optional moving light rings screensaver](assets/screensavers/moving-rings.png)

Both are real, unbrightened 1920 × 1080 captures from the same TV during the earlier owner-approved experiment, not mockups or tests of the public installer. [Full gallery, native-pixel detail and provenance](docs/screensavers.md).

## What this does not claim

- No guarantee of “zero spying”, “all ads removed”, microphone silence or a fully trusted rooted device. An active voice-related process is not proof of recording.
- DNS filtering cannot stop every direct-IP, IPv6 or encrypted-DNS path, and does not isolate devices on the same LAN. It does not reliably remove YouTube in-video ads.
- No blanket disabling of `sdx`, `admanager` or `voiceconductor`; no replacement of binaries with `/dev/null`. Breaking the tested CX's SDX authentication dependency left Home visible but unable to launch apps (`ServiceDown` in diagnostics). An active `voiceconductor` is not evidence of recording. [Why these services stay and how to recover](docs/services.md#why-sdx-admanager-and-voiceconductor-stay).
- No consent/EULA mass edits. On this CX the native withdrawal workflow can revoke SDX terms and reboot; it was investigated but **not executed**.
- No router firmware changes, whole-house DNS change, firewall installation, automatic firmware update or factory reset. The separate manual rooting guide describes an explicitly owner-run upstream exploit; **the toolkit itself never automatically runs it or reboots the TV**.
- The original changes were read back and selected UI/network checks passed. **Full streaming playback regression and a physical cold boot were not performed.** Public packaging/refactoring tests are distinct from those device observations. [Validation record](docs/validation.md)
- A later read-only post-start check found the masks, DNS and owned preview overlays still present, but **HbbTV read back as `"on"`**. Boot identity had not changed, so that observation does not establish physical cold-boot persistence or the cause of the HbbTV change. No automatic reapply was performed. [Sanitized post-start evidence](assets/evidence/post-start-verification.json)

## Privacy coverage at a glance

- `collection` means watched-list collection plus HbbTV device ID, **not ACR**. ACR/Live Plus, ad cookie and voice settings are separate opt-in settings; see `python3 tvctl.py --list-features` for exact keys/groups.
- Settings readback, service masks, optional Home cosmetics and DNS filtering cover different paths. None establishes full telemetry blocking, microphone isolation, LAN isolation or video playback.
- [Full privacy matrix: changed / observed / not covered / verify manually](docs/privacy-matrix.md).

## Let an agent help

Give the agent the repository and this instruction:

> Read AGENTS.md and the compatibility/connection guides. Start with a read-only audit of the TV I identify. Explain a per-feature plan and rollback. Ask before authentication changes, stopping services, changing DNS recipient, installing hooks or reloading Home or the screensaver. Keep YouTube customization and screensaver replacement off unless I explicitly choose each one. For the screensaver, read optional-screensaver/README.md before generating or staging anything; installation, reload and boot persistence are separate decisions. Never upload private diagnostics or reboot the TV without a separate instruction.

If root access is not established yet, use [the rooting guide](docs/rooting.md) **instead of attempting that audit**. Obtaining root, pairing, installation and each required bootstrap restart need their own explicit owner decision; permission to read the repository is not permission to run an exploit.

[AGENTS.md](AGENTS.md) defines the same boundaries; a repository URL is not blanket permission to change a network.

## Project map

- [Complete rooting → HBC → first-console bootstrap](docs/rooting.md) · [Trusted SSH setup](docs/connection.md)

- [What was already installed, what changed, and what did not](docs/changes.md)
- [Manual walkthrough](docs/walkthrough.md) · [Recovery](docs/recovery.md)
- [Real internal views and how they were produced](docs/gallery.md)
- [Optional screensaver installation and rollback](optional-screensaver/README.md) · [Real before/after gallery](docs/screensavers.md)
- [Architecture and failure modes](docs/internals.md)
- [Evidence, tests and open checks](docs/validation.md)
- [Source references](docs/sources.md) · [Third-party notices](NOTICE.md)
- [Contributing and compatibility reports](CONTRIBUTING.md)

Original project code, documentation, moving-rings visual code and rendered evidence graphics use the [MIT license](LICENSE). Native LG artwork visible in the original screensaver screenshots is **not relicensed**; see [notices](NOTICE.md). LG firmware, Homebrew Channel, OpenSSH/Dropbear, system tools, app assets and third-party trademarks retain their own ownership and licenses; none of their binaries or full firmware source files are bundled. This is an independent project, not an LG or webOSbrew product.
