# Optional: moving-rings screensaver

This opt-in module replaces only the native webOS screensaver's two QML files with a lightweight moving-rings design. It is separate from the core toolkit and is **not installed, mounted, reloaded, or made persistent by default**. The YouTube/Home preview module is unrelated.

## Compatibility and limits

- The only pinned build is **20260421173614** (firmware 04.64.00, webOS 5.6.2-21 on the source OLED65CX6LA). The module refuses any other `/etc/version`, source hash, target path, mount state, or boot-hook contents. It does not claim support for other models or firmware.
- Requires an already-root-capable, pinned SSH alias, root access, the TV's existing Python 2.7 and standard mount utilities, and host Python 3.9+ plus Git/OpenSSH on a POSIX shell (Linux/macOS/WSL). This module does not configure SSH, root the TV, install software, contact a TV during generation, or use a network from `prepare.py`.
- `ScreenSaver.qml.tpl` is original project code; no vendor QML is tracked. The generator reads the two **owner-extracted** originals, checks their exact SHA-256 values, and changes only four unique geometry anchors in `MainView.qml`. Original copies and generated files stay under ignored `.local-state/` on the host and the dedicated runtime base on the TV.
- ScreenSaver properties `playing`, `liteMode`, `isPartial`, `guideString`, signal `looped`, and the 7500 ms animation/timer cadence are retained. The rings component does not render text.
- The public refactor and mocked lifecycle are offline-tested. The published visual template also passed 15 host Qt/OpenGL render/lifecycle checks; generated Python helpers were imported and exercised through `--help` and no-argument refusal in a network-disabled Python 2.7.18 container. Neither is the TV's embedded 2.7.15 or native Qt/SAM stack. The original moving-rings visual was rendered on the source CX during private development, but **this generated public package has not been installed on a TV**. Public runtime behavior, physical remote operation, full playback, cold-boot ordering and other builds remain unverified.

Do not proceed if a firmware/source hash differs, a target is absent or symlinked, a mount/hook is foreign, stacked, writable or otherwise unexpected, or another administrator is changing TV state. Do not use a force option (none exists). Arrange an owner-controlled **exclusive maintenance window** for apply, reload, boot-hook changes and rollback.

## 1. Extract the two originals locally

Start from the repository root. Set `TV` to an existing SSH alias whose host key is already pinned and whose authorized root-capable access is already configured. Do not put an IP, password, key, or private diagnostics in the repository. The commands below transfer only the two named source files to your host; they do not write to the TV.

```sh
python3 --version                 # 3.9 or newer

git check-ignore -q --no-index -- .local-state/.screensaver-check \
  || { printf '%s\n' 'STOP: .local-state is not ignored'; exit 1; }
umask 077
mkdir -p .local-state
chmod 700 .local-state
export TV='YOUR_EXISTING_PINNED_ROOT_SSH_ALIAS'
SOURCE=.local-state/screensaver-source
mkdir -m 700 "$SOURCE"           # Refuses an existing source directory.

(set -C; ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes \
  -o IdentitiesOnly=yes -o ForwardAgent=no -o ClearAllForwardings=yes \
  -o ConnectTimeout=8 -o ConnectionAttempts=1 "$TV" \
  'cat /usr/palm/applications/com.webos.app.screensaver/qml/Containers/ScreenSaver.qml' \
  > "$SOURCE/ScreenSaver.qml")
(set -C; ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes \
  -o IdentitiesOnly=yes -o ForwardAgent=no -o ClearAllForwardings=yes \
  -o ConnectTimeout=8 -o ConnectionAttempts=1 "$TV" \
  'cat /usr/palm/applications/com.webos.app.screensaver/qml/Containers/MainView.qml' \
  > "$SOURCE/MainView.qml")
sha256sum "$SOURCE/ScreenSaver.qml" "$SOURCE/MainView.qml"
```

The expected hashes are checked by the generator; they are also recorded in the generated manifest. If either transfer fails or a destination appeared, stop and inspect the partial local files rather than overwriting them. Keep `.local-state/` private and do not publish the originals.

## 2. Generate the local package (no device changes)

```sh
OUT="$(mktemp -d .local-state/screensaver-build.XXXXXX)"
rmdir "$OUT"                    # The generator requires a fresh destination.
python3 optional-screensaver/prepare.py \
  --source-dir "$SOURCE" --output-dir "$OUT"
python3 - "$OUT" <<'PY'
import hashlib
from pathlib import Path
import sys
base = Path(sys.argv[1])
for name in ('ScreenSaver.original.qml', 'ScreenSaver.patched.qml',
             'MainView.original.qml', 'MainView.patched.qml'):
    print(hashlib.sha256((base / name).read_bytes()).hexdigest(), name)
PY
```

Review `manifest.json`, the four QML hashes, and the exact patch description. Generation refuses unknown originals, missing/duplicate geometry anchors, an output path outside `.local-state/`, symlinks, an existing output directory, or a `.local-state/` path Git does not ignore. It has no SSH, Luna, mount, reload, or boot-hook code path. `--help` and invalid/no-argument invocation are local-only and do not create output.

## 3. Install (stage) package files explicitly

This is the first TV write and is separately acknowledged. Before writing, the host tool uses a read-only preflight to require root access, the pinned `/etc/version` build, regular non-symlink native QML targets, and both exact original SHA-256 pins. Only then does it create the dedicated runtime directory and stage the nine generated package files; it does not mount QML, install the persistent boot hook, or reload the app. The host tool uses `ssh -T` with batch mode, strict host-key checking, identities-only, forwarding disabled, and transfers each file through binary stdin. It refuses a pre-existing runtime base, uses no SCP/SFTP, then reads back every remote SHA-256 against the same validated in-memory byte snapshot used for transfer; it does not reopen mutable local package files as the upload or readback authority. `--check` is local-only and makes no SSH connection.

```sh
python3 -B optional-screensaver/install.py --package-dir "$OUT" --check
python3 -B optional-screensaver/install.py --package-dir "$OUT" \
  --target-alias "$TV" --install --ack-install
```

The alias must be an existing pinned SSH config alias, not an IP/user string. Confirm the result reports `staged: true`, `network_used: true`, `verified_file_count: 9`, `apply_performed: false`, `reload_performed: false`, `visible_rendering_verified: false`, and `boot_hook_installed: false`. Staging is not an overlay apply or a rendering test. A failed transfer may leave partial files; stop and inspect the exact base before retrying. Do not merge into or replace an existing package. Retain all package files and checkpoints during operation and recovery.

## 4. Check, then apply the two read-only binds

These check commands are read-only. Set the fixed runtime base once in the same host shell (it is not an editable target selector). The runtime checks the pinned build, package hashes, exact target paths, original contents or owned mount instances, and read-only state. No check installs the hook or reloads the app.

```sh
BASE=/var/lib/webosbrew/screensaver-override
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" \
  "python '$BASE/overlay_runtime.py' --check"
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" \
  "python '$BASE/manage_boot_hook.py' --check"
```

Proceed only if both QML targets report `original`, the hook is absent or exactly owned, and the package/build checks pass. Then explicitly request the mounts:

```sh
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" \
  "python '$BASE/overlay_runtime.py' --apply --ack-mount"
```

Apply first creates private, exclusive original-file checkpoints under `$BASE/checkpoints/`, then binds only `ScreenSaver.qml` and `MainView.qml` read-only. Apply, rollback and check take a nonblocking kernel `flock` on the existing mode-0700 runtime directory; contention reports **busy** without a second mutation, and check creates no lock file. The lock coordinates this package's helpers, not a non-cooperating administrator: the exclusive maintenance window remains necessary.

Before binding, an fsynced private `$BASE/lifecycle.json` records the boot ID and the exact source/original inode identities; bound/read-only phases additionally record the observed mount ID. Verified ownership is committed separately in `$BASE/active.json`. The runtime refuses foreign, stacked, nested, changed or unowned mounts. During interrupted-apply recovery it may detach a still-writable **exact journaled bind** created before the read-only remount; it does not generalize that permission to writable mounts. No lazy unmount is used. Review the JSON result and require both targets to be `owned-ro` before reloading.

## 5. Reload only the native screensaver (separate acknowledgement)

A file bind does not replace QML already loaded in a running process. Reload is a distinct disruptive step. Use it only during the approved maintenance window, preferably while the native screensaver is visible. Preflight checks the expected owned mounts, reads and validates both native SAM schemas before close, uses bounded PTY-backed `luna-send`, and controls only `com.webos.app.screensaver`. Its exact `qml-runner` fallback checks app ID, main-QML path, PID and process start time, and sends `TERM` only to that verified process. It never kills other apps, restarts SAM, deletes snapshots, or escalates to `KILL`.

```sh
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" \
  "python '$BASE/reload_screensaver.py' --ack-native-screensaver-reload"
```

The tool verifies a fresh native screensaver process, rejects a restored snapshot, and checks that the foreground and preexisting other-app identities are unchanged. If a failure occurs after close, it makes one bounded recovery launch attempt when no screensaver process remains, then exits nonzero with the observed state. A nonzero result does **not** mean the original view was restored; inspect it and use the recovery procedure below. Test the visible rings and normal TV navigation manually with the remote. This step is not a playback or burn-in test.

## 6. Optional boot persistence (mounts only)

Do this only after successful screen QA and a separate decision to accept persistent boot-time mounts. The manager refuses a foreign hook and installs only the exact generated bytes at `/var/lib/webosbrew/init.d/65-screensaver-override`. Its hook mounts the two verified files only: it does **not** restart or launch the screensaver. Boot ordering and a physical cold start have not been tested for this public package.

```sh
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" \
  "python '$BASE/manage_boot_hook.py' --install --ack-install"
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" \
  "python '$BASE/manage_boot_hook.py' --check"
```

Generation, staging, one-time apply and reload do not install persistence. The init hook is separate from native screensaver reload; after a boot, allow normal OS/app startup and perform a separately approved reload if the screensaver is already running with old QML. Do not infer boot ordering from a same-session test.

## Interrupted apply and recovery

`--check` never repairs state: if `$BASE/lifecycle.json` remains, it refuses and asks for an explicitly acknowledged apply or rollback. Preserve the package, checkpoint, `active.json` and journal; do not delete/edit them to make a check pass. In an exclusive approved window, choose the rollback procedure below to return to originals, or repeat section 4's acknowledged apply to recover then retry. Recovery validates boot/source/original identities, rejects stacked or mismatched mounts, and preserves a fully verified committed overlay when only journal cleanup was interrupted. The tiny crash window before a mount ID is recorded is handled only by matching the exact private source inode, original target identity and one target bind; this depends on the exclusive administrator window, not protection against a malicious root user.

SIGTERM/KeyboardInterrupt request checked cleanup after the active mount/umount child returns; completion is not instantaneous. SIGKILL, power loss or filesystem failure cannot promise cleanup. A later acknowledged operation uses the durable record; after a boot it retires old intent only when the unchanged original targets are visible. A refusal/nonzero exit may preserve partial state and evidence for diagnosis. Do not force an unmount or automatically reboot.

## Rollback and recovery

Rollback is explicit. It first creates an exact disable marker so an installed hook cannot reapply the overlay, preflights both targets, then detaches only verified, single, read-only mounts whose boot ID, mount IDs and source/target inodes match the recorded ownership. It retains package files and original checkpoints. It does not reload or claim that the old QML has been loaded into the running process.

```sh
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" \
  "python '$BASE/overlay_runtime.py' --rollback --ack-rollback"
```

Require both targets to report `original` and `future_apply_disabled: true`. Then, as a **separate** native screensaver-only reload decision, load the original firmware implementation:

```sh
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" \
  "python '$BASE/reload_screensaver.py' --original --ack-native-screensaver-reload"
```

If the boot hook was installed, remove only its exact owned bytes after rollback:

```sh
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" \
  "python '$BASE/manage_boot_hook.py' --remove --ack-remove"
```

Keep the source files, generated package and checkpoints until the original screensaver is visibly running and no process can retain old QML file descriptors. Do not delete the runtime base as a cleanup shortcut.

### If a check or reload fails

- On any unknown hash/build, foreign/stacked/writable mount, target symlink, foreign hook, unexpected checkpoint, or identity drift: stop. Do not force-unmount, overwrite, re-run an installer blindly, or modify the guard.
- Keep the existing SSH session. Run `overlay_runtime.py --check` and `manage_boot_hook.py --check` again and preserve their exact private output. A successful detach alone does not prove the original UI is active.
- If the reload reports that it could not establish a fresh screensaver, it attempts a bounded relaunch only when no screensaver process remains. Do not immediately repeat reload. Inspect the process/mount checks; use the explicit rollback and `--original` reload commands above if you choose to abandon the feature.
- If native recovery also fails, leave package and checkpoints intact and stop. Do not restart SAM, kill a process by name, delete CRIU state, reboot, or claim recovery without a fresh visible/readback check.
- Lazy detachment is never requested. Retain all source files until the native app is confirmed reloaded; an old process may keep file descriptors open.

## Offline tests

From the repository root, run:

```sh
python3 -B -m unittest discover -s tests -p 'test_optional_screensaver.py' -v
python3 -B -c "from pathlib import Path; files=[Path('optional-screensaver/prepare.py'), Path('optional-screensaver/install.py'), *Path('optional-screensaver/templates').glob('*.tpl'), Path('tests/test_optional_screensaver.py')]; [compile(p.read_text(encoding='utf-8'), str(p), 'exec') for p in files if p.suffix == '.py' or p.name.endswith('.py.tpl')]"
```

The tests use synthetic source bytes, fake mount tables, mocked native RPC/process state and temporary files. They never contact a TV or network. POSIX-only permission/symlink cases skip on Windows; package generation and template syntax checks remain portable. The suite cannot validate Qt rendering, the real device's SAM schemas, root QML arguments, physical remote behavior, cold-boot ordering or full playback.
