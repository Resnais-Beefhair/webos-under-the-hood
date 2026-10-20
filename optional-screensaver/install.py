#!/usr/bin/env python3
"""Explicitly stage a generated package via pinned SSH and binary stdin."""
import sys
sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_STATE = ROOT / ".local-state"
BASE = "/var/lib/webosbrew/screensaver-override"
HOOK = "/var/lib/webosbrew/init.d/65-screensaver-override"
BUILD = "20260421173614"
TARGETS = {
    "ScreenSaver.qml": "/usr/palm/applications/com.webos.app.screensaver/qml/Containers/ScreenSaver.qml",
    "MainView.qml": "/usr/palm/applications/com.webos.app.screensaver/qml/Containers/MainView.qml",
}
ORIGINAL = {
    "ScreenSaver.qml": "78b7d3fcfeff9c64b60b8e7c7bd199888eefac47063898aab0ee6e1f0f319690",
    "MainView.qml": "03ba65c5c05387e967518b4a04cafda0b24c5524cbacf76a7d0906fc0d5a3700",
}
FILES = (
    "ScreenSaver.original.qml",
    "ScreenSaver.patched.qml",
    "MainView.original.qml",
    "MainView.patched.qml",
    "manifest.json",
    "overlay_runtime.py",
    "manage_boot_hook.py",
    "reload_screensaver.py",
    "screensaver-boot-hook.sh",
)
PACKAGE_HASH_NAMES = set(FILES) - {"manifest.json"}
SSH_OPTIONS = [
    "ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
    "-o", "IdentitiesOnly=yes", "-o", "ForwardAgent=no", "-o", "ClearAllForwardings=yes",
    "-o", "ConnectTimeout=8", "-o", "ConnectionAttempts=1",
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def _inside(path, root):
    try:
        return os.path.commonpath([str(path), str(root)]) == str(root)
    except ValueError:
        return False


def _require_ignored_state():
    if LOCAL_STATE.is_symlink() or (LOCAL_STATE.exists() and not LOCAL_STATE.is_dir()):
        raise ValueError(".local-state must be a real directory, not a symlink or file")
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "check-ignore", "-q", "--no-index", "--", ".local-state/.screensaver-stage-check"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except OSError as exc:
        raise ValueError("Git is required to verify ignored .local-state/: %s" % exc)
    if result.returncode != 0:
        raise ValueError(".local-state/ is not ignored by Git")
    if os.name == "posix" and LOCAL_STATE.exists() and stat.S_IMODE(LOCAL_STATE.stat().st_mode) & 0o077:
        raise ValueError(".local-state permissions are not private; use chmod 700 .local-state")


def _snapshot_package(package_dir):
    """Validate one byte snapshot; never reopen accepted data for transfer."""
    _require_ignored_state()
    path = Path(package_dir)
    if not path.is_absolute():
        path = ROOT / path
    lexical = Path(os.path.abspath(str(path)))
    state_lexical = Path(os.path.abspath(str(LOCAL_STATE)))
    if not _inside(lexical, state_lexical) or lexical == state_lexical:
        raise ValueError("package directory must be below ignored .local-state/")
    cursor = LOCAL_STATE
    for part in lexical.relative_to(state_lexical).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("package path contains a symlink: %s" % cursor)
    resolved_state = LOCAL_STATE.resolve(strict=False)
    resolved = lexical.resolve(strict=False)
    if not _inside(resolved, resolved_state) or resolved == resolved_state or not resolved.is_dir():
        raise ValueError("package directory is missing or escaped .local-state/")
    if os.name == "posix":
        for directory in [resolved] + list(resolved.parents):
            if directory == resolved_state or _inside(directory, resolved_state):
                if directory.exists() and stat.S_IMODE(directory.stat().st_mode) & 0o077:
                    raise ValueError("package path is not private: %s" % directory)

    manifest_path = resolved / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("manifest.json must be a regular non-symlink file")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    expected_fields = {
        "feature": "optional-moving-rings-screensaver",
        "build": BUILD,
        "runtime_base": BASE,
        "boot_hook": HOOK,
        "targets": TARGETS,
        "original_sha256": ORIGINAL,
    }
    for key, value in expected_fields.items():
        if manifest.get(key) != value:
            raise ValueError("package manifest %s mismatch" % key)
    hashes = manifest.get("package_sha256")
    patched = manifest.get("patched_sha256")
    if not isinstance(hashes, dict) or set(hashes) != PACKAGE_HASH_NAMES:
        raise ValueError("package manifest has an unexpected file allowlist")
    if not isinstance(patched, dict) or set(patched) != set(TARGETS):
        raise ValueError("package manifest patched-source allowlist mismatch")
    accepted = {}
    for name in FILES:
        item = resolved / name
        if item.is_symlink() or not item.is_file():
            raise ValueError("package file must be regular and non-symlink: %s" % name)
        data = manifest_bytes if name == "manifest.json" else item.read_bytes()
        accepted[name] = data
        expected = sha(data) if name == "manifest.json" else hashes.get(name)
        if name != "manifest.json" and (not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)):
            raise ValueError("invalid package SHA-256 for %s" % name)
        if name != "manifest.json" and sha(data) != expected:
            raise ValueError("package SHA-256 mismatch: %s" % name)
        if name.endswith(".original.qml") and sha(data) != ORIGINAL[name.split(".")[0] + ".qml"]:
            raise ValueError("original QML hash mismatch: %s" % name)
        if name.endswith(".patched.qml"):
            qml_name = name.split(".")[0] + ".qml"
            if sha(data) != patched.get(qml_name):
                raise ValueError("patched QML hash mismatch: %s" % name)
    return resolved, manifest, accepted


def validate_package(package_dir):
    resolved, manifest, _ = _snapshot_package(package_dir)
    return resolved, manifest


def _ssh(alias, remote_command, data=None):
    if shutil.which("ssh") is None:
        raise RuntimeError("OpenSSH client is not available")
    try:
        return subprocess.run(SSH_OPTIONS + [alias, remote_command], input=data,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90, check=False)
    except subprocess.TimeoutExpired:
        raise RuntimeError("SSH staging command timed out; inspect the TV base before retrying")
    except OSError as exc:
        raise RuntimeError("could not run SSH staging command: %s" % exc)


def _parse_sha256_output(raw, expected_names):
    try:
        result = {}
        for line in raw.decode("ascii").splitlines():
            parts = line.split(None, 1)
            if len(parts) != 2:
                raise ValueError("malformed sha256sum line")
            name = Path(parts[1].lstrip("* ")).name
            if name in result:
                raise ValueError("duplicate sha256sum filename")
            result[name] = parts[0]
        if set(result) != set(expected_names):
            raise ValueError("sha256sum filename set mismatch")
        return result
    except (UnicodeError, ValueError) as exc:
        raise RuntimeError("SHA-256 readback could not be parsed: %s" % exc)


def stage(package_dir, alias):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", alias) or alias.startswith("-"):
        raise ValueError("target must be an existing SSH config alias, not a host/user string")
    package_dir, manifest, accepted = _snapshot_package(package_dir)
    if shutil.which("ssh") is None:
        raise RuntimeError("OpenSSH client is not available")

    target_paths = [TARGETS[name] for name in sorted(TARGETS)]
    preflight = 'set -eu; test "$(id -u)" = 0; test "$(cat /etc/version)" = "%s"; ' % BUILD
    preflight += "test -d '/var/lib/webosbrew' && test ! -L '/var/lib/webosbrew'; "
    for target in target_paths:
        preflight += "test -f '%s' && test ! -L '%s'; " % (target, target)
    preflight += "sha256sum " + " ".join("'%s'" % target for target in target_paths)
    result = _ssh(alias, preflight)
    if result.returncode != 0:
        raise RuntimeError("TV root/build/target preflight failed; no package files were written")
    target_hashes = _parse_sha256_output(result.stdout, set(TARGETS))
    for name, expected in ORIGINAL.items():
        if target_hashes.get(name) != expected:
            raise RuntimeError("TV source hash mismatch for %s; no package files were written" % name)

    result = _ssh(alias, "set -eu; test ! -e '%s'; umask 077; mkdir -m 700 '%s'" % (BASE, BASE))
    if result.returncode != 0:
        raise RuntimeError("remote base was not created (or already exists); no package files were transferred")

    for name in FILES:
        command = "set -eu; umask 077; set -C; cat > '%s/%s'" % (BASE, name)
        result = _ssh(alias, command, accepted[name])
        if result.returncode != 0:
            raise RuntimeError("staging stopped while transferring %s; inspect partial remote files before retrying" % name)

    modes = "chmod 600 '%s/ScreenSaver.original.qml' '%s/MainView.original.qml' '%s/manifest.json'; " % (BASE, BASE, BASE)
    modes += "chmod 644 '%s/ScreenSaver.patched.qml' '%s/MainView.patched.qml'; " % (BASE, BASE)
    modes += "chmod 700 '%s/overlay_runtime.py' '%s/manage_boot_hook.py' '%s/reload_screensaver.py' '%s/screensaver-boot-hook.sh'; " % (BASE, BASE, BASE, BASE)
    names = " ".join("'%s/%s'" % (BASE, name) for name in FILES)
    result = _ssh(alias, "set -eu; %ssha256sum %s" % (modes, names))
    if result.returncode != 0:
        raise RuntimeError("remote package permissions/hash readback failed; preserve the staged files")
    readback = _parse_sha256_output(result.stdout, set(FILES))
    for name in FILES:
        expected = sha(accepted[name])
        if readback.get(name) != expected:
            raise RuntimeError("remote package readback did not match local bytes: %s" % name)
    return {"staged": True, "verified_file_count": len(FILES), "runtime_base": BASE,
            "network_used": True, "source_build_verified": True, "source_hashes_verified": True,
            "apply_performed": False, "reload_performed": False,
            "visible_rendering_verified": False, "boot_hook_installed": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", required=True, help="generated package below ignored .local-state/")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--check", action="store_true", help="verify the local package only; no SSH")
    actions.add_argument("--install", action="store_true", help="stage package over pinned SSH")
    parser.add_argument("--target-alias", help="existing pinned SSH config alias")
    parser.add_argument("--ack-install", action="store_true", help="explicitly approve TV package staging")
    args = parser.parse_args(argv)
    if not (args.check or args.install):
        parser.print_help()
        return 2
    if args.check and (args.target_alias or args.ack_install):
        parser.error("--check is local-only and takes no target/acknowledgement")
    if args.install and (not args.target_alias or not args.ack_install):
        parser.error("--install requires --target-alias and --ack-install")
    if args.check:
        package_dir, manifest = validate_package(args.package_dir)
        result = {"package_verified": True, "file_count": len(FILES), "network_used": False,
                  "runtime_base": manifest["runtime_base"]}
    else:
        result = stage(args.package_dir, args.target_alias)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("install package: " + str(exc), file=sys.stderr)
        sys.exit(1)
