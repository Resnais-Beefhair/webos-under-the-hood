"""Offline lifecycle-lock and crash-recovery regression tests."""
import contextlib
import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

TESTS = str(Path(__file__).resolve().parent)
if TESTS not in sys.path:
    sys.path.insert(0, TESTS)
from test_optional_screensaver import build_bundle, load_artifact


@unittest.skipUnless(os.name == "posix", "Linux lifecycle flock, inode and permission semantics")
class ScreensaverLifecycleHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        artifacts, _ = build_bundle()
        cls.runtime_source = artifacts["overlay_runtime.py"]

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "runtime"
        self.base.mkdir(mode=0o700)
        os.chmod(str(self.base), 0o700)
        self.runtime = load_artifact(
            {"overlay_runtime.py": self.runtime_source},
            "overlay_runtime.py", "screensaver_lifecycle_hardening")
        self.runtime.BASE = str(self.base)
        self.runtime.TARGETS = {
            "ScreenSaver.qml": str(self.root / "target-screen.qml"),
            "MainView.qml": str(self.root / "target-main.qml"),
        }
        self.boot = "offline-test-boot"
        self.original = {}
        self.patched = {}
        self.backups = {}
        for name, target in self.runtime.TARGETS.items():
            original = (name + "-original").encode("ascii")
            patched = (name + "-patched").encode("ascii")
            self.original[name] = original
            self.patched[name] = patched
            self.runtime.ORIGINAL[name] = hashlib.sha256(original).hexdigest()
            self.runtime.PATCHED[name] = hashlib.sha256(patched).hexdigest()
            Path(target).write_bytes(original)
            backup = self.root / (name + ".unmounted")
            os.link(target, str(backup))
            self.backups[name] = str(backup)
            Path(self.base, name + ".patched.qml").write_bytes(patched)
        self.rows = {}
        self.calls = []
        self.next_mount_id = 200

    def mount_rows(self, target=None):
        if target is not None:
            return list(self.rows.get(target, []))
        return [row for group in self.rows.values() for row in group]

    def _bind(self, name, mount_id=None):
        target = self.runtime.TARGETS[name]
        source = os.path.join(self.runtime.BASE, name + ".patched.qml")
        if mount_id is None:
            self.next_mount_id += 1
            mount_id = str(self.next_mount_id)
        row = {"id": str(mount_id), "mountpoint": target,
               "options": ["rw", "relatime"], "super_options": ["rw"]}
        self.rows.setdefault(target, []).append(row)
        if not os.path.exists(target):
            raise AssertionError("bind target unexpectedly missing")
        os.unlink(target)
        os.link(source, target)
        return row

    def _unmount(self, target):
        self.rows.pop(target, None)
        name = next(name for name, path in self.runtime.TARGETS.items() if path == target)
        if os.path.lexists(target):
            os.unlink(target)
        os.link(self.backups[name], target)

    def command(self, args):
        self.calls.append(list(args))
        if args[:2] == ["mount", "--bind"]:
            name = next(name for name, target in self.runtime.TARGETS.items()
                        if target == args[3])
            self._bind(name)
        elif args[:2] == ["mount", "-o"]:
            target = args[-1]
            rows = self.rows[target]
            rows[-1]["options"] = ["ro", "relatime"]
        elif args[0] == "umount":
            self._unmount(args[1])
        else:
            raise AssertionError("unexpected simulated command: %r" % (args,))

    @contextlib.contextmanager
    def patched_runtime(self, command=None, **extra):
        replacements = {
            "_load_manifest": Mock(return_value={}),
            "_ensure_checkpoints": Mock(),
            "boot_id": Mock(return_value=self.boot),
            "mount_rows": self.mount_rows,
        }
        replacements.update(extra)
        with patch.multiple(self.runtime, **replacements), \
                patch.object(self.runtime.subprocess, "check_call",
                             side_effect=command or self.command):
            yield replacements

    def _intent_journal(self, names=None):
        names = sorted(names or self.runtime.TARGETS)
        entries = {}
        for name in names:
            source = os.path.join(self.runtime.BASE, name + ".patched.qml")
            target = self.runtime.TARGETS[name]
            entries[name] = {
                "phase": "intent",
                "source_inode": self.runtime._inode(source),
                "target_inode": self.runtime._inode(target),
            }
        journal = {"version": 1, "operation": "apply", "boot_id": self.boot,
                   "targets": entries}
        self.runtime._save_journal(journal)
        return journal

    @unittest.skipUnless(os.name == "posix", "directory flock requires POSIX")
    def test_read_only_inspect_uses_directory_flock_without_creating_state(self):
        before = sorted(os.listdir(str(self.base)))
        with self.patched_runtime():
            result = self.runtime.inspect()
        self.assertEqual(result["mounts"], {name: "original" for name in self.runtime.TARGETS})
        self.assertEqual(sorted(os.listdir(str(self.base))), before)
        self.assertFalse((self.base / "active.json").exists())
        self.assertFalse((self.base / "lifecycle.json").exists())

    def test_check_refuses_pending_journal_without_repairing_or_writing(self):
        self._intent_journal(["MainView.qml"])
        journal_path = self.base / "lifecycle.json"
        before = journal_path.read_bytes()
        with self.patched_runtime():
            with self.assertRaisesRegex(RuntimeError, "run --apply or --rollback to recover"):
                self.runtime.inspect()
        self.assertEqual(journal_path.read_bytes(), before)
        self.assertFalse((self.base / "active.json").exists())
        self.assertEqual(sorted(os.listdir(str(self.base))),
                         sorted(["MainView.qml.patched.qml", "ScreenSaver.qml.patched.qml",
                                 "lifecycle.json"]))

    @unittest.skipUnless(os.name == "posix", "directory flock requires POSIX")
    def test_directory_lock_refuses_symlink_and_nonprivate_directory(self):
        alias = self.root / "runtime-link"
        alias.symlink_to(self.base, target_is_directory=True)
        with patch.object(self.runtime, "BASE", str(alias)):
            with self.assertRaisesRegex(RuntimeError, "invalid runtime directory"):
                with self.runtime._lifecycle_lock():
                    self.fail("symlinked base acquired lifecycle lock")
        os.chmod(str(self.base), 0o755)
        try:
            with self.assertRaisesRegex(RuntimeError, "private mode 0700"):
                with self.runtime._lifecycle_lock():
                    self.fail("non-private base acquired lifecycle lock")
        finally:
            os.chmod(str(self.base), 0o700)
        self.assertEqual(os.listdir(str(self.base)),
                         [name for name in os.listdir(str(self.base)) if name.endswith(".patched.qml")])

    @unittest.skipUnless(os.name == "posix", "real fcntl lock requires POSIX")
    def test_real_cross_process_flock_is_reported_as_busy(self):
        script = (
            "import fcntl,os,sys,time; "
            "fd=os.open(sys.argv[1], os.O_RDONLY|getattr(os,'O_DIRECTORY',0)); "
            "fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB); "
            "print('held', flush=True); time.sleep(1.0)"
        )
        child = subprocess.Popen([sys.executable, "-c", script, str(self.base)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "held")
            with patch.object(self.runtime.subprocess, "check_call") as call:
                for operation in (self.runtime.apply_mounts, self.runtime.rollback_mounts):
                    with self.assertRaisesRegex(RuntimeError, "lifecycle operation busy"):
                        operation()
                call.assert_not_called()
        finally:
            child.wait(timeout=5)
            child.stdout.close()
            child.stderr.close()
        self.assertEqual(child.returncode, 0)

    @unittest.skipUnless(os.name == "posix", "real fcntl lock requires POSIX")
    def test_overlapping_apply_calls_serialize_preflight_mount_and_journal(self):
        first_checkpoint = threading.Event()
        release_first = threading.Event()
        second_started = threading.Event()
        second_checkpoint = threading.Event()
        checkpoint_count = []
        results = []
        errors = []

        def gated_checkpoints(names):
            checkpoint_count.append(list(names))
            if len(checkpoint_count) == 1:
                first_checkpoint.set()
                if not release_first.wait(5):
                    raise RuntimeError("test gate timed out")
            else:
                second_checkpoint.set()

        def run(second=False):
            if second:
                second_started.set()
            try:
                results.append(self.runtime.apply_mounts())
            except BaseException as exc:
                errors.append(exc)

        with self.patched_runtime(_ensure_checkpoints=gated_checkpoints):
            one = threading.Thread(target=run)
            one.start()
            self.assertTrue(first_checkpoint.wait(3), "first apply did not reach checkpoint gate")
            two = threading.Thread(target=run, kwargs={"second": True})
            two.start()
            self.assertTrue(second_started.wait(3), "second apply did not start")
            self.assertFalse(second_checkpoint.wait(0.2),
                             "second apply passed preflight while first held lifecycle lock")
            release_first.set()
            one.join(5)
            two.join(5)
        self.assertFalse(one.is_alive() or two.is_alive(), "apply thread did not finish")
        self.assertEqual(len(errors), 1)
        self.assertRegex(str(errors[0]), "lifecycle operation busy")
        self.assertEqual([result["changed"] for result in results], [2])
        self.assertEqual(len(checkpoint_count), 1)
        self.assertEqual(sum(call[:2] == ["mount", "--bind"] for call in self.calls), 2)
        self.assertTrue(all(len(self.rows.get(target, [])) == 1
                            for target in self.runtime.TARGETS.values()))
        self.assertFalse((self.base / "lifecycle.json").exists())
        with self.patched_runtime():
            retry = self.runtime.apply_mounts()
        self.assertEqual(retry["changed"], 0)

    def test_foreign_mount_refuses_before_writing_journal_or_unmounting(self):
        self._bind("ScreenSaver.qml", mount_id="foreign-77")
        self.rows[self.runtime.TARGETS["ScreenSaver.qml"]][0]["options"] = ["ro"]
        with self.patched_runtime():
            with self.assertRaisesRegex(RuntimeError, "unowned mount"):
                self.runtime.apply_mounts()
        self.assertEqual(self.calls, [])
        self.assertFalse((self.base / "lifecycle.json").exists())
        self.assertEqual(len(self.rows[self.runtime.TARGETS["ScreenSaver.qml"]]), 1)

    def test_intent_journal_recovers_crash_after_bind_before_mount_id_write(self):
        journal = self._intent_journal()
        self._bind("MainView.qml", mount_id="crash-window-88")
        with self.patched_runtime():
            result = self.runtime.apply_mounts()
        self.assertEqual(result["changed"], 2)
        self.assertEqual(self.calls[0], ["umount", self.runtime.TARGETS["MainView.qml"]])
        self.assertEqual(sum(call[:2] == ["mount", "--bind"] for call in self.calls), 2)
        self.assertEqual(set(journal["targets"]), set(self.runtime.TARGETS))
        self.assertFalse((self.base / "lifecycle.json").exists())
        self.assertEqual(set(self.runtime._load_state()["mounts"]), set(self.runtime.TARGETS))
        self.assertTrue(all(len(self.rows[target]) == 1 for target in self.runtime.TARGETS.values()))

    def test_retry_preserves_verified_ownership_after_commit_before_journal_clear(self):
        entries = {}
        records = {}
        for name in sorted(self.runtime.TARGETS):
            target = self.runtime.TARGETS[name]
            original_target_inode = self.runtime._inode(target)
            source_inode = self.runtime._inode(os.path.join(self.runtime.BASE, name + ".patched.qml"))
            row = self._bind(name, mount_id="committed-" + name)
            row["options"] = ["ro", "relatime"]
            entries[name] = {
                "phase": "readonly", "mount_id": row["id"],
                "source_inode": source_inode,
                "target_inode": original_target_inode,
            }
            records[name] = self.runtime._state_record(name, row["id"])
        self.runtime._save_state({"version": 1, "boot_id": self.boot, "mounts": records})
        self.runtime._save_journal({"version": 1, "operation": "apply",
                                    "boot_id": self.boot, "targets": entries})
        with self.patched_runtime():
            result = self.runtime.apply_mounts()
        self.assertEqual(result["changed"], 0)
        self.assertFalse(any(call[0] == "umount" for call in self.calls))
        self.assertEqual(len(self.rows), 2)
        self.assertFalse((self.base / "lifecycle.json").exists())

    def test_keyboard_interrupt_after_bind_rolls_back_only_journaled_mounts(self):
        def interrupt_after_remount(args):
            self.command(args)
            if args[:2] == ["mount", "-o"]:
                raise KeyboardInterrupt()

        with self.patched_runtime(command=interrupt_after_remount):
            with self.assertRaises(KeyboardInterrupt):
                self.runtime.apply_mounts()
        self.assertEqual(len(self.rows), 0)
        self.assertFalse((self.base / "active.json").exists())
        self.assertFalse((self.base / "lifecycle.json").exists())
        self.assertEqual(sum(call[0] == "umount" for call in self.calls), 1)
        self.assertTrue(all(Path(target).read_bytes() == self.original[name]
                            for name, target in self.runtime.TARGETS.items()))

    @unittest.skipUnless(hasattr(signal, "SIGTERM") and os.name == "posix",
                         "SIGTERM handling requires POSIX")
    def test_sigterm_after_bind_runs_checked_cleanup_and_restores_handler(self):
        previous = signal.getsignal(signal.SIGTERM)

        def terminate_after_bind(args):
            self.command(args)
            if args[:2] == ["mount", "--bind"]:
                os.kill(os.getpid(), signal.SIGTERM)

        with self.patched_runtime(command=terminate_after_bind):
            with self.assertRaisesRegex(self.runtime._LifecycleInterrupted, "SIGTERM"):
                self.runtime.apply_mounts()
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)
        self.assertEqual(len(self.rows), 0)
        self.assertFalse((self.base / "lifecycle.json").exists())
        self.assertEqual(sum(call[0] == "umount" for call in self.calls), 1)

    def test_old_boot_intent_retires_only_when_exact_original_is_present(self):
        self._intent_journal(["MainView.qml"])
        with self.patched_runtime(boot_id=Mock(return_value="new-boot")):
            result = self.runtime.apply_mounts()
        self.assertEqual(result["changed"], 2)
        self.assertFalse(any(call[0] == "umount" for call in self.calls))
        self.assertFalse((self.base / "lifecycle.json").exists())
        self.assertTrue(all(len(self.rows[target]) == 1
                            for target in self.runtime.TARGETS.values()))

    def test_mismatched_journal_mount_identity_fails_closed_without_unmount(self):
        journal = self._intent_journal(["MainView.qml"])
        entry = journal["targets"]["MainView.qml"]
        entry["phase"] = "bound"
        entry["mount_id"] = "expected-id"
        self.runtime._save_journal(journal)
        self._bind("MainView.qml", mount_id="different-id")
        with self.patched_runtime():
            with self.assertRaisesRegex(RuntimeError, "mount instance changed"):
                self.runtime.apply_mounts()
        self.assertFalse(any(call[0] == "umount" for call in self.calls))
        self.assertTrue((self.base / "lifecycle.json").exists())
        self.assertEqual(len(self.rows[self.runtime.TARGETS["MainView.qml"]]), 1)

    def test_stacked_journal_mount_is_not_cleaned(self):
        journal = self._intent_journal(["MainView.qml"])
        target = self.runtime.TARGETS["MainView.qml"]
        self._bind("MainView.qml", mount_id="one")
        self.rows[target].append({"id": "two", "mountpoint": target,
                                  "options": ["ro"], "super_options": ["rw"]})
        with self.patched_runtime():
            with self.assertRaisesRegex(RuntimeError, "stacked or mismatched mount"):
                self.runtime._recover_pending_apply()
        self.assertTrue((self.base / "lifecycle.json").exists())
        self.assertEqual(len(self.rows[target]), 2)
        self.assertFalse(any(call[0] == "umount" for call in self.calls))


if __name__ == "__main__":
    unittest.main(verbosity=2)
