# Human walkthrough

Run from the repository root in a POSIX shell on Linux, macOS or WSL. This is a sequence of **choices**, not a paste-all installer. No AI account is needed. Do not run a write section before understanding its trade-off and recovery. The support envelope is deliberately narrow: [compatibility](compatibility.md).

## 1. Establish your own access first

Follow [connection.md](connection.md). Root/HBC and the TV's existing Python are prerequisites, not packages this toolkit installs. Verify the model in the TV UI, the firmware/build, a dedicated SSH alias and pinned host key, and an independent recovery route. Here `lg-tv` means your own alias. Stop if SSH fails; do not turn off host-key checking.

```sh
python3 tvctl.py --help
python3 -B -m unittest discover -s tests -v
umask 077
mkdir -p .local-state
chmod 700 .local-state
python3 tvctl.py --target lg-tv audit --output .local-state/audit.json
```

The audit reads selected setting schemas/values, root/build identity, SDX authentication, launchpoints, foreground app and the one active Ethernet DNS service. It sends no setters, mounts or reloads. Getter calls can demand-start a native Luna service. The audit is **private**: it includes a boot ID and foreground application. Do not upload it. A successful audit is a prerequisite, not approval to write.

## 2. Choose the core features separately

Before any write or rollback, arrange an **exclusive administration window**: no other person/agent should change these TV settings or use its settings UI concurrently. Ordinary playback need not stop for a read-only audit, but affected features need their own approved window. Native Luna/ConnMan setters are unconditional, not atomic compare-and-set transactions. The CLI reports this limit in its `coordination` field: immediate checks catch some drift, not an arbitrary intervening writer.

The defaults below **only plan**. `--target` and `--confirm-model` are global options and go before the subcommand. No hidden “apply all” exists.

```sh
python3 tvctl.py --target lg-tv settings --feature collection
python3 tvctl.py --target lg-tv settings --feature hbbtv
python3 tvctl.py --target lg-tv settings --feature updates
```

- `collection` sets `option.watchedListCollection` and `option.hbbTvDeviceId` to the string `"off"`.
- `hbbtv` separately sets `option.hbbTV` to `"off"`. Broadcast interactive/red-button services may stop working.
- `updates` sets `support.automaticUpdate` to `"off"`. This avoids an automatic update preference but also postpones security fixes and **does not guarantee firmware is frozen**. Choose a deliberate manual update policy; compatibility and re-rootability of future firmware are unknown.

The CLI checks native categories, string-valued enums and the exact tested build. It does not replay unverified switches or EULA objects. Read the [inventory](changes.md) before choosing.

### Apply one feature, then verify

Only after you explicitly choose `collection`, for example:

```sh
python3 tvctl.py --target lg-tv --confirm-model 'LG OLED65CX6LA' settings --feature collection --apply --confirm-target lg-tv --checkpoint .local-state/collection.json
python3 tvctl.py --target lg-tv settings --feature collection
python3 tvctl.py --target lg-tv audit --output .local-state/after-collection.json
```

The new checkpoint is exclusive and private; a pre-existing file is refused. If no values need changing, the CLI reports `no-op` without making a misleading checkpoint. For another feature use its own name and a new checkpoint, e.g. `hbbtv.json` or `updates.json`. Readback must match, SDX must remain authenticated, and foreground/launchpoints must be compared with the immediate baseline. Test Home and the affected functionality before another change. Never relax a failed guard to make the output green.

A timeout or readback failure does not mean no write occurred. Preserve the checkpoint, read fresh state, then follow [recovery](recovery.md); do not blindly repeat the apply command.

## 3. Optional voice/content-mining service masks

Read the separate [service-mask guide](services.md). This is a service stop and a persistent startup-hook choice, not a setting-plan command. It can disable voice input. Keep `sdx`, `admanager`, their binaries and global app preloading intact. Do not use a generic debloater or “stop every advertising service” list.

## 4. Optional TV-only DNS filtering

The source TV had a **non-empty manually configured resolver list**. The CLI's mutation/rollback path supports that baseline only. It refuses apply from an empty `Nameservers.Configuration`: a safe automatic/DHCP restoration command has not been hardware-verified. For an automatic-DNS TV, use its network UI instead, privately record Automatic DNS and all original network fields, and restore that same UI choice if needed. Do not invent ConnMan reset syntax or alter IP/gateway fields to make the CLI proceed.

Choose a resolver and read its privacy policy. AdGuard Public DNS is one optional external operator, not a required account or a project service. Approving DNS means approving that operator as a recipient of the TV's queries. Do not change the household/router DNS.

```sh
python3 tvctl.py --target lg-tv dns --servers 94.140.14.14 94.140.15.15
```

Review the before/proposed lists. Only after explicit recipient and change approval, for the supported manual baseline:

```sh
python3 tvctl.py --target lg-tv --confirm-model 'LG OLED65CX6LA' dns --servers 94.140.14.14 94.140.15.15 --apply --confirm-target lg-tv --ack-external-dns --checkpoint .local-state/dns.json
python3 tvctl.py --target lg-tv audit --output .local-state/after-dns.json
```

The CLI discovers exactly one active Ethernet service on the selected TV; no other LAN host is scanned. It writes only `Nameservers.Configuration`, checks both stored/effective lists, and rejects unrelated ConnMan drift. A `verified` result proves those configuration readbacks, **not** blocking coverage or streaming playback. Keep your saved original list for recovery. Wi-Fi/multiple active Ethernet services are outside this tool's scope.

Filtering cannot isolate the TV from the LAN or cover all direct-IP, IPv6 or encrypted-DNS traffic. It is not a reliable YouTube in-video ad blocker. Verify your ordinary apps and Plex, not just a DNS test name. [Limitations](internals.md#dns-is-one-layer)

## 5. Cosmetic Home previews: off by default

Only if you want it, use [optional-preview/README.md](../optional-preview/README.md). It suppresses the main YouTube icon's Home preview row, **not the icon or YouTube itself**. Generation needs a privately extracted exact-hash original. Mounting, a one-time Home reload and recurring boot-time reloads are separate decisions. No vendor QML is distributed.

## 6. Close the loop

Use [the verification checklist](recovery.md#verification-after-each-change). Test the physical remote, Home, YouTube/Plex/your streaming apps and any features you kept. Schedule a physical cold start separately if you choose persistence; a hook file or simulated boot is not that test. No reboot is performed automatically.
