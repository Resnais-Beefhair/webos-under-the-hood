# Effective service masks, with a deliberate voice-feature trade-off

This feature stops **voiceinput** and preserves the existing **contentminer** mask. Voice input may stop working. Get the owner's approval, read [compatibility](compatibility.md), keep working SSH, and capture the current state first. Do not infer that every audio/recording path is covered.

The included shell payload is adapted from the source-device-tested hook. Its no-argument mode refuses; only `--apply-services` enables writes. The boot wrapper pins the exact tested `/etc/version` build. The public entry-point changes and these installation instructions were tested offline, not reinstalled on the running source TV.

## 1. Read-only preflight and checkpoint

```sh
mkdir -p .local-state
chmod 700 .local-state
python3 tvctl.py --target lg-tv audit --output .local-state/before-services.json
ssh lg-tv 'systemctl show voiceinput.service contentminer.service -p LoadState -p ActiveState -p UnitFileState'
ssh lg-tv 'cat /etc/version'
ssh lg-tv 'python -' <<'PY'
import os
p = "/etc/systemd/system/voiceinput.service"
print("regular unit file:", os.path.isfile(p) and not os.path.islink(p))
print([x.strip() for x in open("/proc/mounts") if x.split()[1] == p])
PY
```

The expected unit is an existing regular file, **not** a foreign symlink/mount. If any bind already covers that exact unit, or an old privacy hook exists, stop and inspect the existing implementation instead of stacking another one. In the source setup `contentminer` was already masked/inactive; it was not unmasked as a “reset”.

Capture the runtime links and unit digest privately, with no-overwrite output:

```sh
(set -C
ssh lg-tv 'python -' > .local-state/services-layers-before.json <<'PY'
from __future__ import print_function
import hashlib, json, os, stat
p = "/etc/systemd/system/voiceinput.service"
if not stat.S_ISREG(os.lstat(p).st_mode):
    raise RuntimeError("expected original regular unit, not a bind/symlink")
rows = [x.strip() for x in open("/proc/mounts") if x.split()[1] == p]
if rows:
    raise RuntimeError("an existing mount requires separate inspection")
links = {}
for name in ("voiceinput.service", "contentminer.service"):
    path = "/run/systemd/system/" + name
    if os.path.lexists(path) and not os.path.islink(path):
        raise RuntimeError("foreign runtime unit: " + name)
    links[name] = os.readlink(path) if os.path.islink(path) else None
    if links[name] not in (None, "/dev/null"):
        raise RuntimeError("foreign runtime link: " + name)
print(json.dumps({"runtime_links_before": links, "exact_mounts_before": rows,
    "unit_sha256": hashlib.sha256(open(p, "rb").read()).hexdigest(),
    "boot_id": open("/proc/sys/kernel/random/boot_id").read().strip()}, indent=2))
PY
)
```

If that command fails, its output file may be partial; keep/inspect it, do not treat it as a checkpoint. The installer below refuses an existing `50-privacy-services` or project directory rather than overwrite it. Never substitute a wildcard delete for that refusal. The payload also checks root/build, refuses foreign/stacked unit mounts and runtime links, and serializes its invocations with an exclusive directory lock under `/run/systemd/system`, not persistent project storage. A stale lock requires investigation, not blind deletion. Test-only environment path overrides are not a compatibility/force mechanism.

## 2. Explicitly opt in and stage original project files

These commands **write the TV**; do not run them as a preflight. They create a new namespaced directory and refuse an existing hook. The paths are not firmware partitions.

```sh
ssh lg-tv 'set -eu; test "$(id -u)" = 0; test "$(cat /etc/version)" = 20260421173614; test ! -e /var/lib/webosbrew/init.d/50-privacy-services; umask 077; mkdir /var/lib/webosbrew/privacy-services; chmod 700 /var/lib/webosbrew/privacy-services'
ssh lg-tv 'set -eu; set -C; umask 077; cat > /var/lib/webosbrew/privacy-services/privacy-services.sh' < services/privacy-services.sh
ssh lg-tv 'set -eu; set -C; umask 077; cat > /var/lib/webosbrew/privacy-services/50-privacy-services' < services/50-privacy-services.boot
ssh lg-tv 'set -eu; sh -n /var/lib/webosbrew/privacy-services/privacy-services.sh; sh -n /var/lib/webosbrew/privacy-services/50-privacy-services; sha256sum /var/lib/webosbrew/privacy-services/privacy-services.sh /var/lib/webosbrew/privacy-services/50-privacy-services'
python3 -c 'from pathlib import Path; import hashlib; [(print(hashlib.sha256(Path(p).read_bytes()).hexdigest(),p)) for p in ("services/privacy-services.sh","services/50-privacy-services.boot")]'
```

Compare **both** device hashes with the corresponding local payloads. Stop if either differs. An interrupted transfer is not a successful install; retain the private checkpoint and inspect only your new files before resuming.

The following creates a no-overwrite hard link for the persistent hook, on the same `/var/lib/webosbrew` filesystem. If that assumption is false, stop rather than work around it with a forced copy.

```sh
ssh lg-tv 'set -eu; chmod 755 /var/lib/webosbrew/privacy-services/privacy-services.sh /var/lib/webosbrew/privacy-services/50-privacy-services; ln /var/lib/webosbrew/privacy-services/50-privacy-services /var/lib/webosbrew/init.d/50-privacy-services; test -x /var/lib/webosbrew/init.d/50-privacy-services'
```

Installing the startup link is explicit consent to reapply these masks at each normal HBC startup. It does not request a reboot. Read [HBC startup guidance](sources.md) if your installed HBC differs.

## 3. Apply once, then read back

```sh
ssh lg-tv 'sh /var/lib/webosbrew/init.d/50-privacy-services'
ssh lg-tv 'systemctl show voiceinput.service contentminer.service -p LoadState -p ActiveState -p UnitFileState'
```

Require **both** `LoadState=masked` and `ActiveState=inactive`. The voice unit's `/dev/null` bind corrects the `/etc` precedence problem; the hook does not overwrite the firmware unit or the executable. Repeat the hook only to test idempotence in an approved window; the exact voice-unit mount count must stay one. Keep `sdx`, `admanager` and `voiceconductor` intact and compare your audit invariants.

Do not use `systemctl start voiceinput` as a casual test. The source implementation tried it only **after** proving the unit was effectively masked and checked that starting was refused. An incorrect mask could otherwise turn input back on.

## Rollback without enabling collection behind your back

First stop future reapplication by moving only the exact hook you installed into its own private directory, after comparing bytes/inode with your payload. Do not remove a different hook. Then detach only the exact `/dev/null` bind over `/etc/systemd/system/voiceinput.service` after checking a single mount, no nested mounts, and the target/source device+inode identity. Do not unmount storage or force a foreign mount. Run `systemctl daemon-reload` afterward, **not a service-manager restart**.

For the exact installation above, after reviewing your saved baseline, this guarded command disables the owned hook and detaches only that bind. It never starts/unmasks a service. An unexpected or busy mount is a refusal; do not add `-f` or `-l`.

```sh
ssh lg-tv 'python -' <<'PY'
from __future__ import print_function
import os, stat, subprocess
base = "/var/lib/webosbrew/privacy-services"
payload = base + "/50-privacy-services"
hook = "/var/lib/webosbrew/init.d/50-privacy-services"
disabled = base + "/50-privacy-services.disabled"
target = "/etc/systemd/system/voiceinput.service"
if os.getuid() != 0 or open("/etc/version").read().strip() != "20260421173614":
    raise RuntimeError("wrong user/build")
def identity(p):
    value = os.stat(p)
    return value.st_dev, value.st_ino
rows = [x.split() for x in open("/proc/mounts")]
exact = [x for x in rows if x[1] == target]
if len(exact) > 1 or any(x[1].startswith(target + "/") for x in rows):
    raise RuntimeError("stacked/nested mount")
if exact and identity(target) != identity("/dev/null"):
    raise RuntimeError("foreign unit mount")
if not os.path.lexists(hook):
    if not os.path.lexists(disabled) or identity(disabled) != identity(payload):
        raise RuntimeError("no owned hook or retained disabled-hook checkpoint")
if os.path.lexists(hook):
    if not stat.S_ISREG(os.lstat(hook).st_mode) or identity(hook) != identity(payload):
        raise RuntimeError("not this installation's exact hard-linked hook")
    os.link(hook, disabled)  # Fails on collision; retains a private checkpoint.
    if identity(hook) != identity(disabled):
        raise RuntimeError("hook changed during recovery")
    os.unlink(hook)
if exact:
    if identity(target) != identity("/dev/null"):
        raise RuntimeError("unit mount changed during recovery")
    subprocess.check_call(["umount", target])
subprocess.check_call(["systemctl", "daemon-reload"])
print("Owned startup hook disabled and unit bind absent; runtime masks retained.")
PY
```

The hook does not change the original unit bytes, so the original becomes visible again. Existing runtime masks are a separate layer: restore only the runtime link/state changes actually owned by this installation, using your pre-change record. In particular, do **not** unmask `contentminer` if it was already masked beforehand. Disabling the boot hook does not automatically start voice input or collection in the current session.

There is intentionally no “enable every service” reset. If you need voice input restored, compare the checkpoint, explicitly choose that behavior and restore only the relevant original unit/runtime state. A cold boot is a separate owner-scheduled action, not an automatic rollback step.

Only if `runtime_links_before.voiceinput.service` was **null**, the current runtime link is `/dev/null`, and no other administrator changed it, restoring that previously absent runtime link means:

```sh
ssh lg-tv 'systemctl unmask --runtime voiceinput.service; systemctl daemon-reload; systemctl show voiceinput.service -p LoadState -p ActiveState -p UnitFileState'
```

Do not run that command if the link already existed. Keep the pre-existing contentminer mask; if yours was genuinely created by this installation, review its separate before-record before considering an unmask. Starting a previously active service is another explicit functional choice, not an implicit consequence of rollback.
