# Connection and recovery setup

These are **owner-approved authentication/security changes**, not things an agent may infer permission to do. Read [compatibility](compatibility.md) first. Start from an already-rooted TV with Homebrew Channel and a trusted working root console or management session. If you have neither, stop and read [rooting background](rooting.md); do not factory-reset or guess credentials.

All shell examples below are for Linux/macOS/WSL. Replace placeholders locally. Never paste a private key, password, pairing key or authorized-key line into an issue or agent conversation.

## 1. Identify the TV without scanning the household

Read the Ethernet address from the TV's network settings or your own router's device page. Record it privately. Verify the model and firmware in the TV UI. The documented source was an Ethernet-connected OLED65CX6LA; Wi-Fi was already off and was not changed.

From the **existing trusted TV root console**, check:

```sh
id
cat /etc/version
cat /var/run/nyx/os_info.json
```

Do not publish the raw results. The supported build is `20260421173614`, firmware `04.64.00`, release `5.6.2`, build `21`. Stop on a different profile.

Homebrew Channel's source uses `/var/luna/preferences/webosbrew_sshd_enabled` to enable its SSH server and `/home/root/.ssh/authorized_keys` for user keys.[3] Inspect the installed version before assuming the same paths. If SSH is not enabled, use HBC's documented controls or an existing trusted root console; setting the enable flag is a separate authentication decision and may require a later approved normal startup. Do not start an unverified server or schedule a reboot automatically.

## 2. Create a dedicated client key on your host

```sh
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
ssh-keygen -t ed25519 -a 64 -f "$HOME/.ssh/lg_tv_ed25519" -C lg-tv-admin
```

Do not overwrite an existing file. Choose a passphrase if appropriate and load the key into your OS's SSH agent for batch operation. If the key remains locked, later `BatchMode` commands fail; do not automatically remove the passphrase or fall back to a password.

The file ending in `.pub` is the **public** half. On your host, create a restricted public entry:

```sh
python3 -c 'from pathlib import Path; p=Path.home()/".ssh/lg_tv_ed25519.pub"; parts=p.read_text().split(); assert parts[0]=="ssh-ed25519"; print("no-port-forwarding,no-agent-forwarding,no-X11-forwarding "+" ".join(parts[:2]))'
```

Keep that output local. On the trusted TV console, create a unique private checkpoint, then append the one new entry (do not replace existing entries):

```sh
umask 077
mkdir -p /var/lib/webosbrew/backups
BACKUP=/var/lib/webosbrew/backups/ssh-bootstrap-$(date +%Y%m%d-%H%M%S)
mkdir "$BACKUP"                 # Refuses a collision instead of overwriting it.
chmod 700 "$BACKUP"
if [ -e /home/root/.ssh/authorized_keys ]; then
    cp -p /home/root/.ssh/authorized_keys "$BACKUP/authorized_keys.before"
else
    touch "$BACKUP/authorized_keys.was-absent"
fi
mkdir -p /home/root/.ssh
chmod 700 /home/root/.ssh
cat >> /home/root/.ssh/authorized_keys
```

Paste **only the one restricted PUBLIC entry**, press Enter, then Ctrl+D. Wait for the console prompt to return. Do not paste the next command into `cat`.

```sh
chmod 600 /home/root/.ssh/authorized_keys
```

Do not run this blindly on a different layout. Retain the original management session until the independent test below passes. The toolkit does not read or export your authorized-keys file.

## 3. Pin the server host key, independently

`ssh-keyscan` retrieves a key; it does **not authenticate it**. On the host:

```sh
TV_IP=REPLACE_WITH_YOUR_TV_IP
ssh-keyscan -T 5 -t ed25519 "$TV_IP" > "$HOME/.ssh/lg_tv_known_hosts.candidate"
ssh-keygen -lf "$HOME/.ssh/lg_tv_known_hosts.candidate"
```

Compare the type/public key or fingerprint with a value obtained over the **existing trusted TV console**. Prefer the upstream tool when installed:

```sh
dropbearkey -y -f /var/lib/webosbrew/sshd/dropbear_ed25519_host_key
```

If that export tool is unavailable on the source-style HBC layout, `tools/hostkey_public.py` is a small device-side fallback. Transfer/paste only that script through your trusted console, then run:

```sh
python /tmp/hostkey_public.py --export-public /var/lib/webosbrew/sshd/dropbear_ed25519_host_key
```

It understands only the tested Dropbear Ed25519 container: it reads its header, **seeks past the private seed without reading it**, and exports only the public half. It never dumps the file. On an unknown format it refuses. Do not replace it with `cat`/hex/base64 of a host-key file, and do not share its output publicly. Verify the exported public key matches the candidate exactly. A trusted console is necessary; a second unauthenticated scan is not independent evidence.

Only after a match, promote the candidate without overwriting a different existing pin:

```sh
test ! -e "$HOME/.ssh/lg_tv_known_hosts" && mv "$HOME/.ssh/lg_tv_known_hosts.candidate" "$HOME/.ssh/lg_tv_known_hosts"
chmod 600 "$HOME/.ssh/lg_tv_known_hosts"
```

If the final pin already exists, compare and investigate rather than deleting it or accepting a changed key.

## 4. Add your SSH alias and test a NEW session

Append a dedicated block to your local `~/.ssh/config` (replace the placeholder, preserve other entries):

```sshconfig
Host lg-tv
    HostName REPLACE_WITH_YOUR_TV_IP
    User root
    IdentityFile ~/.ssh/lg_tv_ed25519
    UserKnownHostsFile ~/.ssh/lg_tv_known_hosts
    StrictHostKeyChecking yes
    IdentitiesOnly yes
    BatchMode yes
    ForwardAgent no
    ForwardX11 no
    ClearAllForwardings yes
    ConnectTimeout 5
```

Protect the config with mode `600`. From a new terminal, not the bootstrap session:

```sh
ssh lg-tv 'id; cat /etc/version'
python3 tvctl.py --target lg-tv audit --output .local-state/audit.json
```

Check root identity and the expected profile. This does not prove that every possible password-login path is disabled. The historical initial setup reported disabling its default SSH password; this toolkit did not independently reconfigure password authentication. Review your installed server's actual authentication policy, separately and with recovery, if you need to change it.

## 5. Close ordinary telnet only after successful SSH

The HBC normal-startup flag is:

```sh
ssh lg-tv 'umask 077; touch /var/luna/preferences/webosbrew_telnet_disabled; test -f /var/luna/preferences/webosbrew_telnet_disabled'
```

This persists the preference; it does not prove an already-running listener exited. In the tested implementation only the HBC `telnetd` listener at `/media/developer/apps/usr/palm/services/org.webosbrew.hbchannel.service/bin/telnetd` was sent `TERM` after executable verification. Never use `killall`, kill a client shell or target an unrelated daemon. Check the exact PID, executable and start time before signaling; if uncertain, keep the flag and arrange a separately approved normal startup rather than guessing.

From the host, test port 23 **on your chosen TV only**, then verify another new SSH session. Connection **refused** is evidence of a closed TCP listener; a timeout is ambiguous. HBC emergency/failsafe behavior may intentionally open telnet independently and was not modified. Do not advertise SSH or telnet to the Internet or enable router port forwarding.

## Recovery

If the new SSH key or host pin fails, keep the existing trusted session and correct the new entry/configuration; do not remove the old keys or disable telnet. If a key is later revoked, remove only the exact entry you added, with a checkpoint and working alternative. Never restore an entire old authorized-keys file over someone else's newer change.
