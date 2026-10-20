#!/usr/bin/env python3
"""Build a local-only, hash-pinned Home preview override package.

Vendor QML is read from a user-supplied file and is never copied into the
tracked package. Generated source/recovery files belong under .local-state/.
"""
import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
LOCAL_STATE = ROOT / ".local-state"
TARGET = "/usr/palm/applications/com.webos.app.home/qml/Controllers/PreviewInterfaces/Interfaces.qml"
BASE = "/var/lib/webosbrew/home-preview-override"
ORIGINAL_SHA256 = "d0aa864876562529de9a15e6071d5deb7e11c93b97acaadebadb0ca946790bb5"
PATCHED_SHA256 = "a6ab3df9ca1470e673db4905c7dc4a4173f9dad5e1b4045fe00fef0297af980a"
ANCHOR = b"    function getAppPreview(launchPoint) {\n"
GUARD = (
    b'        // Only suppress the main YouTube hover recommendations, not channels.\n'
    b'        if (launchPoint.launchPointId === systemProperties.youTubeAppId + "_default") {\n'
    b'            createPreviewModel(launchPoint.launchPointId, "app", []);\n'
    b'            switchModels();\n'
    b'            return;\n'
    b'        }\n'
    b"\n"
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def patch_source(source_bytes):
    actual = sha256(source_bytes)
    if actual != ORIGINAL_SHA256:
        raise ValueError("source SHA-256 mismatch: expected %s, got %s" % (ORIGINAL_SHA256, actual))
    anchor_count = source_bytes.count(ANCHOR)
    if anchor_count != 1:
        raise ValueError("expected exactly one getAppPreview(launchPoint) anchor; found %d" % anchor_count)
    patched = source_bytes.replace(ANCHOR, ANCHOR + GUARD, 1)
    if sha256(patched) != PATCHED_SHA256:
        raise ValueError("pinned source did not produce the known tested patch hash")
    return patched


def _template(name, values):
    path = TEMPLATE_DIR / name
    text = path.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("@%s@" % key, value)
    if "@BASE@" in text or "@UI@" in text or "@ORIGINAL_SHA256@" in text or "@PATCHED_SHA256@" in text or "@BOOT_HOOK_SHA256@" in text:
        raise ValueError("unexpanded template placeholder in %s" % name)
    return text.encode("utf-8")


def build_bundle(source_bytes):
    patched = patch_source(source_bytes)
    patched_hash = sha256(patched)
    base_values = {
        "BASE": BASE,
        "UI": TARGET,
        "ORIGINAL_SHA256": ORIGINAL_SHA256,
        "PATCHED_SHA256": patched_hash,
    }
    boot_hook = _template("home-preview-boot-hook.sh.tpl", base_values)
    all_values = dict(base_values)
    all_values["BOOT_HOOK_SHA256"] = sha256(boot_hook)
    artifacts = {
        "Interfaces.original.qml": source_bytes,
        "Interfaces.patched.qml": patched,
        "preview_runtime.py": _template("preview_runtime.py.tpl", all_values),
        "reload_home.py": _template("reload_home.py.tpl", all_values),
        "rollback_preview.py": _template("rollback_preview.py.tpl", all_values),
        "manage_boot_hook.py": _template("manage_boot_hook.py.tpl", all_values),
        "home-preview-boot-hook.sh": boot_hook,
    }
    manifest = {
        "feature": "optional-main-YouTube-Home-preview-suppression",
        "remote_path": TARGET,
        "runtime_base": BASE,
        "original_sha256": ORIGINAL_SHA256,
        "guarded_sha256": patched_hash,
        "boot_hook_sha256": sha256(boot_hook),
        "patch": "One early return in getAppPreview for the YouTube _default launchpoint only.",
        "vendor_qml_versioned": False,
        "private_source_storage": "ignored .local-state only",
        "tested_device": "LG OLED65CX6LA; firmware 04.64.00; webOS 5.6.2-21",
        "test_scope": "Original device integration was tested separately; this package is offline-refactored and is not a new live-device test.",
    }
    artifacts["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return artifacts, manifest


def _inside(path, root):
    try:
        return os.path.commonpath([str(path), str(root)]) == str(root)
    except ValueError:
        return False


def validate_output_dir(output_dir):
    """Require a fresh output path below this repository's local-only state."""
    if LOCAL_STATE.is_symlink() or (LOCAL_STATE.exists() and not LOCAL_STATE.is_dir()):
        raise ValueError(".local-state must be a real directory, not a symlink or file")
    if LOCAL_STATE.exists() and stat.S_IMODE(LOCAL_STATE.stat().st_mode) & 0o077:
        raise ValueError(".local-state permissions are not private; use chmod 700 .local-state")
    state_root = LOCAL_STATE.resolve(strict=False)
    requested = Path(output_dir)
    if not requested.is_absolute():
        requested = ROOT / requested
    # Reject symlinks in every existing path component below .local-state.
    lexical = Path(os.path.abspath(str(requested)))
    if not _inside(lexical, LOCAL_STATE.absolute()) or lexical == LOCAL_STATE.absolute():
        raise ValueError("output directory must be a child of public-release/.local-state")
    relative = lexical.relative_to(LOCAL_STATE.absolute())
    cursor = LOCAL_STATE
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("output path contains a symlink: %s" % cursor)
    resolved = lexical.resolve(strict=False)
    if not _inside(resolved, state_root) or resolved == state_root:
        raise ValueError("resolved output directory escaped .local-state")
    if resolved.exists():
        raise FileExistsError("refusing to overwrite existing output directory: %s" % resolved)
    return resolved


def write_bundle(output_dir, artifacts):
    output_dir = Path(output_dir)
    state_root = LOCAL_STATE
    if state_root.is_symlink():
        raise ValueError(".local-state must not be a symlink")
    state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if stat.S_IMODE(state_root.stat().st_mode) & 0o077:
        raise ValueError(".local-state permissions are not private; use chmod 700 .local-state")
    resolved_root = state_root.resolve(strict=True)
    resolved_output = output_dir.resolve(strict=False)
    if not _inside(resolved_output, resolved_root) or resolved_output == resolved_root:
        raise ValueError("output directory must be below public-release/.local-state")
    parent = resolved_root
    for part in resolved_output.parent.relative_to(resolved_root).parts:
        parent = parent / part
        if parent.is_symlink():
            raise ValueError("output parent contains a symlink: %s" % parent)
        parent.mkdir(mode=0o700, exist_ok=True)
        if not parent.is_dir() or stat.S_IMODE(parent.stat().st_mode) & 0o077:
            raise ValueError("output parent is not a private directory: %s" % parent)
    stage = Path(tempfile.mkdtemp(prefix=".preview-build-", dir=str(resolved_output.parent)))
    try:
        for name, data in artifacts.items():
            dest = stage / name
            with dest.open("xb") as stream:
                stream.write(data)
            os.chmod(str(dest), 0o700 if name.endswith(".py") or name.endswith(".sh") else 0o600)
        if resolved_output.exists() or resolved_output.is_symlink():
            raise FileExistsError("refusing to overwrite existing output directory: %s" % resolved_output)
        os.rename(str(stage), str(resolved_output))
    except Exception:
        shutil.rmtree(str(stage), ignore_errors=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="user-extracted original Interfaces.qml")
    parser.add_argument("--output-dir", required=True, help="fresh output directory below public-release/.local-state/")
    args = parser.parse_args(argv)
    source_path = Path(args.source)
    if source_path.is_symlink() or not source_path.is_file():
        parser.error("--source must be a regular, non-symlink file")
    source_bytes = source_path.read_bytes()
    try:
        artifacts, manifest = build_bundle(source_bytes)
        output_dir = validate_output_dir(args.output_dir)
        write_bundle(output_dir, artifacts)
    except (OSError, ValueError, FileExistsError) as exc:
        print("prepare.py: %s" % exc, file=sys.stderr)
        return 1
    print(json.dumps({"output_dir": str(output_dir), "manifest": manifest}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
