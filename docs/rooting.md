# From an unrooted LG CX to a trusted root connection

This is the **complete, manual bootstrap route** for the source profile: **OLED65CX6LA, firmware 04.64.00, webOS 5.6.2-21**. It covers host preparation, obtaining the exact upstream root tool, connectivity, pairing, Homebrew Channel (HBC), a first root console, and the handoff to pinned, key-authenticated SSH. You do not need an AI account, LG developer account, Developer Mode app, SDK, or the maintainer's private files for this route.

**Evidence boundary:** the original operator recorded using SlopBro and HBC 0.7.3. The TV was already rooted when this toolkit's later work began. This expanded guide was checked against the pinned upstream source and exercised only in its non-exploit host paths; a factory-fresh TV was **not re-rooted** to test it. Source review and offline tests are not a fresh end-to-end root installation. Unknown models/firmware are not certified by this guide.

If you already have HBC with **Root status: ok** and a trusted root connection, **skip rooting** and go to [connection setup](connection.md). Do not rerun an exploit merely to update these instructions.

## 1. Decide and identify the target before installing anything

1. Use only a TV you own or are explicitly authorized to administer. Arrange an interruption window: rooting launches a TV application, installs HBC, changes persistence and may require an owner-selected reboot. Do not root during playback, recording, another administrator's work or a firmware update.
2. On the TV, open **All Settings** and find **TV Information/About This TV** and **Software Update** (names and placement vary by region). Record the model, firmware and webOS version privately. This route uses webOS major **5**, not the firmware number `04.64.00`. If those fields do not match the source profile, stop this project's modification workflow; do not guess a version flag or flash/downgrade firmware to make it match.
3. Find the TV's current address in its network settings or your own router's device page. Identify it physically; do not scan the household to choose a TV. Prefer the same trusted Ethernet LAN for TV and host. Guest/client isolation, a VPN, WSL NAT or an untrusted shared network can prevent or undermine this process.
4. Do **not** install LG's **Developer Mode** app for this route. If already present, remove it with the TV's normal app-management UI before the first rooted reboot; do not delete its files by hand. Rooted HBC replaces that app's access/persistence role, and upstream warns against keeping it installed on a rooted TV.[3][6]
5. Check the TV's date/time and Internet access before any filtering. SlopBro's pinned installer downloads HBC **0.7.3** over HTTPS unless an IPK is already supplied. This guide preserves certificate verification; it does not use `--curl-insecure` or `curl -k` to hide clock/trust failures.[3]

**Rootability is not toolkit compatibility.** SlopBro upstream reports use across webOS 4–11 and includes a service-launch-patch workaround; it does not give a definitive per-model firmware ceiling. Do not read this as “every CX/firmware is rootable,” “04.64.00 is the last rootable firmware,” or permission to widen the toolkit's independent schema/hash guards.[1]

Rooting changes the trust/support model, can affect warranty/support and exposes powerful management access. HBC persistence and later firmware/factory-reset behavior are not a recovery guarantee. No partition flashing, hardware opening, system-binary replacement, factory reset or blind firmware update belongs in this procedure.

## 2. Prepare the host

The fully described host route is **Ubuntu 24.04 or newer, or Ubuntu in Windows WSL**, with a POSIX shell. Existing Linux/macOS setups can use the same recipes if Python 3.9+, Git, OpenSSH and a telnet client are already available. The code uses Python's standard library; do not install Python or pip packages on the TV.

On Windows without WSL, run this in an **administrator PowerShell**:

```powershell
wsl --install -d Ubuntu
```

Complete Windows' requested host restart, open Ubuntu and create its local user. This is a **computer** restart, not a TV reboot. Run all later shell recipes inside Ubuntu, not PowerShell. WSL networking must permit the TV to connect back to the advertised host address; if it does not, use a directly connected Linux host rather than changing router/host firewalls blindly.

On Ubuntu/WSL, review then install the host tools:

```sh
sudo apt-get update
sudo apt-get install --no-install-recommends python3 git openssh-client inetutils-telnet
python3 --version
git --version
ssh -V
```

These commands install packages on **your host**, not on the TV. The fully described package recipe is Ubuntu-specific, not a claim that macOS has `apt-get`.

Obtain this project, if you have not already, then work from its root:

```sh
git clone https://github.com/Resnais-Beefhair/webos-under-the-hood.git
cd webos-under-the-hood
umask 077
mkdir -p .local-state/rooting
chmod 700 .local-state .local-state/rooting
```

Do not repeat `git clone` inside an existing checkout. `.local-state/` is ignored and private; it will contain pairing credentials, copied upstream code and possibly logs. Do not force-add it to Git, upload it, or serve the whole project directory over HTTP.

## 3. Obtain the exact upstream tool, without vendoring it into this project

The reviewed SlopBro revision is **`21023d56ca424607bb03d2939609cc658c655fc7`**. It uses host Python 3 and standard-library networking, and includes its payload directory. Clone it privately; do not use a random packed file, a floating `main` download or a `curl | sh` bootstrap.[1][2]

```sh
(
set -eu
SLOPBRO_REV=21023d56ca424607bb03d2939609cc658c655fc7
test ! -e .local-state/rooting/slopbro
git clone --no-checkout https://github.com/throwaway96/slopbro.git .local-state/rooting/slopbro
git -C .local-state/rooting/slopbro checkout --detach "$SLOPBRO_REV"
test "$(git -C .local-state/rooting/slopbro rev-parse HEAD)" = "$SLOPBRO_REV"
test -z "$(git -C .local-state/rooting/slopbro status --porcelain)"
python3 -B .local-state/rooting/slopbro/slopbro.py --help
)
```

**Run this block once in a new workspace.** If the destination already exists, the clone is refused; stop and inspect that checkout, including `git status --short`, rather than blindly executing an old or locally changed copy. Read its `README.md`, `slopbro.py` and `wwwroot/autoroot.sh` locally. `--help` is non-exploit; it does not pair, start a server or touch the TV. A matching commit alone does not excuse unexplained worktree edits.

SlopBro remains a separately downloaded **AGPL-3.0-or-later** upstream program. This repository neither embeds it nor relicenses it under MIT. Its reviewed autoroot script installs HBC 0.7.3, elevates its service and establishes persistence; this is a real security modification, not just sideloading an icon.[1][3]

## 4. Set the two addresses and prove the return path without an exploit

In the same host shell, replace these two values with your own:

```sh
TV_IP=REPLACE_WITH_YOUR_TV_IP
HOST_IP=REPLACE_WITH_YOUR_HOST_LAN_IP
```

`HOST_IP` must be an address the **TV can reach**, not localhost, a container/VPN interface or an unreachable WSL address. On Linux/WSL, `ip -4 route get "$TV_IP"` shows the host route and source address; inspect it rather than guessing. On macOS inspect Network settings for the active LAN interface. Record addresses privately, not in public issues.

Start the upstream **simple connectivity mode**, from the private checkout:

```sh
cd .local-state/rooting/slopbro
python3 -B slopbro.py --local-ip "$HOST_IP" --test-server simple "$TV_IP"
```

Open the printed `http://HOST_IP:PORT/` in the **chosen TV's normal browser**. The expected plain text is `Here's your slop, bro!`. This mode serves that fixed text only: no pairing, exploit page or TV application launch. The default port is 8080, with a dynamic fallback if occupied; use the actual printed port.[1][2]

The upstream server listens on all host interfaces. Use a trusted, appropriately restricted LAN and, if a firewall exception is necessary, explicitly limit it to this TV and actual port for the short test. Do not disable the firewall, publish/forward the port, run as root to obtain a port, or make a permanent exception. A successful host-local browser test alone does not prove TV reachability.

Press **Ctrl+C**, wait for the host prompt to return and verify that printed URL no longer answers from the TV. Close that TV browser page. Never leave this test server running alongside the real launch. **Do not substitute `--test-server payload`: that mode serves a real exploit page and is not the harmless connectivity check.**[2]

If this test fails, fix the route/address or use a directly reachable host. WSL's default NAT does not guarantee inbound TV-to-host connectivity. Do not attempt the exploit until the TV itself reached the simple response.

## 5. Explicitly approve and run the root operation

You should still be in `.local-state/rooting/slopbro`. Confirm the exact physical TV, addresses and maintenance window. This is the point at which the owner deliberately chooses to exploit the TV and install persistent HBC:

```sh
python3 -B slopbro.py --asset-source dir --local-ip "$HOST_IP" --webos-version 5 "$TV_IP"
```

Watch the target screen and accept **only the pairing request you just initiated**. The launcher connects over SSAP, starts its temporary HTTP server, launches a compatible TV app pointing to the page, and writes a local `<TV-address>.key` pairing credential. Keep that file private; it is not an SSH key and does not authenticate the future SSH host key.[1][2]

**SSAP TLS is not authenticated by this pinned client:** it disables certificate and hostname verification. An active LAN attacker can interfere with pairing/launch; the plain-HTTP payload route also has no transport authentication. A pairing prompt or TLS connection is not protection against that attacker. Use only your isolated/trusted administration LAN; if active interception is in scope, stop rather than treating this bootstrap as secure transport. This client limitation is separate from the HBC download's HTTPS certificate verification, which this guide preserves.[2][3]

Follow the TV's displayed progress. The pinned payload downloads/installs HBC, elevates it and reports **Rooting complete** with reboot/developer-app guidance. The host message “all tracked files were requested” only records requests to the tracked URLs; it does **not** prove the response bodies were fully delivered, or that root, installation or persistence succeeded. Treat an installer/TLS/elevation error as a stop, not an invitation to repeat mutations.[2][3]

When progress stops or the host remains waiting, do not leave it unattended indefinitely: stop the host with Ctrl+C, keep private logs and inspect whether HBC was installed before deciding on another attempt. A failed or interrupted run can have made partial changes. Do not loop the exploit, change fake-service paths randomly, run old rooting methods in succession, kill TV services or factory-reset as cleanup.

### The first owner-controlled reboot

If HBC is not yet visible or the success dialog requests a reboot, first confirm the LG Developer Mode app is absent. Choose the TV's displayed **Reboot now** only in your approved interruption window, or **Don't reboot** and schedule it. If the app's presence cannot be established, do not reboot past that warning. The upstream installer explicitly checks this condition.[3]

This guide permits the **human owner to choose** that necessary bootstrap restart; the project CLI never automatically reboots the TV. A root-success toast is not proof of physical cold-boot persistence. Do not pull power while installation is in progress.

## 6. Open HBC, enable the bootstrap transports and obtain a first root console

1. Launch **Homebrew Channel** from the TV's Home apps. Open its **Settings**.
2. Check **webosbrew version: 0.7.3** and **Root status: ok**. `unelevated` is **not** success. If HBC is missing, unelevated or in Failsafe mode, stop here; do not continue with toolkit writes or clear recovery flags blindly.[5]
3. In **Root configuration**, keep **SSH Server off** and temporarily enable **Telnet** for this bootstrap only. Do not expose SSH before provisioning your public key: HBC otherwise installs a placeholder root password. Leave **Block system updates** and **Failsafe mode** unchanged unless separately chosen. Configuration changes require a reboot; use HBC's **System reboot** control only after the owner approves that interruption, then wait for the TV and HBC to return. SSH is enabled later, only after the public-key file is in place.[4][5]
4. On the trusted LAN, open the unauthenticated temporary root console from your host:

```sh
telnet "$TV_IP" 23
```

HBC's ordinary telnet server is a **passwordless root shell**, not a secure login. Do not type passwords, private keys, tokens or pairing credentials into it. Never expose it to the Internet or leave it enabled for convenience. Use it only for bootstrap verification, public-key provisioning and independent SSH host-key verification. Do not use an unfamiliar console that asks for unexpected credentials.[4]

At the **TV shell prompt**, enter these short, read-only commands one at a time:

```sh
id
cat /etc/version
cat /var/run/nyx/os_info.json
```

Require `uid=0` and the documented profile: `/etc/version` `20260421173614`, firmware `04.64.00`, webOS `5.6.2`, build `21`. Keep the output private. An HBC icon or an open port alone does not establish root or firmware compatibility.

The pinned HBC startup has a placeholder SSH password when `authorized_keys` is absent; merely enabling SSH is **not hardened access**. Use your own public key and verify the next startup rather than relying on that password. Do not try passwords in an agent conversation.[4]

## 7. Complete SSH bootstrap without losing recovery

Return to the project root in a **second host terminal**. Retain telnet as the recovery transport until the independent SSH test succeeds; after an explicitly chosen reboot, reconnect it rather than expecting the old session to survive:

```sh
cd /PATH/TO/webos-under-the-hood
```

Follow [connection setup](connection.md) **from section 2 onward**. That page is part of this repository and gives the literal commands to:

1. Generate a dedicated host Ed25519 key without overwriting another key.
2. Take a TV-side checkpoint and append only the public entry, using short wrapped commands that also fit the embedded telnet console.
3. Only after the public-key file is provisioned, enable HBC's **SSH Server**, keep **Telnet** enabled and choose an approved normal startup. Reconnect the trusted telnet console after that restart, then obtain the TV's public host key, compare it with the host's `ssh-keyscan` candidate and pin the exact match. A scan alone is not verification.
4. Create the `lg-tv` SSH alias with strict host-key checking and confirm root/profile from a **new** key-authenticated SSH session.
5. Only then disable ordinary telnet. An owner-selected normal startup applies the persistent HBC preference; a flag file alone does not prove the current listener stopped.

Do not install a replacement SSH server, overwrite HBC's startup script, copy someone else's private key, delete existing authorized keys or disable the only working console.

After provisioning a key and choosing the later normal startup, HBC's startup no longer takes its absent-`authorized_keys` placeholder-password branch. This is source-described behavior, not proof that every other password-authentication path on a modified TV is closed. Verify your installed configuration; broader authentication hardening is a separate decision.[4]

## 8. Remove bootstrap exposure and continue through this repository

After independent SSH works, finish the telnet-disable procedure in [connection setup](connection.md#5-close-ordinary-telnet-only-after-successful-ssh), then check again from a fresh terminal after the chosen normal startup:

```sh
ssh lg-tv 'id; cat /etc/version'
python3 tvctl.py --target lg-tv audit --output .local-state/audit.json
```

Require the exact target profile. The audit is private and contains diagnostic information. Confirm the former SlopBro/simple-test host process has exited and its printed HTTP port is closed; keep only private evidence and remove any narrowly scoped temporary firewall exception you added. Leave the pairing file private, or delete **only that exact task-owned credential** locally if you do not want to reuse it; do not post its contents. No persistent SlopBro server or agent is required.

Now continue, without searching for another how-to:

1. [Choose and apply individual privacy changes](walkthrough.md), including explicit DNS-recipient approval and checkpoint/readback/rollback.
2. Optionally [hide YouTube's Home preview row](../optional-preview/README.md), without changing its icon, application or network access.
3. Optionally [replace the screensaver](../optional-screensaver/README.md), with separate mount, reload and boot-persistence decisions. [See real before/after images](screensavers.md).
4. [Verify and recover](recovery.md) after every chosen feature; retain private checkpoints. Physical cold-start, remote and playback checks are separate from offline tests.

## Troubleshooting without widening the blast radius

- **No HTTP response on the TV:** recheck the two selected addresses, the printed actual port, route, WSL NAT/client isolation and any narrowly scoped host firewall rule. A ping or successful SSH in the opposite direction is not sufficient.
- **No pairing prompt:** confirm the normal TV UI permits the expected LG Connect Apps/mobile-control pairing for this session, the chosen TV is on, and the pending request is yours. Do not use a pairing key from another TV or globally open a router port. An unexpected/unsupported UI is a stop, not a reason to spray versions.
- **TV reports HBC download/TLS failure:** fix the TV clock, DNS/reachability or trust conditions and inspect the partial-install state. This guide never falls back to disabling certificate verification or downloading an untrusted replacement IPK.
- **Root status `unelevated`, missing HBC, or failed install:** preserve the exact private error and target versions. Do not assume successful payload download means rooting completed; do not use a blanket reinstall/startup overwrite as recovery.
- **HBC settings changed but no port opened:** the pinned UI says a system reboot is needed. Schedule it explicitly; do not start random daemons or restart SAM.
- **Telnet refuses or times out after bootstrap:** if strict, key-authenticated SSH works, do not re-enable telnet as a shortcut. Refusal is evidence of a closed listener; a timeout alone is ambiguous. If no root access works, stop before toolkit writes.
- **Already-rooted/failsafe device:** do not reroot, clear failsafe flags or remove HBC to start over. Diagnose the particular state and retain its recovery route. This project's targeted overlay rollback is not an unrooter.

The source/operator history, this guide's offline checks, future live rooting, later toolkit installation and hosted CI are **different evidence levels**. Rooting is not automatically reversible just because the later QML overlays are.

## Sources

[1] https://raw.githubusercontent.com/throwaway96/slopbro/21023d56ca424607bb03d2939609cc658c655fc7/README.md
[2] https://raw.githubusercontent.com/throwaway96/slopbro/21023d56ca424607bb03d2939609cc658c655fc7/slopbro.py
[3] https://raw.githubusercontent.com/throwaway96/slopbro/21023d56ca424607bb03d2939609cc658c655fc7/wwwroot/autoroot.sh
[4] https://raw.githubusercontent.com/webosbrew/webos-homebrew-channel/92fcf9fef7ce08dbeae3b0616df8d0c75c11f0b3/services/startup.sh
[5] https://raw.githubusercontent.com/webosbrew/webos-homebrew-channel/92fcf9fef7ce08dbeae3b0616df8d0c75c11f0b3/frontend/views/SettingsPanel.js
[6] https://www.webosbrew.org/pages/sdk-configuration
