"""Check pasted shell recipes without executing a command or contacting a TV."""
import re
import shlex
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("sh"), "POSIX shell syntax checks need sh")
class DocumentationTests(unittest.TestCase):
    def test_shell_blocks_and_embedded_ssh_commands_parse(self):
        paths = [ROOT / "README.md", *ROOT.glob("docs/*.md"), ROOT / "optional-preview/README.md"]
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for index, block in enumerate(re.findall(r"```sh\n(.*?)```", text, re.S)):
                with self.subTest(path=path.name, block=index):
                    result = subprocess.run(["sh", "-n"], input=block, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                # The local shell can parse while the quoted remote shell cannot.
                # Expand continued lines only; don't execute any recipe or heredoc.
                for line in block.replace("\\\n", " ").splitlines():
                    if not line.lstrip().startswith("ssh "):
                        continue
                    words = shlex.split(line)
                    cursor = 1
                    while cursor < len(words) and words[cursor].startswith("-"):
                        option = words[cursor]
                        cursor += 2 if option in ("-o", "-p", "-i", "-F") else 1
                    cursor += 1  # SSH target, followed by the quoted remote command.
                    if cursor >= len(words):
                        continue
                    remote = words[cursor]
                    with self.subTest(path=path.name, remote_command=remote[:30]):
                        result = subprocess.run(["sh", "-n", "-c", remote], capture_output=True, text=True)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        for payload in re.findall(r"python -c ([^;]+)", remote):
                            args = shlex.split("python -c " + payload)
                            self.assertEqual(len(args), 3, "Python payload lost quoting")
                            compile(args[2], "<documented remote Python>", "exec")

    def test_interactive_public_key_paste_is_not_a_command_block(self):
        text = (ROOT / "docs/connection.md").read_text()
        self.assertIn('cat >> /home/root/.ssh/authorized_keys\n```', text)
        self.assertNotRegex(text, r"cat >>[^`]+chmod 600")


class ServiceRecoveryRecipeTests(unittest.TestCase):
    def run_recipe(self, *, foreign_mount=False, foreign_hook=False, no_ownership=False):
        # Exercise the actual documented Python, not a separately retyped helper.
        import io
        import stat
        import types
        from contextlib import redirect_stdout
        from unittest.mock import Mock, patch
        text = (ROOT / "docs/services.md").read_text()
        scripts = re.findall(r"<<'PY'\n(.*?)\nPY", text, re.S)
        source = next(code for code in scripts if 'Owned startup hook disabled' in code)
        base = "/var/lib/webosbrew/privacy-services"
        payload = base + "/50-privacy-services"
        hook = "/var/lib/webosbrew/init.d/50-privacy-services"
        disabled = base + "/50-privacy-services.disabled"
        target = "/etc/systemd/system/voiceinput.service"
        metadata = {payload: (1, 20), "/dev/null": (2, 9),
                    target: (2, 100 if foreign_mount else 9)}
        if not no_ownership:
            metadata[hook] = (1, 200 if foreign_hook else 20)
        def file_stat(path):
            device, inode = metadata[path]
            return types.SimpleNamespace(st_dev=device, st_ino=inode, st_mode=stat.S_IFREG)
        def create_link(old, new):
            if new in metadata:
                raise FileExistsError(new)
            metadata[new] = metadata[old]
        link = Mock(side_effect=create_link)
        unlink = Mock(side_effect=lambda path: metadata.pop(path))
        fake_os = types.SimpleNamespace(getuid=lambda: 0, stat=file_stat, lstat=file_stat,
            path=types.SimpleNamespace(lexists=lambda path: path in metadata), link=link, unlink=unlink)
        call = Mock()
        fake_subprocess = types.SimpleNamespace(check_call=call)
        def open_fixture(path, *args):
            return io.StringIO({"/etc/version": "20260421173614\n",
                "/proc/mounts": "devtmpfs " + target + " devtmpfs rw 0 0\n"}[path])
        error = None
        with patch.dict("sys.modules", {"os": fake_os, "subprocess": fake_subprocess}), \
             patch("builtins.open", side_effect=open_fixture), redirect_stdout(io.StringIO()):
            try:
                exec(compile(source, "<documented service recovery>", "exec"), {})
            except RuntimeError as exc:
                error = exc
        return error, link, unlink, call, metadata

    def test_owned_hook_and_unit_bind_recovery_never_starts_services(self):
        error, link, unlink, call, metadata = self.run_recipe()
        self.assertIsNone(error)
        link.assert_called_once()
        unlink.assert_called_once()
        self.assertEqual([row.args[0][0] for row in call.call_args_list], ["umount", "systemctl"])
        self.assertEqual(call.call_args.args[0], ["systemctl", "daemon-reload"])

    def test_foreign_mount_hook_or_missing_ownership_means_no_changes(self):
        for kwargs in ({"foreign_mount": True}, {"foreign_hook": True}, {"no_ownership": True}):
            with self.subTest(kwargs=kwargs):
                error, link, unlink, call, metadata = self.run_recipe(**kwargs)
                self.assertIsNotNone(error)
                link.assert_not_called()
                unlink.assert_not_called()
                call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
