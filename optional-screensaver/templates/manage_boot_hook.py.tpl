#!/usr/bin/python
"""Install or remove only the exact optional screensaver boot hook."""
from __future__ import print_function
import sys
sys.dont_write_bytecode = True
import argparse
import hashlib
import json
import os
import stat
import subprocess

BASE = '@BASE@'
HOOK = '@HOOK@'
BUILD = '@BUILD@'
HOOK_SHA256 = '@BOOT_HOOK_SHA256@'
RUNTIME_SHA256 = '@RUNTIME_SHA256@'
TARGETS = {
    'ScreenSaver.qml': '@TARGET_SCREENSAVER@',
    'MainView.qml': '@TARGET_MAINVIEW@',
}
ORIGINAL = {
    'ScreenSaver.qml': '@ORIGINAL_SCREENSAVER_SHA256@',
    'MainView.qml': '@ORIGINAL_MAINVIEW_SHA256@',
}
PATCHED = {
    'ScreenSaver.qml': '@PATCHED_SCREENSAVER_SHA256@',
    'MainView.qml': '@PATCHED_MAINVIEW_SHA256@',
}


def require(value, message):
    if not value:
        raise RuntimeError(message)


def read(path):
    require(not os.path.islink(path), 'symlink refused: ' + path)
    with open(path, 'rb') as stream:
        return stream.read()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def package():
    require(os.path.isdir(BASE) and not os.path.islink(BASE), 'invalid runtime directory')
    st = os.stat(BASE)
    require(st.st_uid == 0 and stat.S_IMODE(st.st_mode) == 0o700,
            'runtime directory must be root-owned mode 0700')
    manifest = json.loads(read(os.path.join(BASE, 'manifest.json')).decode('utf-8'))
    require(manifest.get('feature') == 'optional-moving-rings-screensaver', 'wrong package feature')
    require(manifest.get('build') == BUILD and manifest.get('runtime_base') == BASE,
            'package build/runtime path mismatch')
    require(manifest.get('boot_hook') == HOOK and manifest.get('targets') == TARGETS,
            'package hook/target mismatch')
    require(manifest.get('original_sha256') == ORIGINAL and manifest.get('patched_sha256') == PATCHED,
            'package source pins mismatch')
    hashes = manifest.get('package_sha256', {})
    expected_names = set([
        'ScreenSaver.original.qml', 'ScreenSaver.patched.qml',
        'MainView.original.qml', 'MainView.patched.qml',
        'overlay_runtime.py', 'manage_boot_hook.py', 'reload_screensaver.py',
        'screensaver-boot-hook.sh'])
    require(set(hashes.keys()) == expected_names, 'package file allowlist mismatch')
    require(hashes.get('overlay_runtime.py') == RUNTIME_SHA256, 'runtime hash pin mismatch')
    require(hashes.get('screensaver-boot-hook.sh') == HOOK_SHA256, 'hook hash pin mismatch')
    for name, expected in hashes.items():
        require('/' not in name and name not in ('.', '..', 'manifest.json'), 'invalid package filename')
        require(sha(read(os.path.join(BASE, name))) == expected, 'package file changed: ' + name)
    require(read('/etc/version').decode('ascii').strip() == BUILD, 'firmware build changed')
    raw = subprocess.check_output([sys.executable, os.path.join(BASE, 'overlay_runtime.py'), '--check'])
    status = json.loads(raw.decode('utf-8'))
    return manifest, status


def hook_state(path, expected):
    if not os.path.lexists(path):
        return 'absent'
    if os.path.islink(path) or not os.path.isfile(path):
        return 'foreign'
    st = os.stat(path)
    if st.st_uid != 0 or stat.S_IMODE(st.st_mode) != 0o700 or read(path) != expected:
        return 'foreign'
    return 'owned'


def _hook_directory():
    parent = os.path.dirname(HOOK)
    require(os.path.isdir(parent) and not os.path.islink(parent), 'boot-hook directory missing or symlinked')
    return parent


def _expected_hook():
    data = read(os.path.join(BASE, 'screensaver-boot-hook.sh'))
    require(sha(data) == HOOK_SHA256, 'staged boot hook hash mismatch')
    return data


def install_hook(path, expected):
    state = hook_state(path, expected)
    if state == 'owned':
        return False
    require(state == 'absent', 'foreign boot hook; install refused')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
    try:
        stream = os.fdopen(fd, 'wb')
        try:
            stream.write(expected)
            stream.flush()
            os.fsync(stream.fileno())
        finally:
            stream.close()
        os.chmod(path, 0o700)
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    require(hook_state(path, expected) == 'owned', 'installed hook readback failed')
    return True


def remove_hook(path, expected):
    state = hook_state(path, expected)
    if state == 'absent':
        return False
    require(state == 'owned', 'foreign boot hook; removal refused')
    os.unlink(path)
    require(not os.path.lexists(path), 'boot hook removal readback failed')
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--check', action='store_true', help='read-only package/hook check')
    actions.add_argument('--install', action='store_true', help='install exact boot hook')
    actions.add_argument('--remove', action='store_true', help='remove exact owned boot hook')
    parser.add_argument('--ack-install', action='store_true', help='explicitly approve persistent boot hook')
    parser.add_argument('--ack-remove', action='store_true', help='explicitly approve hook removal')
    args = parser.parse_args(argv)
    if not (args.check or args.install or args.remove):
        parser.print_help()
        return 2
    if args.check and (args.ack_install or args.ack_remove):
        parser.error('--check is read-only and takes no acknowledgement flags')
    if args.install and (not args.ack_install or args.ack_remove):
        parser.error('--install requires --ack-install')
    if args.remove and (not args.ack_remove or args.ack_install):
        parser.error('--remove requires --ack-remove')
    manifest, overlay = package()
    expected = _expected_hook()
    _hook_directory()
    state = hook_state(HOOK, expected)
    if args.check:
        result = {'hook_state': state, 'overlay': overlay, 'persistent_action': 'none'}
    elif args.install:
        require(os.geteuid() == 0, 'install requires root')
        require(not overlay.get('disabled'), 'rollback disabled future apply; stage a fresh package before installing')
        require(all(value == 'owned-ro' for value in overlay.get('mounts', {}).values()),
                'install only after both owned read-only binds are active and screen-tested')
        changed = install_hook(HOOK, expected)
        result = {'hook_state': hook_state(HOOK, expected), 'installed': changed,
                  'boot_action': 'mount-only; no application reload'}
    else:
        require(os.geteuid() == 0, 'remove requires root')
        changed = remove_hook(HOOK, expected)
        result = {'hook_state': hook_state(HOOK, expected), 'removed': changed}
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print('manage boot hook: ' + str(exc), file=sys.stderr)
        sys.exit(1)
