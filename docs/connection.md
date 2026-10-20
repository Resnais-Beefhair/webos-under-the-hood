# Connection and recovery setup

These are **owner-approved authentication/security changes**, not things an agent may infer permission to do. Read [compatibility](compatibility.md) first. This page starts with HBC and a trusted root console; the [complete rooting and first-console guide](rooting.md) supplies those steps if you are starting from an unrooted TV. Do not factory-reset or guess credentials to skip that prerequisite.

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

Homebrew Channel's source uses `/var/luna/preferences/webosbrew_sshd_enabled` to enable its SSH server and `/home/root/.ssh/authorized_keys` for user keys.[3] Inspect the installed version before assuming the same paths. **On a fresh bootstrap, keep SSH disabled until section 2 has provisioned the public-key file.** Enabling it earlier exposes HBC's placeholder-password root login. If an inherited installation already exposes SSH without keys, treat that as an existing security issue; do not disable your only working console blindly. Do not start an unverified server or schedule a reboot automatically.

## 2. Create a dedicated client key on your host

```sh
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
ssh-keygen -t ed25519 -a 64 -f "$HOME/.ssh/lg_tv_ed25519" -C lg-tv-admin
```

Do not overwrite an existing file. Choose a passphrase if appropriate. To unlock the key for the later `BatchMode` commands, run this on your host and enter any passphrase **only in your local terminal**:

```sh
ssh-add "$HOME/.ssh/lg_tv_ed25519"
```

If there is no running SSH agent, run `ssh-agent sh` to open an agent-managed shell, repeat `ssh-add` inside it, and perform the remaining host commands in that shell. Type `exit` when finished; that command-managed agent exits with its shell. Reuse an existing desktop agent when available; do not stop another session's agent. If the key remains locked, batch commands fail; do not remove the passphrase automatically or fall back to a password.

The file ending in `.pub` is the **public** half. Some embedded telnet consoles truncate long input lines; do not paste a long authorized-key line into one. On your host, generate short shell commands that assemble the restricted public entry locally in the TV shell. Each generated line is at most 78 characters:

```sh
python3 - <<'PY'
import base64
from pathlib import Path
parts = (Path.home() / '.ssh/lg_tv_ed25519.pub').read_text().split()
assert len(parts) >= 2 and parts[0] == 'ssh-ed25519'
wire = base64.b64decode(parts[1], validate=True)
assert len(wire) == 51 and wire[:19] == b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20'
entry = 'no-port-forwarding,no-agent-forwarding,no-X11-forwarding ' + ' '.join(parts[:2])
commands = ["k=''"]
commands += ['k="${k}' + entry[i:i+55] + '"' for i in range(0, len(entry), 55)]
commands += ["printf '%s\\n' \"$k\" >> /home/root/.ssh/authorized_keys", 'unset k']
assert all(len(line) <= 78 for line in commands)
print('\n'.join(commands))
PY
```

Keep that output local; it contains **only public-key data**, not your private key. Do not send it to an agent, issue or public chat. On the trusted TV console, create a unique private checkpoint first (do not replace existing entries):

```sh
(
set -eu
umask 077
mkdir -p /var/lib/webosbrew/backups
BACKUP=/var/lib/webosbrew/backups/ssh-bootstrap-$(date +%Y%m%d-%H%M%S)
mkdir "$BACKUP"                 # A collision stops this entire block.
chmod 700 "$BACKUP"
if [ -e /home/root/.ssh/authorized_keys ]; then
    cp -p /home/root/.ssh/authorized_keys "$BACKUP/authorized_keys.before"
else
    touch "$BACKUP/authorized_keys.was-absent"
fi
mkdir -p /home/root/.ssh
chmod 700 /home/root/.ssh
printf 'Checkpoint: %s\n' "$BACKUP"
)
```

Now paste the **generated short commands** into that TV console, one line at a time, waiting for the prompt after each line. Start with `k=''` and finish with `unset k`. The generated `printf` appends one key entry; run it only once, and do not paste a raw key or an interactive `cat` recipe. Then secure the file:

```sh
chmod 600 /home/root/.ssh/authorized_keys
test -s /home/root/.ssh/authorized_keys && printf 'Public-key file present\n'
```

Require the final confirmation and successful completion of every generated command. Do not run this blindly on a different layout. The toolkit does not read or export your authorized-keys file.

### Enable SSH only after public-key provisioning

For the fresh HBC bootstrap, now open **HBC Settings → Root configuration**, enable **SSH Server**, leave **Telnet enabled** for recovery, and use **System reboot** only in the owner-approved window. This normal startup sees the existing public-key file instead of installing the placeholder password. Do not claim that merely appending a key changes a password already active in the current boot. After the TV returns, reconnect `telnet "$TV_IP" 23`, recheck `id` and the profile, and keep that trusted console available for section 3 and recovery. The old session does not survive the reboot; the telnet service remains available until section 5. An already functioning, trusted key-authenticated SSH setup does not need this bootstrap restart.

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

If that export tool is unavailable, the included `tools/hostkey_public.py` provides a complete short-line fallback. From the **project root on your host**, generate the transfer/run/cleanup commands below. This reads only the public project script, not a key. Keep the generated output local and paste its lines into the existing trusted TV console, in order; the embedded `PY` lines delimit a short Python program, not an interactive `cat` prompt:

```sh
python3 - <<'PY'
import base64, hashlib
from pathlib import Path
payload = Path('tools/hostkey_public.py').read_bytes()
digest = hashlib.sha256(payload).hexdigest()
encoded = base64.b64encode(payload).decode('ascii')
commands = [
    'umask 077', 'd=$(mktemp -d /tmp/webos-key.XXXXXX)',
    '[ -n "$d" ] || exit 1', 'printf "%s\\n" "$d"',
    'f="$d/hostkey_public.py"', 'export f',
    "h='" + digest[:32] + "'", 'h="${h}' + digest[32:] + '"', 'export h',
]
commands += ["printf '%s' '" + encoded[i:i+32] + "' >> \"$f.b64\""
             for i in range(0, len(encoded), 32)]
commands += [
    "python - <<'PY'", 'import os, base64, hashlib',
    "p = os.environ['f']", "b = base64.b64decode(open(p+'.b64','rb').read())",
    "assert hashlib.sha256(b).hexdigest() == os.environ['h']",
    "with open(p, 'wb') as out: out.write(b)", 'PY',
    'h=/var/lib/webosbrew/sshd/dropbear_ed25519_host_key',
    'python "$f" --export-public "$h"',
    'rm -f -- "$f" "$f.b64"', 'rmdir "$d"', 'unset d f h',
]
assert all(len(line) <= 78 for line in commands)
print('\n'.join(commands))
PY
```

The decoder checks SHA-256 before writing/running the helper. The final commands remove only that newly created temporary directory's two named files, not HBC state or host keys. If interrupted, retain the exact task directory printed on its own line in that same TV console and remove only those task-owned files once diagnosed. Stop on any error; do not paste this into an untrusted or different session.

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

**Simple manual path for a new bootstrap:** after the new key-authenticated session has passed, open HBC Settings, switch **Telnet** off, leave **SSH Server** on, and choose **System reboot** only in the owner's approved window. This applies HBC's persistent preference and avoids guessing a listener PID. Do not do it before proving the new key and retaining the checkpoint. After the TV returns, establish another strict SSH session and test the ordinary telnet port from the host:

```sh
TV_IP=REPLACE_WITH_YOUR_TV_IP
ssh lg-tv 'id; cat /etc/version'
python3 - "$TV_IP" <<'PY'
import socket, sys
try:
    connection = socket.create_connection((sys.argv[1], 23), timeout=3)
except ConnectionRefusedError:
    print('Ordinary TCP/23 listener refused: closed at this check')
except OSError as error:
    raise SystemExit('Ambiguous network result; STOP and inspect: ' + str(error))
else:
    connection.close()
    raise SystemExit('TCP/23 is still open; STOP and inspect, do not claim it closed')
PY
```

This is a single selected TV, not a network scan. A timeout is not converted into a successful closure report.

From the host, test port 23 **on your chosen TV only**, then verify another new SSH session. Connection **refused** is evidence of a closed TCP listener; a timeout is ambiguous. HBC emergency/failsafe behavior may intentionally open telnet independently and was not modified. Do not advertise SSH or telnet to the Internet or enable router port forwarding.

## Recovery

If the new SSH key or host pin fails, keep the existing trusted session and correct the new entry/configuration; do not remove the old keys or disable telnet. If a key is later revoked, remove only the exact entry you added, with a checkpoint and working alternative. Never restore an entire old authorized-keys file over someone else's newer change.
