# Installed components and exact change inventory

## Starting point versus new work

The original setup record reports **SlopBro** as the initial root method and **Homebrew Channel 0.7.3** as the installed TV app. Its bundled **Dropbear** supplied SSH; ordinary root telnet had been left open as a fallback. Those initial installation statements are historical operator records, not a new exploit test by this public project. [Rooting background](rooting.md)

No new streaming app, SSH server package, Python package, packet-capture app or resident monitoring agent was installed during the subsequent privacy, HbbTV, preview and DNS changes. Existing YouTube, Plex and other TV apps were retained. The toolkit does not require those apps, their accounts, or the original operator's computer.

On the host, the public toolkit needs Python 3 and OpenSSH; Git is useful to obtain the repository. Optional gallery regeneration needs Pillow only on the host. Hermes, Paramiko, an AI account and the original private helper scripts are **not required**.

## New management configuration

- Dedicated Ed25519 client key; public key added while preserving existing authorized keys.
- Independently verified/pinned server host key, batch operation and disabled forwarding for the new key.
- Homebrew Channel's ordinary telnet-disable flag set **after** new-session SSH verification. Its separate emergency/failsafe behavior was not modified.

The public [connection guide](connection.md) uses placeholders and lets you perform these steps yourself. It contains no actual key, password or pairing credential.

## Targeted device changes

| Feature | Exact target | Source-device change | Reproduction path |
|---|---|---|---|
| Voice-input effective mask | `/etc/systemd/system/voiceinput.service` | Overlay the unit with `/dev/null`; manager reads masked/inactive | [services](services.md) |
| Content-mining service | `contentminer.service` | Preserve masked-runtime/inactive state | [services](services.md) |
| Collection switch | `option.watchedListCollection` | `"on"` → `"off"` | `settings --feature collection` |
| HbbTV device identifier | `option.hbbTvDeviceId` | `"on"` → `"off"` | `settings --feature collection` |
| HbbTV | `option.hbbTV` | `"on"` → `"off"`, separately approved | `settings --feature hbbtv` |
| Automatic-update preference | `support.automaticUpdate` | `"on"` → `"off"`, trade-off explicit | `settings --feature updates` |
| Ethernet DNS | selected ConnMan service's `Nameservers.Configuration` | one Google resolver → AdGuard filtering pair | `dns --servers ...` |
| YouTube main-icon previews | Home `getAppPreview(launchPoint)` | one producer guard, original firmware not overwritten | [optional module](../optional-preview/README.md) |

`off` is a **JSON string**, not the boolean `false`. Native category, key, schema enumeration and response must be checked on the target. A command that returns success without a correct readback has not completed.

## Existing settings that were observed, not newly changed by the later toolkit

`option.livePlus`, `option.turnOnByVoice`, `general.adCookie` and `general.voiceLongDistance` were already `"off"` and were preserved. The historical setup record lists additional advertising/AI/promotion switches; not all of its claimed names and semantic effects were independently verified. They are not blindly replayed by the public CLI. Use the TV UI and actual native schemas for any additional setting.

## Existing startup and hosts protections

The source TV already had a custom exact-hosts list, a hosts bind hook and Homebrew Channel's own startup behavior. The HBC source was checksum-compared with its upstream version. Selected HBC startup code covered update blocking and telemetry-spool mounts; it was **not modified or reimplemented** here.[3]

A reference-only, sanitized list of the observed public hostname redirects is provided in [reference/hosts-observed.txt](../reference/hosts-observed.txt). It is not a new recommended blocklist and is not installed by this toolkit. The old hosts hook could layer over HBC's own hosts bind; do not stack a new one to imitate it. `/etc/hosts` supports exact names, not wildcard blocking. Blocked names do not prove the contents of encrypted traffic, and broad lists can break store, voice, recommendations or updates.

## Kept intact

`sdx`, `admanager`, `voiceconductor` and their binaries; firmware partitions; Homebrew Channel startup source; YouTube app/account/network; other apps' preview providers; global app preloading and CRIU settings; router and other devices; TV IP/gateway/proxy/IPv6 configuration.

Consent/EULA mappings were inspected but not rewritten. On this CX the native withdrawal path includes an SDX terms-withdrawal operation and a reboot, so it remained a separately scheduled decision. A running `voiceconductor` is an observation, not evidence of microphone recording.

## Sources

[3] https://raw.githubusercontent.com/webosbrew/webos-homebrew-channel/1a2b969e992617c9ba4b8a891542cb93a9e07b0a/services/startup.sh
