"""Offline tests for the optional moving-rings screensaver package."""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PUBLIC = Path(__file__).resolve().parents[1]
OPTIONAL = PUBLIC / "optional-screensaver"


def load_module(path, name):
    old_flag = sys.dont_write_bytecode
    try:
        module = types.ModuleType(name)
        module.__file__ = str(path)
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
        return module
    finally:
        sys.dont_write_bytecode = old_flag


prepare = load_module(OPTIONAL / "prepare.py", "screensaver_prepare_tests")
install = load_module(OPTIONAL / "install.py", "screensaver_install_tests")

MAINVIEW_FIXTURE = (
    b"// Synthetic fixture; not vendor source.\n"
    b"width: root.partial ? 320 : getRelativeWidth(600)\n"
    b"height: root.partial ? 320 : getRelativeHeight(600)\n"
    b"x: Math.random() * (root.width - width)\n"
    b"y: Math.random() * ((root.partial ? 320 : root.height) - height)\n"
)
SCREENSAVER_FIXTURE = b"// Synthetic source fixture; not vendor QML.\nItem { property bool playing: false }\n"


def transformed_mainview(source=MAINVIEW_FIXTURE):
    result = source
    for old, new in prepare.GEOMETRY_REPLACEMENTS:
        result = result.replace(old, new, 1)
    return result


def build_bundle(mainview=MAINVIEW_FIXTURE, screensaver=SCREENSAVER_FIXTURE):
    patched = transformed_mainview(mainview)
    original_hashes = {
        "MainView.qml": hashlib.sha256(mainview).hexdigest(),
        "ScreenSaver.qml": hashlib.sha256(screensaver).hexdigest(),
    }
    with patch.object(prepare, "ORIGINAL_SHA256", original_hashes), \
            patch.object(prepare, "PATCHED_MAINVIEW_SHA256", hashlib.sha256(patched).hexdigest()):
        with tempfile.TemporaryDirectory() as temp:
            source_dir = Path(temp) / "source"
            source_dir.mkdir()
            (source_dir / "MainView.qml").write_bytes(mainview)
            (source_dir / "ScreenSaver.qml").write_bytes(screensaver)
            return prepare.build_bundle(source_dir)


def load_artifact(artifacts, name, module_name):
    old_flag = sys.dont_write_bytecode
    try:
        module = types.ModuleType(module_name)
        source = artifacts[name].decode("utf-8")
        exec(compile(source, name, "exec"), module.__dict__)
        return module
    finally:
        sys.dont_write_bytecode = old_flag


class PrepareTests(unittest.TestCase):
    def test_four_unique_pinned_anchors_are_the_only_mainview_changes(self):
        original_hash = hashlib.sha256(MAINVIEW_FIXTURE).hexdigest()
        patched = transformed_mainview()
        with patch.object(prepare, "ORIGINAL_SHA256", {
            "MainView.qml": original_hash,
            "ScreenSaver.qml": hashlib.sha256(SCREENSAVER_FIXTURE).hexdigest(),
        }), patch.object(prepare, "PATCHED_MAINVIEW_SHA256", hashlib.sha256(patched).hexdigest()):
            result = prepare.patch_main_view(MAINVIEW_FIXTURE)
        self.assertEqual(result, patched)
        self.assertEqual(len(prepare.GEOMETRY_REPLACEMENTS), 4)

    def test_unknown_hash_missing_and_duplicate_anchors_refuse(self):
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            prepare.patch_main_view(MAINVIEW_FIXTURE)
        missing = b"synthetic source without anchors\n"
        with patch.object(prepare, "ORIGINAL_SHA256", {
            "MainView.qml": hashlib.sha256(missing).hexdigest(),
            "ScreenSaver.qml": "unused",
        }):
            with self.assertRaisesRegex(ValueError, "found 0"):
                prepare.patch_main_view(missing)
        duplicate = MAINVIEW_FIXTURE + MAINVIEW_FIXTURE
        with patch.object(prepare, "ORIGINAL_SHA256", {
            "MainView.qml": hashlib.sha256(duplicate).hexdigest(),
            "ScreenSaver.qml": "unused",
        }):
            with self.assertRaisesRegex(ValueError, "found 2"):
                prepare.patch_main_view(duplicate)

    def test_source_screen_hash_and_symlink_are_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            source_dir = Path(temp)
            (source_dir / "ScreenSaver.qml").write_bytes(SCREENSAVER_FIXTURE + b"changed")
            (source_dir / "MainView.qml").write_bytes(MAINVIEW_FIXTURE)
            with self.assertRaisesRegex(ValueError, "ScreenSaver.qml SHA-256 mismatch"):
                prepare.build_bundle(source_dir)
            if os.name == "posix":
                link_dir = Path(temp) / "link"
                link_dir.symlink_to(source_dir, target_is_directory=True)
                with self.assertRaisesRegex(ValueError, "real directory"):
                    prepare.build_bundle(link_dir)

    def test_generated_bundle_hashes_python_and_shell_and_qml_contract(self):
        artifacts, manifest = build_bundle()
        self.assertEqual(artifacts["MainView.original.qml"], MAINVIEW_FIXTURE)
        self.assertEqual(artifacts["MainView.patched.qml"], transformed_mainview())
        self.assertEqual(manifest["vendor_qml_versioned"], False)
        self.assertEqual(manifest["private_source_storage"], "ignored .local-state only")
        self.assertFalse(manifest["network_used_for_generation"])
        self.assertFalse(manifest["device_files_written_by_generation"])
        self.assertFalse(manifest["qml_overlay_applied"])
        self.assertFalse(manifest["native_screensaver_reloaded"])
        self.assertFalse(manifest["visible_rendering_verified"])
        self.assertEqual(set(manifest["targets"]), {"ScreenSaver.qml", "MainView.qml"})
        qml = artifacts["ScreenSaver.patched.qml"].decode("utf-8")
        for contract in ("property bool playing", "property bool liteMode", "property bool isPartial",
                         "property string guideString", "signal looped()", "duration: 7500",
                         "interval: 7500", "objectName: \"ringField\""):
            self.assertIn(contract, qml)
        self.assertNotIn("Text {", qml)
        self.assertNotIn("irmeli", qml.lower())
        self.assertEqual(manifest["patched_sha256"]["ScreenSaver.qml"], hashlib.sha256(qml.encode()).hexdigest())
        for name, data in artifacts.items():
            if name.endswith(".py"):
                compile(data.decode("utf-8"), name, "exec")
        shell = shutil.which("sh")
        if shell:
            result = subprocess.run([shell, "-n"], input=artifacts["screensaver-boot-hook.sh"],
                                    capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertIn("--boot", artifacts["screensaver-boot-hook.sh"].decode("ascii"))
        self.assertNotIn("reload_screensaver", artifacts["screensaver-boot-hook.sh"].decode("ascii"))
        self.assertFalse(any(path.suffix == ".qml" for path in OPTIONAL.rglob("*")))

    @unittest.skipUnless(shutil.which("node"), "Node.js is optional for ring-count expression test")
    def test_ring_count_expression_matches_partial_lite_and_full_modes(self):
        artifacts, _ = build_bundle()
        qml = artifacts["ScreenSaver.patched.qml"].decode("utf-8")
        line = next(line for line in qml.splitlines() if "readonly property int ringCount:" in line)
        expression = line.split(":", 1)[1].strip()
        script = (
            "const f=new Function('isPartial','liteMode','return " + expression + "');"
            "if(f(true,false)!==2||f(false,true)!==3||f(false,false)!==5)throw Error('ring count mismatch');"
            "console.log('partial=2 lite=3 full=5');"
        )
        result = subprocess.run([shutil.which("node"), "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("partial=2 lite=3 full=5", result.stdout)

    @unittest.skipUnless(shutil.which("git"), "Git is required to exercise ignored-state checks")
    def test_output_confines_to_ignored_state_and_refuses_collision_and_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / ".gitignore").write_text(".local-state/\n", encoding="utf-8")
            state = root / ".local-state"
            state.mkdir(mode=0o700)
            with patch.object(prepare, "ROOT", root), patch.object(prepare, "LOCAL_STATE", state):
                safe = prepare.validate_output_dir(".local-state/run-one")
                self.assertEqual(safe, (state / "run-one").resolve())
                with self.assertRaisesRegex(ValueError, "child of .local-state"):
                    prepare.validate_output_dir(root / "outside")
                safe.mkdir()
                with self.assertRaises(FileExistsError):
                    prepare.validate_output_dir(safe)
                if os.name == "posix":
                    (state / "linked").symlink_to(root, target_is_directory=True)
                    with self.assertRaisesRegex(ValueError, "symlink"):
                        prepare.validate_output_dir(".local-state/linked/run-two")

    @unittest.skipUnless(os.name == "posix" and shutil.which("git"),
                         "private output modes require POSIX/WSL and Git")
    def test_write_bundle_is_private_and_never_overwrites(self):
        artifacts, _ = build_bundle()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / ".gitignore").write_text(".local-state/\n", encoding="utf-8")
            state = root / ".local-state"
            state.mkdir(mode=0o700)
            with patch.object(prepare, "ROOT", root), patch.object(prepare, "LOCAL_STATE", state):
                output = prepare.write_bundle(state / "bundle", artifacts)
                self.assertEqual((output / "ScreenSaver.original.qml").read_bytes(), SCREENSAVER_FIXTURE)
                self.assertEqual((output / "MainView.patched.qml").read_bytes(), transformed_mainview())
                self.assertEqual((output / "ScreenSaver.original.qml").stat().st_mode & 0o777, 0o600)
                self.assertEqual((output / "overlay_runtime.py").stat().st_mode & 0o777, 0o700)
                with self.assertRaises(FileExistsError):
                    prepare.write_bundle(output, artifacts)

    def test_generated_runtime_help_paths_do_not_write_bytecode(self):
        artifacts, manifest = build_bundle()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("overlay_runtime.py", "manage_boot_hook.py", "reload_screensaver.py"):
                path = root / name
                path.write_bytes(artifacts[name])
                result = subprocess.run([sys.executable, str(path), "--help"],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(list(root.rglob("*.pyc")))
            self.assertFalse(list(root.rglob("__pycache__")))

    def test_no_argument_help_and_import_paths_do_not_create_state_or_bytecode(self):
        with tempfile.TemporaryDirectory() as temp:
            cases = [
                (str(OPTIONAL / "prepare.py"), ["--help"], 0),
                (str(OPTIONAL / "prepare.py"), [], 2),
                (str(OPTIONAL / "install.py"), ["--help"], 0),
                (str(OPTIONAL / "install.py"), [], 2),
            ]
            for script, arguments, expected in cases:
                result = subprocess.run([sys.executable, script] + arguments,
                                        cwd=temp, capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stderr)
            self.assertFalse((Path(temp) / ".local-state").exists())
            self.assertFalse(list(OPTIONAL.rglob("*.pyc")))
            self.assertFalse(list(OPTIONAL.rglob("__pycache__")))


class InstallStageTests(unittest.TestCase):
    def _fixture_package(self, root):
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / ".gitignore").write_text(".local-state/\n", encoding="utf-8")
        state = root / ".local-state"
        state.mkdir(mode=0o700)
        package_dir = state / "package"
        package_dir.mkdir(mode=0o700)
        artifacts, manifest = build_bundle()
        for name, data in artifacts.items():
            path = package_dir / name
            path.write_bytes(data)
            if os.name == "posix":
                os.chmod(path, 0o700 if name.endswith((".py", ".sh")) else 0o600)
        original = {
            "MainView.qml": hashlib.sha256(MAINVIEW_FIXTURE).hexdigest(),
            "ScreenSaver.qml": hashlib.sha256(SCREENSAVER_FIXTURE).hexdigest(),
        }
        return state, package_dir, artifacts, manifest, original

    def _patch_local_paths(self, root, state, original):
        return (patch.object(install, "ROOT", root),
                patch.object(install, "LOCAL_STATE", state),
                patch.object(install, "ORIGINAL", original))

    @unittest.skipUnless(shutil.which("git"), "Git is required to test local package checks")
    def test_check_is_local_only_and_validates_all_package_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state, package_dir, artifacts, manifest, original = self._fixture_package(root)
            with self._patch_local_paths(root, state, original)[0], \
                    self._patch_local_paths(root, state, original)[1], \
                    self._patch_local_paths(root, state, original)[2], \
                    patch.object(install, "_ssh", side_effect=AssertionError("check must not connect")), \
                    patch("sys.stdout", new=io.StringIO()) as output:
                self.assertEqual(install.main(["--package-dir", str(package_dir), "--check"]), 0)
                self.assertTrue(json.loads(output.getvalue())["package_verified"])
            (package_dir / "reload_screensaver.py").write_bytes(b"tampered")
            with self._patch_local_paths(root, state, original)[0], \
                    self._patch_local_paths(root, state, original)[1], \
                    self._patch_local_paths(root, state, original)[2]:
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    install.validate_package(package_dir)

    @unittest.skipUnless(shutil.which("git"), "Git is required to test staging guards")
    def test_install_requires_explicit_ack_and_does_not_contact_on_default_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state, package_dir, artifacts, manifest, original = self._fixture_package(root)
            with self._patch_local_paths(root, state, original)[0], \
                    self._patch_local_paths(root, state, original)[1], \
                    self._patch_local_paths(root, state, original)[2], \
                    patch.object(install, "_ssh", side_effect=AssertionError("must not connect")):
                with patch("sys.stdout", new=io.StringIO()):
                    self.assertEqual(install.main(["--package-dir", str(package_dir)]), 2)
                with self.assertRaises(SystemExit):
                    install.main(["--package-dir", str(package_dir), "--install", "--target-alias", "tv"])
                with self.assertRaises(SystemExit):
                    install.main(["--package-dir", str(package_dir), "--check", "--target-alias", "tv"])

    @unittest.skipUnless(shutil.which("git"), "Git is required to exercise staging")
    def test_acknowledged_stage_uses_pinned_ssh_binary_stdin_and_hash_readback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state, package_dir, artifacts, manifest, original = self._fixture_package(root)
            calls = []
            real_run = subprocess.run
            def fake_run(command, **kwargs):
                if command[0] == "git":
                    return real_run(command, **kwargs)
                calls.append((command, kwargs))
                remote = command[-1]
                if "sha256sum" in remote and install.BASE not in remote:
                    rows = ["%s  %s" % (install.ORIGINAL[name], install.TARGETS[name])
                            for name in sorted(install.TARGETS)]
                    stdout = ("\n".join(rows) + "\n").encode("ascii")
                elif "sha256sum" in remote:
                    rows = []
                    for name in install.FILES:
                        rows.append("%s  %s/%s" %
                                    (hashlib.sha256((package_dir / name).read_bytes()).hexdigest(),
                                     install.BASE, name))
                    stdout = ("\n".join(rows) + "\n").encode("ascii")
                else:
                    stdout = b""
                return types.SimpleNamespace(returncode=0, stdout=stdout, stderr=b"")
            with self._patch_local_paths(root, state, original)[0], \
                    self._patch_local_paths(root, state, original)[1], \
                    self._patch_local_paths(root, state, original)[2], \
                    patch.object(install.shutil, "which", return_value="/usr/bin/ssh"), \
                    patch.object(install.subprocess, "run", side_effect=fake_run):
                receipt = install.stage(package_dir, "tv-test")
            self.assertEqual(receipt["verified_file_count"], 9)
            self.assertTrue(receipt["network_used"])
            self.assertFalse(receipt["apply_performed"])
            self.assertFalse(receipt["reload_performed"])
            self.assertFalse(receipt["visible_rendering_verified"])
            self.assertFalse(receipt["boot_hook_installed"])
            self.assertEqual(len(calls), len(install.FILES) + 3)
            preflight_command = calls[0][0][-1]
            self.assertIn('test "$(id -u)" = 0', preflight_command)
            self.assertIn('test "$(cat /etc/version)" = "%s"' % install.BUILD, preflight_command)
            for command, kwargs in calls:
                self.assertIn("-o", command)
                self.assertIn("StrictHostKeyChecking=yes", command)
                self.assertIn("ForwardAgent=no", command)
                self.assertIn("ClearAllForwardings=yes", command)
                self.assertEqual(command[-2], "tv-test")
            transfers = [(command, kwargs) for command, kwargs in calls if "cat >" in command[-1]]
            self.assertEqual(len(transfers), len(install.FILES))
            for command, kwargs in transfers:
                filename = Path(command[-1].split("cat > '", 1)[1].rstrip("' ")).name
                self.assertIsInstance(kwargs["input"], bytes)
                self.assertEqual(kwargs["input"], (package_dir / filename).read_bytes())

    @unittest.skipUnless(shutil.which("git"), "Git is required to exercise staging")
    def test_stage_uses_validated_snapshot_even_if_local_files_and_manifest_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state, package_dir, artifacts, manifest, original = self._fixture_package(root)
            uploaded = {}
            def fake_ssh(alias, command, data=None):
                if "sha256sum" in command and install.BASE not in command:
                    # A concurrent local editor changes both payload and manifest
                    # after validation, while remote preflight is in progress.
                    changed = b"# synthetic changed script after validation\n"
                    (package_dir / "reload_screensaver.py").write_bytes(changed)
                    edited = json.loads((package_dir / "manifest.json").read_text())
                    edited["package_sha256"]["reload_screensaver.py"] = hashlib.sha256(changed).hexdigest()
                    (package_dir / "manifest.json").write_text(json.dumps(edited))
                    rows = ["%s  %s" % (original[name], install.TARGETS[name]) for name in sorted(original)]
                    output = ("\n".join(rows) + "\n").encode("ascii")
                elif "cat >" in command:
                    name = Path(command.split("cat > '", 1)[1].rstrip("' ")).name
                    uploaded[name] = data
                    output = b""
                elif "sha256sum" in command:
                    rows = ["%s  %s/%s" % (hashlib.sha256(uploaded[name]).hexdigest(), install.BASE, name)
                            for name in install.FILES]
                    output = ("\n".join(rows) + "\n").encode("ascii")
                else:
                    output = b""
                return types.SimpleNamespace(returncode=0, stdout=output, stderr=b"")
            with patch.multiple(install, ROOT=root, LOCAL_STATE=state, ORIGINAL=original), \
                    patch.object(install.shutil, "which", return_value="/usr/bin/ssh"), \
                    patch.object(install, "_ssh", side_effect=fake_ssh):
                result = install.stage(package_dir, "tv-test")
            self.assertTrue(result["staged"])
            self.assertNotEqual((package_dir / "reload_screensaver.py").read_bytes(), artifacts["reload_screensaver.py"])
            self.assertTrue(uploaded == artifacts, "staging uploaded bytes different from the validated snapshot")

    @unittest.skipUnless(shutil.which("git"), "Git is required to exercise staging")
    def test_wrong_device_build_refuses_before_staging(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state, package_dir, artifacts, manifest, original = self._fixture_package(root)
            failed_preflight = types.SimpleNamespace(returncode=1, stdout=b"", stderr=b"")
            with patch.multiple(install, ROOT=root, LOCAL_STATE=state, ORIGINAL=original), patch.object(install.shutil, "which", return_value="/usr/bin/ssh"), patch.object(install, "_ssh", return_value=failed_preflight) as ssh:
                with self.assertRaisesRegex(RuntimeError, "root/build/target preflight"):
                    install.stage(package_dir, "tv-test")
                ssh.assert_called_once()
                self.assertIn(install.BUILD, ssh.call_args.args[1])
                self.assertNotIn(install.BASE, ssh.call_args.args[1])

    @unittest.skipUnless(shutil.which("git"), "Git is required to exercise staging")
    def test_device_source_hash_mismatch_refuses_before_creating_stage_area(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state, package_dir, artifacts, manifest, original = self._fixture_package(root)
            wrong = {"MainView.qml": "0" * 64, "ScreenSaver.qml": original["ScreenSaver.qml"]}
            rows = ["%s  %s" % (wrong[name], install.TARGETS[name])
                    for name in sorted(install.TARGETS)]
            preflight_result = types.SimpleNamespace(returncode=0,
                                                     stdout=("\n".join(rows) + "\n").encode("ascii"),
                                                     stderr=b"")
            with patch.multiple(install, ROOT=root, LOCAL_STATE=state, ORIGINAL=original), patch.object(install.shutil, "which", return_value="/usr/bin/ssh"), patch.object(install, "_ssh", return_value=preflight_result) as ssh:
                with self.assertRaisesRegex(RuntimeError, "source hash mismatch"):
                    install.stage(package_dir, "tv-test")
                ssh.assert_called_once()
                self.assertIn("/etc/version", ssh.call_args.args[1])
                self.assertNotIn(install.BASE, ssh.call_args.args[1])

    @unittest.skipUnless(shutil.which("git"), "Git is required to exercise staging failure")
    def test_existing_remote_base_or_bad_readback_stops_without_claiming_install(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state, package_dir, artifacts, manifest, original = self._fixture_package(root)
            real_run = subprocess.run
            def remote_exists(command, **kwargs):
                if command[0] == "git":
                    return real_run(command, **kwargs)
                if "sha256sum" in command[-1]:
                    rows = ["%s  %s" % (install.ORIGINAL[name], install.TARGETS[name])
                            for name in sorted(install.TARGETS)]
                    return types.SimpleNamespace(returncode=0,
                                                 stdout=("\n".join(rows) + "\n").encode("ascii"),
                                                 stderr=b"")
                return types.SimpleNamespace(returncode=1, stdout=b"", stderr=b"")
            with self._patch_local_paths(root, state, original)[0], \
                    self._patch_local_paths(root, state, original)[1], \
                    self._patch_local_paths(root, state, original)[2], \
                    patch.object(install.shutil, "which", return_value="/usr/bin/ssh"), \
                    patch.object(install.subprocess, "run", side_effect=remote_exists) as run:
                with self.assertRaisesRegex(RuntimeError, "base was not created"):
                    install.stage(package_dir, "tv-test")
                self.assertEqual(len([call for call in run.call_args_list if call.args[0][0] == "ssh"]), 2)
            calls = []
            real_run = subprocess.run
            def bad_hash(command, **kwargs):
                if command[0] == "git":
                    return real_run(command, **kwargs)
                calls.append(command)
                remote = command[-1]
                if "sha256sum" in remote and install.BASE not in remote:
                    rows = ["%s  %s" % (install.ORIGINAL[name], install.TARGETS[name])
                            for name in sorted(install.TARGETS)]
                    stdout = ("\n".join(rows) + "\n").encode("ascii")
                elif "sha256sum" in remote:
                    rows = ["0" * 64 + "  %s/%s" % (install.BASE, name) for name in install.FILES]
                    stdout = ("\n".join(rows) + "\n").encode("ascii")
                else:
                    stdout = b""
                return types.SimpleNamespace(returncode=0, stdout=stdout, stderr=b"")
            with self._patch_local_paths(root, state, original)[0], \
                    self._patch_local_paths(root, state, original)[1], \
                    self._patch_local_paths(root, state, original)[2], \
                    patch.object(install.shutil, "which", return_value="/usr/bin/ssh"), \
                    patch.object(install.subprocess, "run", side_effect=bad_hash):
                with self.assertRaisesRegex(RuntimeError, "readback did not match"):
                    install.stage(package_dir, "tv-test")

    @unittest.skipUnless(os.name == "posix" and shutil.which("git"),
                         "symlink escape test requires POSIX/WSL and Git")
    def test_package_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state, package_dir, artifacts, manifest, original = self._fixture_package(root)
            outside = root / "outside"
            outside.mkdir()
            link = state / "escape"
            link.symlink_to(outside, target_is_directory=True)
            with self._patch_local_paths(root, state, original)[0], \
                    self._patch_local_paths(root, state, original)[1], \
                    self._patch_local_paths(root, state, original)[2]:
                with self.assertRaisesRegex(ValueError, "symlink"):
                    install.validate_package(link / "package")


@unittest.skipUnless(os.name == "posix", "device mount lifecycle needs POSIX directory locks and private modes")
class RuntimeMountTests(unittest.TestCase):
    def setUp(self):
        self.artifacts, _ = build_bundle()
        self.runtime = load_artifact(self.artifacts, "overlay_runtime.py", "screensaver_runtime_tests")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.runtime.BASE = str(root / "base")
        Path(self.runtime.BASE).mkdir()
        os.chmod(self.runtime.BASE, 0o700)
        self.runtime.TARGETS = {
            "ScreenSaver.qml": str(root / "target-screen.qml"),
            "MainView.qml": str(root / "target-main.qml"),
        }
        self.runtime.ORIGINAL = {name: hashlib.sha256((name + "-original").encode()).hexdigest()
                                 for name in self.runtime.TARGETS}
        self.runtime.PATCHED = {name: hashlib.sha256((name + "-patched").encode()).hexdigest()
                                for name in self.runtime.TARGETS}
        for name, target in self.runtime.TARGETS.items():
            Path(target).write_bytes((name + "-original").encode())
            Path(self.runtime.BASE, name + ".patched.qml").write_bytes((name + "-patched").encode())
        self.boot = "test-boot-id"

    def _owned_fixture(self, name="ScreenSaver.qml"):
        target = self.runtime.TARGETS[name]
        source = os.path.join(self.runtime.BASE, name + ".patched.qml")
        os.unlink(target)
        os.link(source, target)
        row = {"id": "42", "mountpoint": target, "options": ["ro", "relatime"], "super_options": ["rw"]}
        record = self.runtime._state_record(name, "42")
        return row, record

    def test_unmounted_original_and_owned_read_only_instance(self):
        name = "ScreenSaver.qml"
        self.assertEqual(self.runtime._target_status(name, {}), "original")
        row, record = self._owned_fixture(name)
        state = {"boot_id": self.boot, "mounts": {name: record}}
        with patch.object(self.runtime, "boot_id", return_value=self.boot), \
                patch.object(self.runtime, "mount_rows", side_effect=lambda target=None: [row] if target else [row]):
            self.assertEqual(self.runtime._target_status(name, state), "owned-ro")

    def test_foreign_stacked_writable_drift_and_nested_mounts_refuse(self):
        name = "ScreenSaver.qml"
        row, record = self._owned_fixture(name)
        state = {"boot_id": self.boot, "mounts": {name: record}}
        def rows_for(rows):
            return lambda target=None: rows if target is None else [row for row in rows if row["mountpoint"] == target]
        with patch.object(self.runtime, "boot_id", return_value=self.boot), \
                patch.object(self.runtime, "mount_rows", side_effect=rows_for([row])):
            with self.assertRaisesRegex(RuntimeError, "unowned mount"):
                self.runtime._target_status(name, {})
        with patch.object(self.runtime, "boot_id", return_value=self.boot), \
                patch.object(self.runtime, "mount_rows", side_effect=rows_for([row, dict(row)])):
            with self.assertRaisesRegex(RuntimeError, "stacked"):
                self.runtime._target_status(name, state)
        writable = dict(row, options=["rw", "relatime"])
        with patch.object(self.runtime, "boot_id", return_value=self.boot), \
                patch.object(self.runtime, "mount_rows", side_effect=rows_for([writable])):
            with self.assertRaisesRegex(RuntimeError, "writable"):
                self.runtime._target_status(name, state)
        drift = dict(row, id="43")
        with patch.object(self.runtime, "boot_id", return_value=self.boot), \
                patch.object(self.runtime, "mount_rows", side_effect=rows_for([drift])):
            with self.assertRaisesRegex(RuntimeError, "instance changed"):
                self.runtime._target_status(name, state)
        nested = dict(row, mountpoint=self.runtime.TARGETS[name] + "/child")
        with patch.object(self.runtime, "boot_id", return_value=self.boot), \
                patch.object(self.runtime, "mount_rows", side_effect=rows_for([row, nested])):
            with self.assertRaisesRegex(RuntimeError, "nested mount"):
                self.runtime._target_status(name, state)

    def test_unknown_original_content_refuses_without_mount(self):
        name = "MainView.qml"
        Path(self.runtime.TARGETS[name]).write_bytes(b"unrecognized source")
        with patch.object(self.runtime, "mount_rows", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "unknown unmounted content"):
                self.runtime._target_status(name, {})

    def test_apply_partial_remount_failure_cleans_only_new_bind_instances(self):
        runtime = self.runtime
        rows = {}
        calls = []
        def mount_rows(target=None):
            if target is None:
                return [row for group in rows.values() for row in group]
            return rows.get(target, [])
        def call(args):
            calls.append(args)
            if args[:2] == ["mount", "--bind"]:
                source, target = args[2], args[3]
                rows[target] = [{"id": str(len(rows) + 10), "mountpoint": target,
                                 "options": ["rw"], "super_options": ["rw"]}]
            elif args[:2] == ["mount", "-o"]:
                target = args[-1]
                if target == runtime.TARGETS["ScreenSaver.qml"]:
                    raise subprocess.CalledProcessError(1, args)
                rows[target][0]["options"] = ["ro"]
            elif args[0] == "umount":
                rows.pop(args[1], None)
        def inode(path):
            for index, (name, target) in enumerate(runtime.TARGETS.items(), 1):
                source = os.path.join(runtime.BASE, name + ".patched.qml")
                if path == source or (path == target and target in rows):
                    return [2, index]
                if path == target:
                    return [1, index]
            raise AssertionError("unexpected inode path: " + path)
        def file_hash(path):
            for name, target in runtime.TARGETS.items():
                if path == target and target not in rows:
                    return runtime.ORIGINAL[name]
                if path == target or path.endswith(name + ".patched.qml"):
                    return runtime.PATCHED[name]
            raise AssertionError("unexpected digest path: " + path)
        with patch.object(runtime, "_load_manifest", return_value={}), \
                patch.object(runtime, "_disabled_state", return_value=False), \
                patch.object(runtime, "_load_state", return_value={"boot_id": "", "mounts": {}}), \
                patch.object(runtime, "_target_status", return_value="original"), \
                patch.object(runtime, "_ensure_checkpoints") as checkpoints, \
                patch.object(runtime, "boot_id", return_value=self.boot), \
                patch.object(runtime, "mount_rows", side_effect=mount_rows), \
                patch.object(runtime, "_same_file", return_value=True), \
                patch.object(runtime, "_inode", side_effect=inode), \
                patch.object(runtime, "file_digest", side_effect=file_hash), \
                patch.object(runtime, "_save_state") as save_state, \
                patch.object(runtime.subprocess, "check_call", side_effect=call):
            with self.assertRaises(subprocess.CalledProcessError):
                runtime.apply_mounts()
        checkpoints.assert_called_once_with(["MainView.qml", "ScreenSaver.qml"])
        save_state.assert_not_called()
        self.assertEqual(rows, {})
        self.assertEqual([entry[0] for entry in calls if entry[0] == "umount"], ["umount", "umount"])
        self.assertFalse(any("-l" in entry for entry in calls))

    def test_apply_binds_both_targets_readonly_without_reloading_or_claiming_render(self):
        runtime = self.runtime
        state = {"version": 1, "boot_id": "", "mounts": {}}
        rows = {}
        calls = []
        def mount_rows(target=None):
            if target is None:
                return [row for group in rows.values() for row in group]
            return rows.get(target, [])
        def call(args):
            calls.append(args)
            if args[:2] == ["mount", "--bind"]:
                target = args[3]
                rows[target] = [{"id": str(100 + len(rows)), "mountpoint": target,
                                 "options": ["rw"], "super_options": ["rw"]}]
            elif args[:2] == ["mount", "-o"]:
                rows[args[-1]][0]["options"] = ["ro"]
        def inode(path):
            for index, (name, target) in enumerate(runtime.TARGETS.items(), 1):
                source = os.path.join(runtime.BASE, name + ".patched.qml")
                if path == source or (path == target and target in rows):
                    return [2, index]
                if path == target:
                    return [1, index]
            raise AssertionError("unexpected inode path: " + path)
        def digest(path):
            for name, target in runtime.TARGETS.items():
                if path == target and target not in rows:
                    return runtime.ORIGINAL[name]
                if path == target or path.endswith(name + ".patched.qml"):
                    return runtime.PATCHED[name]
            raise AssertionError("unexpected digest path: " + path)
        def save_state(value):
            state.clear()
            state.update(value)
        checkpoints = Mock()
        with patch.multiple(runtime,
                            _load_manifest=Mock(return_value={}),
                            _disabled_state=Mock(return_value=False),
                            _load_state=Mock(side_effect=lambda: state),
                            _ensure_checkpoints=checkpoints,
                            boot_id=Mock(return_value=self.boot),
                            mount_rows=Mock(side_effect=mount_rows),
                            _same_file=Mock(return_value=True),
                            _inode=Mock(side_effect=inode),
                            file_digest=Mock(side_effect=digest),
                            _save_state=Mock(side_effect=save_state)):
            with patch.object(runtime.subprocess, "check_call", side_effect=call):
                result = runtime.apply_mounts()
        self.assertEqual(result["changed"], 2)
        self.assertEqual(result["status"]["mounts"], {name: "owned-ro" for name in runtime.TARGETS})
        self.assertTrue(result["apply_performed"])
        self.assertFalse(result["reload_performed"])
        self.assertFalse(result["visible_rendering_verified"])
        self.assertEqual(len([args for args in calls if args[:2] == ["mount", "--bind"]]), 2)
        self.assertEqual(len([args for args in calls if args[:2] == ["mount", "-o"]]), 2)
        self.assertFalse(any("umount" in args for args in calls))
        checkpoints.assert_called_once_with(sorted(runtime.TARGETS))

    def test_rollback_disables_future_apply_and_detaches_only_owned(self):
        runtime = self.runtime
        name = "ScreenSaver.qml"
        row, record = self._owned_fixture(name)
        state = {"version": 1, "boot_id": self.boot, "mounts": {name: record}}
        rows = {runtime.TARGETS[name]: [row]}
        calls = []
        def mount_rows(target=None):
            if target is None:
                return [item for group in rows.values() for item in group]
            return rows.get(target, [])
        def call(args):
            calls.append(args)
            rows.pop(args[1], None)
        inspect_result = {"mounts": {n: "original" for n in runtime.TARGETS}, "disabled": True}
        with patch.object(runtime, "_load_manifest", return_value={}), \
                patch.object(runtime, "_load_state", return_value=state), \
                patch.object(runtime, "_target_status", side_effect=lambda n, s: "owned-ro" if n == name else "original"), \
                patch.object(runtime, "boot_id", return_value=self.boot), \
                patch.object(runtime, "mount_rows", side_effect=mount_rows), \
                patch.object(runtime, "_same_file", return_value=True), \
                patch.object(runtime, "file_digest", side_effect=lambda path: runtime.ORIGINAL[
                    "ScreenSaver.qml" if "target-screen" in path else "MainView.qml"]), \
                patch.object(runtime, "_save_state") as save_state, \
                patch.object(runtime, "_inspect_unlocked", return_value=inspect_result), \
                patch.object(runtime.subprocess, "check_call", side_effect=call):
            result = runtime.rollback_mounts()
        self.assertTrue((Path(runtime.BASE) / "disabled").exists())
        self.assertEqual((Path(runtime.BASE) / "disabled").read_text(), "screensaver-override-disabled-v1\n")
        self.assertEqual(calls, [["umount", runtime.TARGETS[name]]])
        self.assertTrue(result["future_apply_disabled"])
        self.assertTrue(result["checkpoint_files_retained"])
        self.assertTrue(result["rollback_performed"])
        self.assertFalse(result["reload_performed"])
        self.assertFalse(result["visible_rendering_verified"])
        self.assertEqual(save_state.call_count, 2)

    def test_foreign_rollback_creates_no_disable_marker_and_unmounts_nothing(self):
        runtime = self.runtime
        with patch.object(runtime, "_load_manifest", return_value={}), \
                patch.object(runtime, "_load_state", return_value={"boot_id": "", "mounts": {}}), \
                patch.object(runtime, "_target_status", side_effect=["foreign", "original"]), \
                patch.object(runtime.subprocess, "check_call") as call:
            with self.assertRaisesRegex(RuntimeError, "rollback refused"):
                runtime.rollback_mounts()
        self.assertFalse((Path(runtime.BASE) / "disabled").exists())
        call.assert_not_called()

    def test_cli_defaults_and_acknowledgement_guards_do_not_touch_mounts(self):
        runtime = self.runtime
        with patch.object(runtime, "inspect", side_effect=AssertionError("must not inspect")), \
                patch.object(runtime.subprocess, "check_call") as call:
            self.assertEqual(runtime.main([]), 2)
            with self.assertRaises(SystemExit):
                runtime.main(["--apply"])
            with self.assertRaises(SystemExit):
                runtime.main(["--rollback"])
            call.assert_not_called()

    def test_boot_marker_turns_hook_into_read_only_no_op(self):
        runtime = self.runtime
        status = {"mounts": {name: "original" for name in runtime.TARGETS}, "disabled": True}
        with patch.object(runtime, "_load_manifest", return_value={}), \
                patch.object(runtime, "_disabled_state", return_value=True), \
                patch.object(runtime, "_inspect_unlocked", return_value=status), \
                patch.object(runtime.os, "geteuid", return_value=0), \
                patch.object(runtime.subprocess, "check_call") as call:
            self.assertEqual(runtime.main(["--apply", "--ack-mount", "--boot"]), 0)
            call.assert_not_called()


class BootManagerTests(unittest.TestCase):
    def setUp(self):
        self.artifacts, _ = build_bundle()
        self.manager = load_artifact(self.artifacts, "manage_boot_hook.py", "screensaver_boot_manager_tests")

    def test_exact_hook_install_remove_idempotence_and_foreign_refusal(self):
        manager = self.manager
        expected = b"#!/bin/sh\nexec python /fixed/base/overlay_runtime.py --apply --ack-mount --boot\n"
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "hook")
            with patch.object(manager, "hook_state", side_effect=["absent", "owned"]):
                self.assertTrue(manager.install_hook(path, expected))
            self.assertEqual(Path(path).read_bytes(), expected)
            with patch.object(manager, "hook_state", return_value="foreign"):
                with self.assertRaisesRegex(RuntimeError, "foreign boot hook"):
                    manager.install_hook(path, expected)
            with patch.object(manager, "hook_state", side_effect=["owned", "absent"]):
                self.assertTrue(manager.remove_hook(path, expected))
            self.assertFalse(Path(path).exists())
            with patch.object(manager, "hook_state", return_value="foreign"):
                Path(path).write_bytes(b"foreign\n")
                with self.assertRaisesRegex(RuntimeError, "foreign boot hook"):
                    manager.remove_hook(path, expected)
                self.assertEqual(Path(path).read_bytes(), b"foreign\n")

    def test_hook_state_detects_absent_foreign_file_and_symlink(self):
        manager = self.manager
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "hook"
            expected = b"exact\n"
            self.assertEqual(manager.hook_state(str(path), expected), "absent")
            path.write_bytes(b"other\n")
            self.assertEqual(manager.hook_state(str(path), expected), "foreign")
            if os.name == "posix":
                path.unlink()
                path.symlink_to(Path(temp) / "missing")
                self.assertEqual(manager.hook_state(str(path), expected), "foreign")

    def test_no_action_and_unacknowledged_install_do_not_read_or_write(self):
        manager = self.manager
        with patch.object(manager, "package", side_effect=AssertionError("must not inspect package")), \
                patch.object(manager, "install_hook", side_effect=AssertionError("must not install")):
            self.assertEqual(manager.main([]), 2)
            with self.assertRaises(SystemExit):
                manager.main(["--install"])

    @unittest.skipUnless(os.name == "posix", "device hook install requires POSIX root-identity checks")
    def test_check_is_read_only_and_install_requires_active_owned_mounts(self):
        manager = self.manager
        overlay = {"disabled": False, "mounts": {"ScreenSaver.qml": "owned-ro", "MainView.qml": "owned-ro"}}
        with patch.object(manager, "package", return_value=({}, overlay)), \
                patch.object(manager, "_expected_hook", return_value=b"hook"), \
                patch.object(manager, "_hook_directory"), \
                patch.object(manager, "hook_state", return_value="absent"), \
                patch.object(manager, "install_hook") as install:
            result = manager.main(["--check"])
            self.assertEqual(result, 0)
            install.assert_not_called()
        inactive = {"disabled": False, "mounts": {"ScreenSaver.qml": "original", "MainView.qml": "original"}}
        with patch.object(manager, "package", return_value=({}, inactive)), \
                patch.object(manager, "_expected_hook", return_value=b"hook"), \
                patch.object(manager, "_hook_directory"), \
                patch.object(manager.os, "geteuid", return_value=0), \
                patch.object(manager, "install_hook") as install:
            with self.assertRaisesRegex(RuntimeError, "only after both owned"):
                manager.main(["--install", "--ack-install"])
            install.assert_not_called()


class ReloadTests(unittest.TestCase):
    def setUp(self):
        self.artifacts, _ = build_bundle()
        self.reload = load_artifact(self.artifacts, "reload_screensaver.py", "screensaver_reload_tests")
        self.schemas = {
            "closeByAppId": {"required": ["id"], "properties": {"id": {"type": "string"}}},
            "launch": {"required": ["id"], "properties": {
                "id": {"type": "string"}, "spinner": {"type": "boolean"},
                "noSplash": {"type": "boolean"}, "checkUpdateOnLaunch": {"type": "boolean"},
            }},
        }
        self.before = {"foreground": "com.webos.app.home", "apps": [
            {"id": "com.webos.app.home", "pid": 10, "start": "home-1"},
            {"id": self.reload.APP, "pid": 20, "start": "saver-1"},
            {"id": "com.webos.app.youtube", "pid": 30, "start": "youtube-1"},
        ]}
        self.fresh = {"foreground": "com.webos.app.home", "apps": [
            {"id": "com.webos.app.home", "pid": 10, "start": "home-1"},
            {"id": self.reload.APP, "pid": 21, "start": "saver-2"},
            {"id": "com.webos.app.youtube", "pid": 30, "start": "youtube-1"},
        ]}
        self.closed = {"foreground": "com.webos.app.home", "apps": [
            {"id": "com.webos.app.home", "pid": 10, "start": "home-1"},
            {"id": "com.webos.app.youtube", "pid": 30, "start": "youtube-1"},
        ]}

    def test_schema_payload_validation_is_strict_and_schema_first(self):
        reload = self.reload
        loader = lambda name: self.schemas[name]
        self.assertTrue(reload.validate_payload(reload.CLOSE_METHOD, reload.CLOSE_PAYLOAD, loader))
        with self.assertRaisesRegex(ValueError, "requires"):
            reload.validate_payload(reload.CLOSE_METHOD, {"id": reload.APP},
                                    lambda name: {"required": ["id", "extra"],
                                                  "properties": {"id": {"type": "string"}}})
        with self.assertRaisesRegex(ValueError, "does not allow"):
            reload.validate_payload(reload.CLOSE_METHOD, {"id": reload.APP, "extra": True}, loader)
        with self.assertRaisesRegex(ValueError, "expects"):
            reload.validate_payload(reload.LAUNCH_METHOD, {"id": reload.APP, "spinner": "yes"}, loader)
        def reject_launch(name):
            if name == "launch":
                return {"required": ["missing"], "properties": {}}
            return self.schemas[name]
        with patch.object(reload, "_check_overlay", return_value={}), \
                patch.object(reload, "native_state") as state:
            with self.assertRaisesRegex(ValueError, "requires"):
                reload.reload_screensaver(api=lambda *args: self.fail("no native call"), schema_loader=reject_launch)
            state.assert_not_called()

    def test_native_reload_closes_and_relaunches_only_screensaver(self):
        reload = self.reload
        requests = []
        def api(method, payload):
            requests.append((method, payload))
            return {"returnValue": True}
        with patch.object(reload, "_check_overlay", return_value={"mounts": {"ScreenSaver.qml": "owned-ro"}}), \
                patch.object(reload, "native_state", side_effect=[self.before, self.closed, self.fresh]), \
                patch.object(reload, "_runner", return_value=(b"qml argv", {"snapshot": False})), \
                patch.object(reload, "_wait_old_exit", return_value=[]), \
                patch.object(reload, "_wait_fresh", return_value=(self.fresh, [self.fresh["apps"][1]])):
            result = reload.reload_screensaver(api=api, schema_loader=lambda name: self.schemas[name])
        self.assertEqual([method for method, payload in requests], [reload.CLOSE_METHOD, reload.LAUNCH_METHOD])
        self.assertEqual(requests[0][1], {"id": reload.APP})
        self.assertEqual(requests[1][1], reload.LAUNCH_PAYLOAD)
        self.assertTrue(result["foreground_unchanged"])
        self.assertTrue(result["other_app_identities_unchanged"])
        self.assertFalse(result["visible_rendering_verified"])
        self.assertEqual(result["fresh_screensaver"][0]["pid"], 21)

    def test_failure_after_close_attempts_truthful_bounded_recovery(self):
        reload = self.reload
        api = Mock(return_value={"returnValue": True})
        with patch.object(reload, "_check_overlay", return_value={}), \
                patch.object(reload, "native_state", side_effect=[self.before, self.closed]), \
                patch.object(reload, "_runner", return_value=(b"qml argv", {"snapshot": False})), \
                patch.object(reload, "_wait_old_exit", return_value=[]), \
                patch.object(reload, "_wait_fresh", side_effect=RuntimeError("no fresh process")), \
                patch.object(reload, "_bounded_relaunch_recovery", return_value={
                    "attempted": True, "fresh_processes": [], "rendered_mode_verified": False,
                }) as recovery:
            with self.assertRaisesRegex(RuntimeError, "rendered mode is not claimed restored"):
                reload.reload_screensaver(api=api, schema_loader=lambda name: self.schemas[name])
        recovery.assert_called_once()
        self.assertTrue(any(call.args[0] == reload.LAUNCH_METHOD for call in api.call_args_list))

    def test_recovery_attempts_one_bounded_launch_when_no_screensaver_remains(self):
        reload = self.reload
        empty = {"foreground": "com.webos.app.home", "apps": [self.before["apps"][0]]}
        launched = {"foreground": "com.webos.app.home", "apps": [self.before["apps"][0], self.fresh["apps"][1]]}
        api = Mock(return_value={"returnValue": True})
        with patch.object(reload, "native_state", side_effect=[empty, launched]):
            result = reload._bounded_relaunch_recovery(api, [self.before["apps"][1]], empty["foreground"])
        self.assertTrue(result["attempted"])
        self.assertFalse(result["rendered_mode_verified"])
        api.assert_called_once_with(reload.LAUNCH_METHOD, reload.LAUNCH_PAYLOAD)

    def test_runner_fallback_requires_exact_app_main_and_pid_starttime(self):
        reload = self.reload
        app = {"pid": 123, "start": "stamp"}
        raw = b"/usr/bin/qml-runner\x00{\"appId\":\"com.webos.app.screensaver\",\"main\":\"file:///usr/palm/applications/com.webos.app.screensaver/qml/main.qml\"}\x00"
        with patch.object(reload, "stamp", return_value="stamp"), \
                patch.object(reload.os, "readlink", return_value="/usr/bin/qml-runner"), \
                patch.object(reload, "read", return_value=raw):
            result, params = reload._runner(app)
        self.assertEqual(result, raw)
        self.assertEqual(params["appId"], reload.APP)
        bad = raw.replace(b"com.webos.app.screensaver", b"other.app")
        with patch.object(reload, "stamp", return_value="stamp"), \
                patch.object(reload.os, "readlink", return_value="/usr/bin/qml-runner"), \
                patch.object(reload, "read", return_value=bad):
            with self.assertRaisesRegex(RuntimeError, "appId/main path mismatch"):
                reload._runner(app)
        with patch.object(reload, "stamp", return_value="changed"):
            with self.assertRaisesRegex(RuntimeError, "PID/starttime changed"):
                reload._runner(app)

    @unittest.skipUnless(os.name == "posix", "device PTY select uses POSIX file descriptors, not Windows sockets")
    def test_luna_uses_bounded_pty_and_allowlisted_methods(self):
        reload = self.reload
        with tempfile.TemporaryFile() as output:
            output.write(b'{"returnValue":true,"running":[]}')
            output.seek(0)
            fake = Mock(stdout=output)
            fake.poll.return_value = 0
            with patch.object(reload.subprocess, "Popen", return_value=fake) as popen:
                result = reload.luna(reload.RUNNING_METHOD, {})
            self.assertEqual(result["running"], [])
            args = popen.call_args.args[0]
            self.assertEqual(args[:4], ["script", "-q", "-e", "-c"])
            self.assertIn("luna-send -w 5000 -n 1", args[4])
            self.assertEqual(args[-1], "/dev/null")
        with self.assertRaisesRegex(RuntimeError, "not allowlisted"):
            reload.luna("com.webos.service.system/stop", {})

    def test_luna_timeout_terminates_only_pty_wrapper_without_kill_escalation(self):
        reload = self.reload
        fake = Mock()
        fake.stdout = io.BytesIO(b"")
        fake.stdout.fileno = Mock(return_value=98765)
        fake.poll.return_value = None
        with patch.object(reload.subprocess, "Popen", return_value=fake), \
                patch.object(reload.time, "time", side_effect=[0.0, 8.0]), \
                patch.object(reload.select, "select", return_value=([], [], [])):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                reload.luna(reload.RUNNING_METHOD, {})
        fake.terminate.assert_called_once()
        source = (OPTIONAL / "templates" / "reload_screensaver.py.tpl").read_text(encoding="utf-8")
        self.assertNotIn("SIGKILL", source)
        self.assertNotIn("killall", source)
        self.assertIn("signal.SIGTERM", source)

    def test_no_acknowledgement_never_checks_state_or_calls_luna(self):
        reload = self.reload
        with patch.object(reload, "_check_overlay", side_effect=AssertionError("must not check")), \
                patch.object(reload, "luna", side_effect=AssertionError("must not call Luna")):
            with self.assertRaises(SystemExit):
                reload.main([])
            with self.assertRaises(SystemExit):
                reload.main(["--original"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
