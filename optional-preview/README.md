# Optional: suppress the YouTube Home preview

This optional, reversible customization empties only the **main YouTube app launchpoint's Home preview model**. It does not change the YouTube app, its icon, playback, channel launchpoints, or other apps, and does not block YouTube telemetry; it only removes those Home preview cards. It is independent of the repository's core CLI and is not installed or enabled by default.

## Support and limits

- Tested target: LG OLED65CX6LA, firmware 04.64.00, webOS 5.6.2-21.
- The source must be the exact unmodified `Interfaces.qml` at `/usr/palm/applications/com.webos.app.home/qml/Controllers/PreviewInterfaces/Interfaces.qml`, SHA-256 `d0aa864876562529de9a15e6071d5deb7e11c93b97acaadebadb0ca946790bb5`.
- The known patched output SHA-256 is `a6ab3df9ca1470e673db4905c7dc4a4173f9dad5e1b4045fe00fef0297af980a`. Any input hash mismatch, missing/duplicate function anchor, foreign mount, stacked/nested mount, or foreign boot hook is a hard refusal. There is no force override.
- Requires an already-root-capable, authenticated SSH alias with a valid known host key, existing Homebrew Channel (HBC) boot support, Python 2.7 on the TV, and Python 3.9+ on the host. This tool does not configure SSH/authentication, install HBC, or change host keys. The TV's existing Python 2.7 does not have `runpy`; the generated scripts do not use it.
- This refactor is offline-tested. Earlier integration work exercised the original guard, mount lifecycle, rollback, Home reload, hidden reload and boot invocation simulation on the stated device. See the [validation record](../docs/validation.md) for later read-only public-tool checks. Physical cold-boot ordering, full playback and other models/firmware are not established by this package.

The added guard is the same tiny early return used by the tested customization. No LG firmware QML is tracked or distributed from this repository. The original and generated patched QML exist only in the reader's ignored `.local-state` output and (after manual staging) on the TV. Nothing downloads vendor firmware or overwrites its file: the patch is exposed through an exact read-only bind mount. The two Home checkpoint paths are also read-only binds to a retained empty directory; no CRIU snapshot is deleted or globally changed.

Both checkpoint targets must already exist as real directories. A missing target now causes a hard refusal with each checkpoint/UI mount state reported; it is never silently skipped or created. The public boot/recovery changes below are offline-tested, not hardware-qualified.

## Prepare locally (no TV mutation)

Run from the repository root and keep the same shell open for the command blocks below so `TV`, `BASE`, and `OUT` retain their values. Set `TV` to an **existing** SSH alias that already has the necessary authorized root-capable access; do not disable host-key checks. These commands only extract the exact source and create a local bundle. `.local-state` must be ignored by Git before proceeding because the local bundle includes the proprietary original QML as a private recovery copy.

```sh
git check-ignore -q .local-state || { printf '%s\n' 'STOP: .local-state is not ignored'; exit 1; }
export TV='EXISTING_ROOT_CAPABLE_SSH_ALIAS'
BASE=/var/lib/webosbrew/home-preview-override
umask 077
mkdir -p .local-state
SOURCE=.local-state/Interfaces.qml
test ! -e "$SOURCE"
(set -C; ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" \
  'cat /usr/palm/applications/com.webos.app.home/qml/Controllers/PreviewInterfaces/Interfaces.qml' > "$SOURCE")
OUT="$(mktemp -d .local-state/youtube-home-preview.XXXXXX)"
rmdir "$OUT"
python3 optional-preview/prepare.py --source "$SOURCE" --output-dir "$OUT"
sha256sum "$OUT/Interfaces.original.qml" "$OUT/Interfaces.patched.qml"
```

`prepare.py` checks the pinned original checksum and one exact `getAppPreview(launchPoint)` anchor, then writes a manifest, original/patched files, the generated runtime/reload/rollback tools and a disabled boot-hook wrapper. It refuses an existing output path or any location outside `.local-state`. Inspect the manifest and printed hashes. Keep the entire output directory private; do not attach it to an issue or publish it.

## Stage the package (explicit device file writes)

The following commands write package files to the TV but do not install a mount or reload Home. Review the destination and make this a deliberate step. They refuse an existing runtime base rather than replacing it.

```sh
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" \
  "set -eu; test ! -e '$BASE'; mkdir -m 700 '$BASE'"
for name in Interfaces.original.qml Interfaces.patched.qml manifest.json \
            preview_runtime.py reload_home.py rollback_preview.py \
            manage_boot_hook.py home-preview-boot-hook.sh; do
  ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" \
    "set -eu; set -C; umask 077; cat > '$BASE/$name'" < "$OUT/$name" || exit 1
done
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" \
  "set -eu; chmod 600 '$BASE/Interfaces.original.qml' '$BASE/manifest.json'; chmod 644 '$BASE/Interfaces.patched.qml'; chmod 700 '$BASE/'*.py '$BASE/home-preview-boot-hook.sh'; mkdir -m 555 '$BASE/empty-checkpoint'; sha256sum '$BASE/Interfaces.original.qml' '$BASE/Interfaces.patched.qml'"
```

These binary-safe SSH stdin transfers do not require an SFTP server or modern SCP support on the TV. Compare both TV hashes with the local `sha256sum` output. Keep `Interfaces.original.qml`, `Interfaces.patched.qml`, and `empty-checkpoint` in place while the feature is active and while Home/SAM may retain open file descriptors. Never clean up the runtime base as part of rollback.

## Check, then opt in

These are separate steps. Check-only commands do not mount or reload Home. The reload preflight reads Home's running-app state and native schemas but does not establish activation. Read-only/no-action helper imports suppress bytecode writes too.

Arrange an owner-controlled exclusive administration window for mounts, hook changes, reload and rollback: no concurrent root mount writer or competing toolkit run. Ownership checks use exact target, source inode and read-only state, not an atomic mount-instance token; they cannot distinguish a same-inode mount replaced by another root writer between check and detach. Stop on observed drift rather than treating preflight as transaction isolation.

```sh
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" \
  "python '$BASE/preview_runtime.py' --check"
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" \
  "python '$BASE/manage_boot_hook.py' --check"
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" \
  "python '$BASE/reload_home.py' --preflight"
```

After reviewing those results, the next command explicitly requests the reversible Home-only read-only binds. It does not reload Home:

```sh
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" \
  "python '$BASE/preview_runtime.py' --apply --ack-mount"
```

Review the mount result before continuing; a mount does not replace code already mapped into Home, so a still-unchanged UI is not itself a failure. A Home reload is a separate disruptive action, so perform it only after a separate human decision:

```sh
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" \
  "python '$BASE/reload_home.py' --hidden --ack-home-reload"
```

Before closing Home, normal reload independently requires all three expected binds to be exact owned read-only mounts. Missing, writable, foreign/stacked or incomplete layers refuse without app changes. It validates native SAM schemas, uses a controlling PTY for Luna, sends `closeByAppId` with `{id:com.webos.app.home}`, verifies PID **and** `/proc/PID/stat` start time, uses only exact-executable `SIGTERM` as fallback (never `KILL`), and rejects a restored Home CRIU snapshot. Preexisting other app identities must remain unchanged; a newly appearing app alone no longer causes a false failure.

A launch error gets up to three bounded attempts, checking for a fresh Home identity before another request. An accepted launch is not duplicated merely because the running list lags. TERM errors cannot skip relaunch. A final failure returns nonzero with an explicit visible/original-snapshot recovery command. Preserve the error and use the [manual failure playbook](../docs/recovery.md#failure-playbook-optional-home-reload-fails); a failure after close does not mean Home was restored. A failed check is not permission to relax a guard.

## Optional persistence after screen QA

No persistent hook is installed by generation, staging, `--apply`, or Home reload. Only after screen QA and deliberately accepting both recurring boot-time mounts and a **hidden Home-only reload after fresh mounts** may you add the generated HBC hook:

```sh
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" \
  "python '$BASE/manage_boot_hook.py' --install --ack-install --ack-boot-home-reload"
```

Installation is atomic and no-overwrite. Repeating it for the identical owned hook is idempotent; a foreign hook is refused. The wrapper explicitly invokes `preview_runtime.py --boot --ack-mount --ack-home-reload`: it mounts the pinned patch and existing Home checkpoint directories read-only, then reloads **only Home hidden**, and only when new mounts were needed. This avoids retaining old QML in a CRIU-restored process. It never reboots, restarts SAM or deliberately closes another app; reload checks their process identities. A new firmware source hash makes it refuse. Physical boot ordering remains untested. Remove the persistent hook through rollback below.

If a boot reload fails, the runtime attempts to detach **only this invocation's newly created, still-verifiably-owned read-only binds**, then attempts a visible launch with original snapshots allowed. Preexisting owned binds and the persistent hook are not broadly removed; this is not a promise that every original layer was restored. Changed/foreign/stacked/writable targets are preserved and reported. Recovery failure returns nonzero with instructions, without automatic reboot, SAM restart, snapshot deletion or KILL escalation. Missing required checkpoint directories refuse before new binds or reload. These new failure paths have mocked offline tests only.

## Rollback

First run the rollback tool. It preflights all known targets and the hook before changing anything, removes only an exact owned boot hook, and detaches only exact single read-only binds whose target/source inodes match. A lazy detach is permitted only after a busy result is rechecked as that exact owned read-only bind with no nested mount; it is never used for other mounts. The tool retains all package files/placeholders and does not reload Home.

```sh
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" \
  "python '$BASE/rollback_preview.py' --restore-owned-mounts --ack-rollback"
```

Then, as a separately acknowledged operation, reload Home to show the restored firmware implementation. This allows the normal original Home snapshot case; it does not restart SAM or affect other apps:

```sh
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" \
  "python '$BASE/reload_home.py' --hidden --allow-original-snapshot --ack-home-reload"
```

If rollback reports a foreign/stacked/nested mount, unexpected firmware hash, or foreign boot hook, stop and inspect; do not force-unmount, overwrite, or delete anything. If a rollback bind is lazy-detached, existing Home/SAM file descriptors may continue using the old inode until they close; keep the source and placeholder files. No automatic reboot or SAM restart is performed.

## Offline tests

From the repository root:

```sh
python3 -B -m unittest discover -s tests -p 'test_optional_preview.py' -v
python3 -B -c "from pathlib import Path; [compile(p.read_text(), str(p), 'exec') for p in (Path('optional-preview/prepare.py'), Path('tests/test_optional_preview.py'))]"
```

The suite uses only synthetic QML/ListModel-like behavior and mocked mount/Luna/process state. Node.js enables the synthetic launchpoint behavior test; it is skipped if Node is absent. It does not connect to a TV or network. The model/firmware support and user-extracted checksum above are narrow compatibility evidence, not a universal webOS claim.
