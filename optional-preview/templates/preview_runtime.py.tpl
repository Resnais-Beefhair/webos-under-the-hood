#!/usr/bin/env python
"""Hash-guarded Home-only mounts. No arguments never change device state."""
from __future__ import print_function
import hashlib
import os
import stat
import subprocess
import sys

BASE = "@BASE@"
UI = "@UI@"
ORIGINAL_SHA256 = "@ORIGINAL_SHA256@"
PATCHED_SHA256 = "@PATCHED_SHA256@"
CHECKPOINTS = (
    "/mnt/lg/cmn_data/checkpoint/com.webos.app.home",
    "/tmp/checkpoint/com.webos.app.home",
)


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def require_root():
    if os.getuid() != 0:
        raise RuntimeError("root privileges are required on the TV")


def _mount_rows():
    rows = []
    with open("/proc/mounts", "r") as stream:
        for line in stream:
            fields = line.split()
            if len(fields) >= 4:
                rows.append(fields)
    return rows


def _same_inode(source, target):
    a = os.stat(source)
    b = os.stat(target)
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


def mount_state(source, target, rows=None, same_inode=None):
    """Return absent/owned; reject stacked, nested, foreign, or writable binds."""
    if rows is None:
        rows = _mount_rows()
    if same_inode is None:
        same_inode = _same_inode
    exact = [row for row in rows if len(row) >= 4 and row[1] == target]
    nested = [row for row in rows if len(row) >= 4 and row[1].startswith(target.rstrip("/") + "/")]
    if nested:
        raise RuntimeError("nested mount below protected target: %s" % target)
    if len(exact) > 1:
        raise RuntimeError("stacked mounts at protected target: %s" % target)
    if not exact:
        return "absent"
    if not same_inode(source, target):
        raise RuntimeError("foreign mount at protected target: %s" % target)
    if "ro" not in exact[0][3].split(","):
        raise RuntimeError("owned-inode mount is not read-only: %s" % target)
    return "owned"


def _is_regular_nonsymlink(path):
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode)


def _validate_package():
    if os.path.islink(BASE) or not os.path.isdir(BASE):
        raise RuntimeError("runtime base is missing or is a symlink")
    original = os.path.join(BASE, "Interfaces.original.qml")
    patched = os.path.join(BASE, "Interfaces.patched.qml")
    if not _is_regular_nonsymlink(original) or digest(original) != ORIGINAL_SHA256:
        raise RuntimeError("on-device original backup is missing or has the wrong hash")
    if not _is_regular_nonsymlink(patched) or digest(patched) != PATCHED_SHA256:
        raise RuntimeError("patched QML is missing or has the wrong hash")
    empty = os.path.join(BASE, "empty-checkpoint")
    if os.path.islink(empty) or not os.path.isdir(empty) or os.listdir(empty):
        raise RuntimeError("checkpoint placeholder must be a real, empty directory")


def _targets():
    pairs = [(UI, os.path.join(BASE, "Interfaces.patched.qml"))]
    for target in CHECKPOINTS:
        if os.path.lexists(target):
            if os.path.islink(target) or not os.path.isdir(target):
                raise RuntimeError("Home checkpoint target is not a real directory: %s" % target)
            pairs.append((target, os.path.join(BASE, "empty-checkpoint")))
    return pairs


def inspect():
    """Read-only full preflight; return target/state pairs after all guards."""
    _validate_package()
    pairs = _targets()
    result = []
    for target, source in pairs:
        if target == UI:
            if os.path.islink(target) or not _is_regular_nonsymlink(target):
                raise RuntimeError("Home QML target is not a real regular file")
        state = mount_state(source, target)
        if target == UI:
            visible_hash = digest(target)
            expected = PATCHED_SHA256 if state == "owned" else ORIGINAL_SHA256
            if visible_hash != expected:
                raise RuntimeError("Home QML is neither the pinned original nor our owned patch")
        result.append((target, source, state))
    return result


def _cleanup_new_mount(target, source):
    """Best-effort ordinary detach for a mount created during this invocation."""
    rows = _mount_rows()
    exact = [row for row in rows if len(row) >= 4 and row[1] == target]
    nested = [row for row in rows if len(row) >= 4 and row[1].startswith(target.rstrip("/") + "/")]
    if len(exact) != 1 or nested or not _same_inode(source, target):
        raise RuntimeError("new mount cannot be proven ours during cleanup: %s" % target)
    subprocess.check_call(["umount", target])
    if any(row[1] == target for row in _mount_rows()):
        raise RuntimeError("new mount remains after cleanup: %s" % target)


def apply_mounts():
    plan = inspect()  # Refuse every foreign condition before changing any target.
    new_mounts = []
    changed = 0
    try:
        for target, source, state in plan:
            if state == "owned":
                continue
            if mount_state(source, target) != "absent":
                raise RuntimeError("mount state changed during preflight: %s" % target)
            subprocess.check_call(["mount", "--bind", source, target])
            new_mounts.append((target, source))
            subprocess.check_call(["mount", "-o", "remount,bind,ro", target])
            if mount_state(source, target) != "owned":
                raise RuntimeError("bind did not become the exact read-only owned mount: %s" % target)
            changed += 1
    except Exception:
        cleanup_errors = []
        for target, source in reversed(new_mounts):
            try:
                _cleanup_new_mount(target, source)
            except Exception as exc:
                cleanup_errors.append("%s: %s" % (target, exc))
        if cleanup_errors:
            raise RuntimeError("mount application failed; cleanup also failed: %s" % "; ".join(cleanup_errors))
        raise
    return changed


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("No action: use --check, --apply --ack-mount, or --boot --ack-mount.", file=sys.stderr)
        return 2
    if argv == ["--check"]:
        try:
            print("\n".join("%s %s" % (state, target) for target, source, state in inspect()))
            return 0
        except Exception as exc:
            print("preflight refused: %s" % exc, file=sys.stderr)
            return 1
    if argv not in (["--apply", "--ack-mount"], ["--boot", "--ack-mount", "--ack-home-reload"]):
        print("Explicit mode and mount consent are required; boot additionally requires --ack-home-reload. No changes made.", file=sys.stderr)
        return 2
    try:
        require_root()
        changed = apply_mounts()
        if argv[0] == "--boot" and changed:
            # A process restored from CRIU may retain the old code after mounts.
            # Installing this boot hook explicitly approves this Home-only reload.
            subprocess.check_call([sys.executable, os.path.join(BASE, "reload_home.py"),
                                   "--hidden", "--ack-home-reload"])
        print("Home preview mounts ready; changed=%d; boot_reload=%s" %
              (changed, str(argv[0] == "--boot" and bool(changed)).lower()))
        return 0
    except Exception as exc:
        print("mount application failed: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
