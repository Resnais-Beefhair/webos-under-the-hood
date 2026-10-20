#!/usr/bin/env python3
"""Build a local-only, hash-pinned moving-rings screensaver package.

Input QML must be extracted by the owner from the supported TV. The source and
all generated recovery files stay under ignored .local-state/; this script has
no SSH, network, mount, reload, or device-write path.
"""
from __future__ import print_function

import sys
sys.dont_write_bytecode = True

import hashlib
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
LOCAL_STATE = ROOT / ".local-state"
BUILD = "20260421173614"
BASE = "/var/lib/webosbrew/screensaver-override"
HOOK = "/var/lib/webosbrew/init.d/65-screensaver-override"
TARGETS = {
    "ScreenSaver.qml": "/usr/palm/applications/com.webos.app.screensaver/qml/Containers/ScreenSaver.qml",
    "MainView.qml": "/usr/palm/applications/com.webos.app.screensaver/qml/Containers/MainView.qml",
}
ORIGINAL_SHA256 = {
    "ScreenSaver.qml": "78b7d3fcfeff9c64b60b8e7c7bd199888eefac47063898aab0ee6e1f0f319690",
    "MainView.qml": "03ba65c5c05387e967518b4a04cafda0b24c5524cbacf76a7d0906fc0d5a3700",
}
PATCHED_MAINVIEW_SHA256 = "4eee860b6e877677f3db8c45926e8c26848e8440d448d94f7de7337abcc6a8df"
GEOMETRY_REPLACEMENTS = (
    (b"width: root.partial ? 320 : getRelativeWidth(600)",
     b"width: root.partial ? 320 : root.width"),
    (b"height: root.partial ? 320 : getRelativeHeight(600)",
     b"height: root.partial ? 320 : root.height"),
    (b"x: Math.random() * (root.width - width)",
     b"x: root.partial ? Math.random() * (root.width - width) : 0"),
    (b"y: Math.random() * ((root.partial ? 320 : root.height) - height)",
     b"y: root.partial ? Math.random() * (320 - height) : 0"),
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def patch_main_view(source):
    """Apply only the four pinned full-screen geometry replacements."""
    actual = sha256(source)
    expected = ORIGINAL_SHA256["MainView.qml"]
    if actual != expected:
        raise ValueError("MainView.qml SHA-256 mismatch: expected %s, got %s" % (expected, actual))
    result = source
    for old, new in GEOMETRY_REPLACEMENTS:
        count = result.count(old)
        if count != 1:
            raise ValueError("geometry anchor must occur exactly once; found %d: %s" %
                             (count, old.decode("ascii")))
        result = result.replace(old, new, 1)
    if sha256(result) != PATCHED_MAINVIEW_SHA256:
        raise ValueError("pinned MainView.qml did not produce the known patched hash")
    return result


def _read_source(source_dir, name):
    path = source_dir / name
    if path.is_symlink() or not path.is_file():
        raise ValueError("source must be a regular, non-symlink file: %s" % path)
    return path.read_bytes()


def _template(name, values):
    path = TEMPLATE_DIR / name
    if path.is_symlink() or not path.is_file():
        raise ValueError("missing or symlinked template: %s" % path)
    text = path.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("@%s@" % key, value)
    import re
    leftovers = re.findall(r"@[A-Z][A-Z0-9_]*@", text)
    if leftovers:
        raise ValueError("unexpanded template placeholders in %s: %s" %
                         (name, ", ".join(sorted(set(leftovers)))))
    return text.encode("utf-8")


def build_bundle(source_dir):
    source_dir = Path(source_dir)
    if source_dir.is_symlink() or not source_dir.is_dir():
        raise ValueError("--source-dir must be a real directory, not a symlink")
    originals = {name: _read_source(source_dir, name) for name in TARGETS}
    for name, data in originals.items():
        actual = sha256(data)
        expected = ORIGINAL_SHA256[name]
        if actual != expected:
            raise ValueError("%s SHA-256 mismatch: expected %s, got %s" % (name, expected, actual))

    screensaver = (TEMPLATE_DIR / "ScreenSaver.qml.tpl").read_bytes()
    mainview = patch_main_view(originals["MainView.qml"])
    hook = _template("screensaver-boot-hook.sh.tpl", {"BASE": BASE})
    common = {
        "BASE": BASE,
        "HOOK": HOOK,
        "BUILD": BUILD,
        "TARGET_SCREENSAVER": TARGETS["ScreenSaver.qml"],
        "TARGET_MAINVIEW": TARGETS["MainView.qml"],
        "ORIGINAL_SCREENSAVER_SHA256": ORIGINAL_SHA256["ScreenSaver.qml"],
        "ORIGINAL_MAINVIEW_SHA256": ORIGINAL_SHA256["MainView.qml"],
        "PATCHED_SCREENSAVER_SHA256": sha256(screensaver),
        "PATCHED_MAINVIEW_SHA256": sha256(mainview),
        "BOOT_HOOK_SHA256": sha256(hook),
    }
    runtime = _template("overlay_runtime.py.tpl", common)
    package_hashes = {
        "ScreenSaver.original.qml": sha256(originals["ScreenSaver.qml"]),
        "ScreenSaver.patched.qml": sha256(screensaver),
        "MainView.original.qml": sha256(originals["MainView.qml"]),
        "MainView.patched.qml": sha256(mainview),
        "overlay_runtime.py": sha256(runtime),
        "screensaver-boot-hook.sh": sha256(hook),
    }
    manager_values = dict(common)
    manager_values["RUNTIME_SHA256"] = package_hashes["overlay_runtime.py"]
    manager = _template("manage_boot_hook.py.tpl", manager_values)
    package_hashes["manage_boot_hook.py"] = sha256(manager)
    reload_tool = _template("reload_screensaver.py.tpl", common)
    package_hashes["reload_screensaver.py"] = sha256(reload_tool)

    manifest = {
        "feature": "optional-moving-rings-screensaver",
        "build": BUILD,
        "runtime_base": BASE,
        "boot_hook": HOOK,
        "targets": TARGETS,
        "original_sha256": ORIGINAL_SHA256,
        "patched_sha256": {
            "ScreenSaver.qml": sha256(screensaver),
            "MainView.qml": sha256(mainview),
        },
        "package_sha256": package_hashes,
        "patch": "Four unique pinned full-screen geometry replacements in MainView.qml; own moving-rings ScreenSaver.qml.",
        "vendor_qml_versioned": False,
        "private_source_storage": "ignored .local-state only",
        "network_used_for_generation": False,
        "device_files_written_by_generation": False,
        "qml_overlay_applied": False,
        "native_screensaver_reloaded": False,
        "visible_rendering_verified": False,
        "test_scope": "Offline tests only; this generated public runtime has not been installed on a TV.",
    }
    artifacts = {
        "ScreenSaver.original.qml": originals["ScreenSaver.qml"],
        "ScreenSaver.patched.qml": screensaver,
        "MainView.original.qml": originals["MainView.qml"],
        "MainView.patched.qml": mainview,
        "overlay_runtime.py": runtime,
        "manage_boot_hook.py": manager,
        "reload_screensaver.py": reload_tool,
        "screensaver-boot-hook.sh": hook,
        "manifest.json": (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    }
    return artifacts, manifest


def _inside(path, root):
    try:
        return os.path.commonpath([str(path), str(root)]) == str(root)
    except ValueError:
        return False


def _require_ignored_state():
    probe = ".local-state/.screensaver-ignore-check"
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "check-ignore", "-q", "--no-index", "--", probe],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except OSError as exc:
        raise ValueError("Git is required to verify ignored .local-state/: %s" % exc)
    if result.returncode != 0:
        raise ValueError(".local-state/ is not ignored by Git; refusing private QML output")


def validate_output_dir(output_dir):
    """Require a fresh, non-symlink path below this repository's ignored state."""
    _require_ignored_state()
    if LOCAL_STATE.is_symlink() or (LOCAL_STATE.exists() and not LOCAL_STATE.is_dir()):
        raise ValueError(".local-state must be a real directory, not a symlink or file")
    if os.name == "posix" and LOCAL_STATE.exists() and stat.S_IMODE(LOCAL_STATE.stat().st_mode) & 0o077:
        raise ValueError(".local-state permissions are not private; use chmod 700 .local-state")
    requested = Path(output_dir)
    if not requested.is_absolute():
        requested = ROOT / requested
    lexical = Path(os.path.abspath(str(requested)))
    state_lexical = Path(os.path.abspath(str(LOCAL_STATE)))
    if not _inside(lexical, state_lexical) or lexical == state_lexical:
        raise ValueError("output directory must be a child of .local-state")
    cursor = LOCAL_STATE
    for part in lexical.relative_to(state_lexical).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("output path contains a symlink: %s" % cursor)
    resolved_state = LOCAL_STATE.resolve(strict=False)
    resolved = lexical.resolve(strict=False)
    if not _inside(resolved, resolved_state) or resolved == resolved_state:
        raise ValueError("resolved output path escaped .local-state")
    if resolved.exists() or resolved.is_symlink():
        raise FileExistsError("refusing to overwrite existing output directory: %s" % resolved)
    return resolved


def write_bundle(output_dir, artifacts):
    output_dir = validate_output_dir(output_dir)
    LOCAL_STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix" and stat.S_IMODE(LOCAL_STATE.stat().st_mode) & 0o077:
        raise ValueError(".local-state permissions are not private; use chmod 700 .local-state")
    state = LOCAL_STATE.resolve(strict=True)
    parent = state
    for part in output_dir.parent.relative_to(state).parts:
        parent = parent / part
        if parent.is_symlink():
            raise ValueError("output parent contains a symlink: %s" % parent)
        parent.mkdir(mode=0o700, exist_ok=True)
        if not parent.is_dir():
            raise ValueError("output parent is not a directory: %s" % parent)
        if os.name == "posix" and stat.S_IMODE(parent.stat().st_mode) & 0o077:
            raise ValueError("output parent is not private: %s" % parent)
    try:
        output_dir.mkdir(mode=0o700)
    except FileExistsError:
        raise FileExistsError("refusing to overwrite existing output directory: %s" % output_dir)
    try:
        for name, data in artifacts.items():
            dest = output_dir / name
            with dest.open("xb") as stream:
                stream.write(data)
            if os.name == "posix":
                os.chmod(str(dest), 0o700 if name.endswith((".py", ".sh")) else 0o600)
    except Exception:
        shutil.rmtree(str(output_dir), ignore_errors=True)
        raise
    return output_dir


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True,
                        help="directory containing user-extracted original ScreenSaver.qml and MainView.qml")
    parser.add_argument("--output-dir", required=True,
                        help="fresh output directory below ignored .local-state/")
    args = parser.parse_args(argv)
    try:
        artifacts, manifest = build_bundle(args.source_dir)
        output_dir = validate_output_dir(args.output_dir)
        write_bundle(output_dir, artifacts)
    except (OSError, ValueError, FileExistsError) as exc:
        print("prepare.py: %s" % exc, file=sys.stderr)
        return 1
    print(json.dumps({"output_dir": str(output_dir), "manifest": manifest}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
