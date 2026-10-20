# Privacy coverage: settings are not network guarantees

This is the boundary of the public toolkit, not a promise that the TV stops sending data. Features are individually opt-in; `tvctl.py --list-features` gives the exact CLI groups, keys and tested build. A settings plan must validate the native enum on the actual TV before an explicitly approved write and same-boot rollback checkpoint.

| Data path / feature | Exact intervention | Public coverage / verification boundary |
|---|---|---|
| Watched-list collection | `option.watchedListCollection` and `option.hbbTvDeviceId` | Optional `collection` group. Not the ACR switch; does not reset all identifiers or delete history. |
| ACR / Live Plus | `option.livePlus` | Optional `acr` group. `off` was observed on the source TV; the public write path has not been hardware-exercised. Does not prove absence of all content recognition. |
| Advertising cookie | `general.adCookie` | Optional `advertising` group, not a universal advertising-ID reset, consent withdrawal or ad blocker. |
| Voice wakeup / distance settings | `option.turnOnByVoice`, `general.voiceLongDistance` | Optional `voice` group, with two native categories and one checkpoint. A partial write is not an atomic transaction. No microphone payload inspection or proof of hardware microphone isolation. |
| Voice-input service | Exact voiceinput unit bind plus effective manager-state check | Optional firmware/hash-pinned hook. Binaries and `voiceconductor` remain intact. Protection before HBC startup and physical cold-boot persistence are not established. |
| Content-mining service | `contentminer.service` effective mask/inactive check | Optional service hook preserves the expected state; no claim of blocking every collection path. |
| HbbTV | `option.hbbTV` | Optional `hbbtv` group sets the proven string `off`, not an assumed `offByUser`. **Later post-start observation read `on`; persistence/cause remain unresolved.** Verify manually after every start. |
| Firmware updates | `support.automaticUpdate` | Separate opt-in trade-off: keeping root is not a security-update policy. Does not prove firmware cannot update. |
| DNS-level filtering | TV Ethernet resolver list only | Recipient choice requires consent. Configuration readback and a bounded resolution probe are separate from streaming tests, filtering coverage and LAN isolation. |
| Exact-name hosts redirects | Existing source-device mechanism; historical reference only | Not installed by the toolkit. No wildcards; static maintenance and functional breakage risks. [Provenance and omissions](../reference/README.md). |
| Telemetry spools / HBC startup | Existing startup protections observed, not reimplemented | No new comprehensive telemetry blocker; direct IP, IPv6, application-selected/encrypted DNS and HTTPS payloads are not covered. |
| YouTube Home recommendations | Optional producer guard for this Home preview only | Cosmetic opt-in. Icon, YouTube app/account/network, other cards and other providers stay intact; app telemetry is not stopped. |
| EULAs / account consent | Read-only investigation | **Not changed.** Native withdrawal can revoke SDX terms and reboot; separate owner decision and interruption window required. |
| LAN exposure | Pinned-key SSH; prior independently verified telnet closure | No VLAN/firewall/router isolation is installed. DNS filtering is not LAN isolation. |

## Evidence levels

- **Original device intervention:** selected 19 October 2026 settings/service/preview checks and screenshots, not a full playback or cold-boot qualification.
- **Public toolkit:** offline tests and selected real read-only audit/check modes. Newly packaged setters, installers and reload failure recovery are not thereby hardware-tested.
- **Later post-start observation:** masks/DNS/owned preview binds were present, HbbTV was on and boot identity was unchanged. This does not establish a physical cold boot. [Receipt and limits](validation.md#later-read-only-post-start-observation).
- **Verify manually:** remote navigation, each streaming provider, LAN-hosted media, accessibility/voice needs and a separately approved physical cold boot. Do not infer these from a returned Luna success or a green CI badge.
