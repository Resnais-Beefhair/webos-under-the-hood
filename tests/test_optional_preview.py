import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PUBLIC = Path(__file__).resolve().parents[1]
OPTIONAL = PUBLIC / "optional-preview"


def load_python_template(name, module_name):
    path = OPTIONAL / "templates" / name
    module = types.ModuleType(module_name)
    module.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
    return module


spec = importlib.util.spec_from_file_location("preview_prepare", OPTIONAL / "prepare.py")
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)
runtime = load_python_template("preview_runtime.py.tpl", "preview_runtime_for_test")
reload_home = load_python_template("reload_home.py.tpl", "reload_home_for_test")
boot_manager = load_python_template("manage_boot_hook.py.tpl", "manage_boot_hook_for_test")


SYNTHETIC_QML = (
    b"// Synthetic test fixture; not LG/webOS source.\n"
    b"    function getAppPreview(launchPoint) {\n"
    b"        samLookup(launchPoint.launchPointId);\n"
    b"    }\n"
)


def build_synthetic_bundle(source):
    patched = source.replace(prepare.ANCHOR, prepare.ANCHOR + prepare.GUARD, 1)
    with patch.object(prepare, "ORIGINAL_SHA256", hashlib.sha256(source).hexdigest()), \
         patch.object(prepare, "PATCHED_SHA256", hashlib.sha256(patched).hexdigest()):
        return prepare.build_bundle(source)


class PrepareTests(unittest.TestCase):
    def test_exact_guard_inserted_once_at_expected_anchor(self):
        source = SYNTHETIC_QML
        patched_bytes = source.replace(prepare.ANCHOR, prepare.ANCHOR + prepare.GUARD, 1)
        with patch.object(prepare, "ORIGINAL_SHA256", hashlib.sha256(source).hexdigest()), \
             patch.object(prepare, "PATCHED_SHA256", hashlib.sha256(patched_bytes).hexdigest()):
            patched = prepare.patch_source(source)
        self.assertEqual(patched.count(prepare.GUARD), 1)
        self.assertIn(prepare.ANCHOR + prepare.GUARD, patched)
        self.assertEqual(patched.count(b"function getAppPreview(launchPoint)"), 1)

    def test_hash_mismatch_missing_anchor_and_duplicate_anchor_refuse(self):
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            prepare.patch_source(SYNTHETIC_QML)
        missing = b"// no target function\n"
        with patch.object(prepare, "ORIGINAL_SHA256", hashlib.sha256(missing).hexdigest()):
            with self.assertRaisesRegex(ValueError, "found 0"):
                prepare.patch_source(missing)
        duplicate = SYNTHETIC_QML + SYNTHETIC_QML
        with patch.object(prepare, "ORIGINAL_SHA256", hashlib.sha256(duplicate).hexdigest()):
            with self.assertRaisesRegex(ValueError, "found 2"):
                prepare.patch_source(duplicate)

    def test_output_is_confined_fresh_and_non_symlink_under_local_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "public-release"
            root.mkdir()
            state = root / ".local-state"
            state.mkdir(mode=0o700)
            with patch.object(prepare, "ROOT", root), patch.object(prepare, "LOCAL_STATE", state):
                safe = prepare.validate_output_dir(".local-state/run-one")
                self.assertEqual(safe, state / "run-one")
                with self.assertRaisesRegex(ValueError, "child of"):
                    prepare.validate_output_dir(Path(temp) / "outside")
                safe.mkdir(parents=True)
                with self.assertRaises(FileExistsError):
                    prepare.validate_output_dir(safe)
                (state / "linked").symlink_to(Path(temp), target_is_directory=True)
                with self.assertRaisesRegex(ValueError, "symlink"):
                    prepare.validate_output_dir(".local-state/linked/run-two")

    def test_generated_artifacts_are_python_syntax_and_contain_no_firmware_fixture(self):
        source = SYNTHETIC_QML
        bundle, manifest = build_synthetic_bundle(source)
        self.assertEqual(manifest["vendor_qml_versioned"], False)
        self.assertEqual(manifest["private_source_storage"], "ignored .local-state only")
        self.assertEqual(bundle["Interfaces.original.qml"], SYNTHETIC_QML)
        self.assertIn(prepare.GUARD, bundle["Interfaces.patched.qml"])
        for name, data in bundle.items():
            if name.endswith(".py"):
                compile(data.decode("utf-8"), name, "exec")
        shell = shutil.which("sh")
        if shell:
            result = subprocess.run([shell, "-n"], input=bundle["home-preview-boot-hook.sh"], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertFalse(any(path.suffix == ".qml" for path in OPTIONAL.rglob("*")))

    def test_bundle_write_is_private_and_refuses_overwrite(self):
        source = SYNTHETIC_QML
        artifacts, _ = build_synthetic_bundle(source)
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / ".local-state"
            state.mkdir(mode=0o700)
            output = state / "bundle"
            with patch.object(prepare, "LOCAL_STATE", state):
                prepare.write_bundle(output, artifacts)
                self.assertEqual((output / "Interfaces.original.qml").read_bytes(), source)
                self.assertEqual((output / "Interfaces.patched.qml").read_bytes(), artifacts["Interfaces.patched.qml"])
                self.assertEqual((output / "Interfaces.original.qml").stat().st_mode & 0o777, 0o600)
                self.assertEqual((output / "preview_runtime.py").stat().st_mode & 0o777, 0o700)
                with self.assertRaises(FileExistsError):
                    prepare.write_bundle(output, artifacts)

    @unittest.skipUnless(shutil.which("node"), "Node.js is optional for QML-guard behavior test")
    def test_synthetic_qml_behavior_is_per_launchpoint(self):
        source = SYNTHETIC_QML
        bundle, _ = build_synthetic_bundle(source)
        patched = bundle["Interfaces.patched.qml"].decode("utf-8")
        match = re.search(r"^    function getAppPreview\(launchPoint\) \{\n[\s\S]*?^    \}", patched, re.M)
        self.assertIsNotNone(match)
        env = dict(os.environ)
        env["SYNTHETIC_FUNCTION"] = match.group(0)
        js = r'''const code=process.env.SYNTHETIC_FUNCTION;
const get=new Function("systemProperties","createPreviewModel","switchModels","samLookup","launchPoint",code+"\nreturn getAppPreview(launchPoint);");
function run(id){const c={models:[],switches:0,lookup:[]};get({youTubeAppId:"youtube.app"},(...a)=>c.models.push(a),()=>c.switches++,x=>c.lookup.push(x),{launchPointId:id});return c;}
const main=run("youtube.app_default"),channel=run("youtube.app_channel-42"),other=run("other.app_default");
if(main.models.length!==1||main.models[0][0]!=="youtube.app_default"||main.models[0][1]!=="app"||main.models[0][2].length!==0||main.switches!==1||main.lookup.length!==0)throw Error("main YouTube guard failed");
if(channel.models.length||channel.switches||channel.lookup[0]!=="youtube.app_channel-42")throw Error("channel launchpoint changed");
if(other.models.length||other.switches||other.lookup[0]!=="other.app_default")throw Error("other app changed");
console.log("main=empty; channel=unchanged; other=unchanged");'''
        result = subprocess.run([shutil.which("node"), "-e", js], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("main=empty; channel=unchanged; other=unchanged", result.stdout)


class MountGuardTests(unittest.TestCase):
    def setUp(self):
        self.source = "/mock/base/Interfaces.patched.qml"
        self.target = "/mock/home/Interfaces.qml"
        self.row = ["/dev/mock", self.target, "ext4", "ro,relatime", "0", "0"]
        self.identity = lambda a, b: (a == self.source and b == self.target)

    def test_mount_state_absent_and_exact_read_only_owned(self):
        self.assertEqual(runtime.mount_state(self.source, self.target, [], self.identity), "absent")
        self.assertEqual(runtime.mount_state(self.source, self.target, [self.row], self.identity), "owned")

    def test_foreign_stacked_nested_and_writable_mounts_refuse(self):
        with self.assertRaisesRegex(RuntimeError, "foreign"):
            runtime.mount_state(self.source, self.target, [self.row], lambda a, b: False)
        with self.assertRaisesRegex(RuntimeError, "stacked"):
            runtime.mount_state(self.source, self.target, [self.row, self.row], self.identity)
        nested = ["/dev/mock", self.target + "/child", "ext4", "ro", "0", "0"]
        with self.assertRaisesRegex(RuntimeError, "nested"):
            runtime.mount_state(self.source, self.target, [self.row, nested], self.identity)
        writable = list(self.row)
        writable[3] = "rw,relatime"
        with self.assertRaisesRegex(RuntimeError, "not read-only"):
            runtime.mount_state(self.source, self.target, [writable], self.identity)

    def test_apply_mounts_remounts_read_only_and_is_idempotent(self):
        plan = [(self.target, self.source, "absent")]
        with patch.object(runtime, "inspect", return_value=plan), \
             patch.object(runtime, "mount_state", side_effect=["absent", "owned"]), \
             patch.object(runtime.subprocess, "check_call") as call:
            self.assertEqual(runtime.apply_mounts(), 1)
            self.assertEqual(call.call_args_list, [
                unittest.mock.call(["mount", "--bind", self.source, self.target]),
                unittest.mock.call(["mount", "-o", "remount,bind,ro", self.target]),
            ])

    def test_apply_owned_mount_is_idempotent(self):
        plan = [(self.target, self.source, "owned")]
        with patch.object(runtime, "inspect", return_value=plan), \
             patch.object(runtime.subprocess, "check_call") as call:
            self.assertEqual(runtime.apply_mounts(), 0)
            call.assert_not_called()

    def test_failed_remount_only_attempts_ordinary_owned_cleanup(self):
        plan = [(self.target, self.source, "absent")]
        rows = [self.row]
        calls = []
        def fake_call(args):
            calls.append(args)
            if args[:2] == ["mount", "-o"]:
                raise subprocess.CalledProcessError(1, args)
        with patch.object(runtime, "inspect", return_value=plan), \
             patch.object(runtime, "mount_state", return_value="absent"), \
             patch.object(runtime, "_mount_rows", side_effect=[rows, []]), \
             patch.object(runtime, "_same_inode", return_value=True), \
             patch.object(runtime.subprocess, "check_call", side_effect=fake_call):
            with self.assertRaises(subprocess.CalledProcessError):
                runtime.apply_mounts()
        self.assertEqual(calls[-1], ["umount", self.target])
        self.assertNotIn(["umount", "-l", self.target], calls)

    def test_no_argument_hook_and_check_mode_do_not_call_mount_tools(self):
        with patch.object(runtime, "inspect", side_effect=AssertionError("should not inspect")), \
             patch.object(runtime.subprocess, "check_call") as call:
            self.assertEqual(runtime.main([]), 2)
            call.assert_not_called()
        with patch.object(runtime, "inspect", return_value=[(self.target, self.source, "owned")]), \
             patch.object(runtime.subprocess, "check_call") as call:
            self.assertEqual(runtime.main(["--check"]), 0)
            call.assert_not_called()


class BootHookTests(unittest.TestCase):
    def test_boot_mounts_need_distinct_reload_consent(self):
        with patch.object(runtime, "apply_mounts") as mounts:
            self.assertEqual(runtime.main(["--boot", "--ack-mount"]), 2)
            mounts.assert_not_called()
        with patch.object(boot_manager, "install_hook") as install:
            self.assertEqual(boot_manager.main(["--install", "--ack-install"]), 2)
            install.assert_not_called()

    def test_boot_reloads_only_when_it_created_mounts(self):
        for changed in (0, 2):
            with self.subTest(changed=changed), \
                 patch.object(runtime, "require_root"), \
                 patch.object(runtime, "apply_mounts", return_value=changed), \
                 patch.object(runtime.subprocess, "check_call") as call:
                self.assertEqual(runtime.main(["--boot", "--ack-mount", "--ack-home-reload"]), 0)
                if changed:
                    self.assertEqual(call.call_args.args[0][-2:], ["--hidden", "--ack-home-reload"])
                else:
                    call.assert_not_called()

    def test_explicit_one_time_mount_never_reloads_home(self):
        with patch.object(runtime, "require_root"), \
             patch.object(runtime, "apply_mounts", return_value=2), \
             patch.object(runtime.subprocess, "check_call") as call:
            self.assertEqual(runtime.main(["--apply", "--ack-mount"]), 0)
            call.assert_not_called()

    def test_hook_manager_and_rollback_no_argument_paths_are_read_only(self):
        with patch.object(boot_manager, "expected_bytes", side_effect=AssertionError("must not read device package")):
            self.assertEqual(boot_manager.main([]), 2)
        sys.modules["preview_runtime"] = runtime
        sys.modules["manage_boot_hook"] = boot_manager
        rollback = load_python_template("rollback_preview.py.tpl", "rollback_preview_for_test")
        try:
            with patch.object(runtime, "inspect", side_effect=AssertionError("must not inspect device mounts")), \
                 patch.object(boot_manager, "hook_state", side_effect=AssertionError("must not inspect hook")):
                self.assertEqual(rollback.main([]), 2)
        finally:
            sys.modules.pop("preview_runtime", None)
            sys.modules.pop("manage_boot_hook", None)

    def test_absent_owned_foreign_idempotent_install_and_owned_remove(self):
        expected = b"#!/bin/sh\nexec python /safe/path/preview_runtime.py --boot --ack-mount\n"
        boot_manager.BOOT_HOOK_SHA256 = hashlib.sha256(expected).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            hook_dir = Path(temp) / "init.d"
            hook_dir.mkdir()
            path = hook_dir / "60-home-preview-override"
            source = Path(temp) / "boot.sh"
            source.write_bytes(expected)
            boot_manager.HOOK_DIR = str(hook_dir)
            boot_manager.HOOK_PATH = str(path)
            boot_manager.BOOT_HOOK = str(source)
            self.assertEqual(boot_manager.hook_state(str(path), expected), "absent")
            self.assertTrue(boot_manager.install_hook(str(path), expected))
            self.assertEqual(path.read_bytes(), expected)
            self.assertEqual(boot_manager.hook_state(str(path), expected), "owned")
            self.assertFalse(boot_manager.install_hook(str(path), expected))
            self.assertTrue(boot_manager.remove_hook(str(path), expected))
            self.assertFalse(path.exists())
            path.write_bytes(b"foreign\n")
            with self.assertRaisesRegex(RuntimeError, "foreign"):
                boot_manager.install_hook(str(path), expected)
            with self.assertRaisesRegex(RuntimeError, "foreign"):
                boot_manager.remove_hook(str(path), expected)
            self.assertEqual(path.read_bytes(), b"foreign\n")


class RollbackTests(unittest.TestCase):
    def setUp(self):
        self.saved_runtime = sys.modules.get("preview_runtime")
        self.saved_manager = sys.modules.get("manage_boot_hook")
        sys.modules["preview_runtime"] = runtime
        sys.modules["manage_boot_hook"] = boot_manager
        self.rollback = load_python_template("rollback_preview.py.tpl", "rollback_preview_for_test")
        self.addCleanup(self._restore_modules)
        self.target = "/mock/home/Interfaces.qml"
        self.source = "/mock/base/Interfaces.patched.qml"

    def _restore_modules(self):
        if self.saved_runtime is None:
            sys.modules.pop("preview_runtime", None)
        else:
            sys.modules["preview_runtime"] = self.saved_runtime
        if self.saved_manager is None:
            sys.modules.pop("manage_boot_hook", None)
        else:
            sys.modules["manage_boot_hook"] = self.saved_manager

    def test_lazy_detach_only_after_busy_owned_read_only_recheck(self):
        process = Mock(returncode=32)
        process.communicate.return_value = (b"umount: target is busy", None)
        with patch.object(runtime, "mount_state", side_effect=["owned", "owned"]), \
             patch.object(self.rollback.subprocess, "Popen", return_value=process), \
             patch.object(self.rollback, "_rows", return_value=[]), \
             patch.object(self.rollback.subprocess, "check_call") as call:
            self.assertTrue(self.rollback.detach_owned(self.target, self.source))
            call.assert_called_once_with(["umount", "-l", self.target])

    def test_lazy_detach_refuses_unrelated_unmount_error_and_foreign_target(self):
        process = Mock(returncode=1)
        process.communicate.return_value = (b"permission denied", None)
        with patch.object(runtime, "mount_state", return_value="owned"), \
             patch.object(self.rollback.subprocess, "Popen", return_value=process), \
             patch.object(self.rollback.subprocess, "check_call") as call:
            with self.assertRaisesRegex(RuntimeError, "ordinary unmount failed"):
                self.rollback.detach_owned(self.target, self.source)
            call.assert_not_called()
        with patch.object(runtime, "mount_state", side_effect=RuntimeError("foreign mount")), \
             patch.object(self.rollback.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(RuntimeError, "foreign mount"):
                self.rollback.detach_owned(self.target, self.source)
            popen.assert_not_called()


class HomeReloadTests(unittest.TestCase):
    def test_native_schema_required_unknown_and_types_are_enforced(self):
        schemas = {
            "closeByAppId": {"required": ["id"], "properties": {"id": {"type": "string"}}},
            "launch": {"required": ["id"], "properties": {"id": {"type": "string"}, "launchHidden": {"type": "boolean"}, "preload": {"type": "string", "enum": ["full"]}}},
        }
        loader = lambda name: schemas[name]
        reload_home.validate_payload("com.webos.applicationManager/closeByAppId", {"id": "com.webos.app.home"}, schema_loader=loader)
        with self.assertRaisesRegex(ValueError, "requires"):
            reload_home.validate_payload("com.webos.applicationManager/closeByAppId", {}, schema_loader=loader)
        with self.assertRaisesRegex(ValueError, "does not allow"):
            reload_home.validate_payload("com.webos.applicationManager/closeByAppId", {"id": "x", "extra": True}, schema_loader=loader)
        with self.assertRaisesRegex(ValueError, "expects"):
            reload_home.validate_payload("com.webos.applicationManager/launch", {"id": "x", "launchHidden": "yes"}, schema_loader=loader)
        with self.assertRaisesRegex(ValueError, "enum"):
            reload_home.validate_payload("com.webos.applicationManager/launch", {"id": "x", "preload": "none"}, schema_loader=loader)

    def test_processid_schema_snapshot_and_nested_snapshot_marker(self):
        self.assertEqual(reload_home.home_pids([{"id": reload_home.APP, "processid": "2035"}]), {2035})
        with self.assertRaisesRegex(ValueError, "processid"):
            reload_home.home_pids([{"id": reload_home.APP, "pid": 2035}])
        self.assertTrue(reload_home.is_snapshot({"parameters": {"snapshot": True}}))
        self.assertTrue(reload_home.is_snapshot({"snapshot": True}))
        self.assertFalse(reload_home.is_snapshot({"parameters": {"snapshot": False}}))

    def test_reload_closes_launches_and_preserves_other_app_pid_and_starttime(self):
        before = [
            {"id": reload_home.APP, "processid": 100},
            {"id": "com.webos.app.youtube", "processid": 200},
        ]
        after = [
            {"id": reload_home.APP, "processid": 101},
            {"id": "com.webos.app.youtube", "processid": 200},
        ]
        ticks = {100: "old-home", 101: "new-home", 200: "youtube"}
        requests = []
        current = {"time": 0.0}
        def api(method, payload):
            requests.append((method, payload))
            if method.endswith("/running"):
                return {"running": before if sum(1 for m, p in requests if m.endswith("/running")) == 1 else after}
            return {"returnValue": True}
        def term(pid, sig):
            self.assertEqual((pid, sig), (100, reload_home.signal.SIGTERM))
            ticks[100] = None
        def clock():
            return current["time"]
        def sleep(seconds):
            current["time"] += seconds
        result = reload_home.reload_home(
            "--hidden", api=api, sleep=sleep, clock=clock,
            starttime=lambda pid: ticks.get(pid),
            read_params=lambda pid: {"parameters": {"snapshot": False}},
            readlink=lambda path: "/usr/bin/com.webos.app.home", terminate=term,
            validator=lambda method, payload: None,
        )
        self.assertEqual(result["new_home_pids"], [101])
        self.assertTrue(result["other_app_pids_and_starttimes_unchanged"])
        self.assertEqual(result["new_home_snapshot_flags"], {"101": False})
        self.assertNotIn("new_home_params", result)
        self.assertIn(("com.webos.applicationManager/closeByAppId", {"id": reload_home.APP}), requests)
        launch = [payload for method, payload in requests if method.endswith("/launch")][0]
        self.assertEqual(launch["id"], reload_home.APP)
        self.assertTrue(launch["launchHidden"])
        self.assertEqual(launch["preload"], "full")

    def test_nested_snapshot_is_rejected_unless_explicit_rollback_exception(self):
        apps = [{"id": "com.webos.app.youtube", "processid": 200}]
        after = apps + [{"id": reload_home.APP, "processid": 101}]
        ticks = {200: "yt", 101: "home"}
        running_calls = {"count": 0}
        def api(method, payload):
            if method.endswith("/running"):
                running_calls["count"] += 1
                return {"running": apps if running_calls["count"] == 1 else after}
            return {"returnValue": True}
        kwargs = dict(api=api, sleep=lambda _: None, clock=lambda: 0,
                      starttime=lambda pid: ticks.get(pid),
                      read_params=lambda pid: {"parameters": {"snapshot": True}},
                      validator=lambda method, payload: None)
        with self.assertRaisesRegex(RuntimeError, "CRIU snapshot"):
            reload_home.reload_home("--hidden", **kwargs)
        running_calls["count"] = 0
        accepted = reload_home.reload_home("--hidden", allow_original_snapshot=True, **kwargs)
        self.assertEqual(accepted["new_home_pids"], [101])

    def test_launch_schema_is_checked_before_closing_home(self):
        requests = []
        def api(method, payload):
            requests.append((method, payload))
            return {"running": []}
        def reject_launch(method, payload):
            if method.endswith("/launch"):
                raise ValueError("launch schema rejected")
        with self.assertRaisesRegex(ValueError, "launch schema rejected"):
            reload_home.reload_home("--hidden", api=api, validator=reject_launch)
        self.assertEqual(requests, [])

    def test_no_argument_or_unacknowledged_reload_does_not_call_luna(self):
        with patch.object(reload_home, "require_root", side_effect=AssertionError("should not check device")), \
             patch.object(reload_home, "luna", side_effect=AssertionError("must not call Luna")):
            self.assertEqual(reload_home.main([]), 2)
            self.assertEqual(reload_home.main(["--visible"]), 2)
            self.assertEqual(reload_home.main(["--hidden", "--visible", "--ack-home-reload"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
