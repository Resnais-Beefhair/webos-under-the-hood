#!/usr/bin/env python
"""Explicit, atomic, no-overwrite HBC boot-hook manager (Python 2.7+)."""
from __future__ import print_function
import hashlib
import os
import stat
import sys
import tempfile

BASE = "@BASE@"
HOOK_DIR = "/var/lib/webosbrew/init.d"
HOOK_PATH = os.path.join(HOOK_DIR, "60-home-preview-override")
BOOT_HOOK = os.path.join(BASE, "home-preview-boot-hook.sh")
BOOT_HOOK_SHA256 = "@BOOT_HOOK_SHA256@"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require_root():
    if os.getuid() != 0:
        raise RuntimeError("root privileges are required on the TV")


def expected_bytes():
    info = os.lstat(BOOT_HOOK)
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError("boot-hook source is not a regular file")
    with open(BOOT_HOOK, "rb") as stream:
        data = stream.read()
    if digest(data) != BOOT_HOOK_SHA256:
        raise RuntimeError("boot-hook source hash mismatch")
    return data


def hook_state(path=HOOK_PATH, expected=None):
    try:
        info = os.lstat(path)
    except OSError:
        return "absent"
    if expected is None:
        expected = expected_bytes()
    if not stat.S_ISREG(info.st_mode):
        return "foreign"
    with open(path, "rb") as stream:
        current = stream.read()
    return "owned" if current == expected and digest(current) == BOOT_HOOK_SHA256 else "foreign"


def _require_hook_directory():
    try:
        info = os.lstat(HOOK_DIR)
    except OSError:
        raise RuntimeError("HBC init.d directory is missing")
    if not stat.S_ISDIR(info.st_mode):
        raise RuntimeError("HBC init.d path is not a real directory")


def install_hook(path=HOOK_PATH, expected=None):
    if expected is None:
        expected = expected_bytes()
    state = hook_state(path, expected)
    if state == "owned":
        return False
    if state == "foreign":
        raise RuntimeError("refusing to overwrite a foreign boot hook")
    if path != HOOK_PATH:
        raise RuntimeError("unexpected boot-hook path")
    _require_hook_directory()
    fd, temporary = tempfile.mkstemp(prefix=".home-preview-", dir=HOOK_DIR)
    try:
        stream = os.fdopen(fd, "wb")
        try:
            stream.write(expected)
            stream.flush()
            os.fsync(stream.fileno())
        finally:
            stream.close()
        os.chmod(temporary, 0o755)
        # link() is an atomic create-if-absent on the same filesystem; it cannot
        # replace a concurrent or pre-existing hook the way rename() can.
        try:
            os.link(temporary, path)
        except OSError:
            state = hook_state(path, expected)
            if state == "owned":
                return False
            if state == "foreign":
                raise RuntimeError("refusing to overwrite a foreign boot hook")
            raise
        if hook_state(path, expected) != "owned":
            raise RuntimeError("installed boot hook failed its exact-byte verification")
        return True
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def remove_hook(path=HOOK_PATH, expected=None):
    if expected is None:
        expected = expected_bytes()
    state = hook_state(path, expected)
    if state == "absent":
        return False
    if state != "owned":
        raise RuntimeError("refusing to remove a foreign boot hook")
    with open(path, "rb") as stream:
        if stream.read() != expected:
            raise RuntimeError("boot hook changed during removal preflight")
    os.unlink(path)
    if hook_state(path, expected) != "absent":
        raise RuntimeError("boot hook remains after removal")
    return True


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("No action. Use --check, --install --ack-install --ack-boot-home-reload, or --remove --ack-remove.", file=sys.stderr)
        return 2
    if argv == ["--check"]:
        try:
            print(hook_state())
            return 0
        except Exception as exc:
            print("boot-hook check refused: %s" % exc, file=sys.stderr)
            return 1
    if argv not in (["--install", "--ack-install", "--ack-boot-home-reload"], ["--remove", "--ack-remove"]):
        print("Explicit hook mode and matching acknowledgement are required; no changes made.", file=sys.stderr)
        return 2
    try:
        require_root()
        changed = install_hook() if argv[0] == "--install" else remove_hook()
        print("boot hook %s; changed=%s" % ("installed" if argv[0] == "--install" else "removed", str(changed).lower()))
        return 0
    except Exception as exc:
        print("boot-hook operation refused: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
