"""Exercise documented bootstrap recipes offline, never a TV or exploit."""
import base64
import contextlib
import io
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
PIN = "21023d56ca424607bb03d2939609cc658c655fc7"


def python_recipes():
    text = (ROOT / "docs/connection.md").read_text(encoding="utf-8")
    return re.findall(r"<<'PY'\n(.*?)\nPY", text, re.S)


class BootstrapRecipesTests(unittest.TestCase):
    def test_public_entry_recipe_fits_short_console_and_preserves_exact_entry(self):
        code = next(c for c in python_recipes() if 'commands = ' in c)
        wire = b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20' + bytes(range(32))
        public = 'ssh-ed25519 ' + base64.b64encode(wire).decode('ascii')
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            (home / '.ssh').mkdir()
            public_file = home / '.ssh/lg_tv_ed25519.pub'
            public_file.write_text(public + ' ignored-comment\n', encoding='ascii')
            output = io.StringIO()
            with patch.object(Path, 'home', return_value=home), contextlib.redirect_stdout(output):
                exec(compile(code, '<documented key wrap>', 'exec'), {})
            lines = output.getvalue().splitlines()
            self.assertGreater(len(lines), 3)
            self.assertTrue(all(len(line) <= 78 for line in lines))
            self.assertEqual(lines[0], "k=''")
            self.assertEqual(lines[-1], 'unset k')
            chunks = [re.fullmatch(r'k="\$\{k\}(.*)"', line).group(1) for line in lines[1:-2]]
            self.assertEqual(''.join(chunks), 'no-port-forwarding,no-agent-forwarding,no-X11-forwarding ' + public)
            self.assertEqual(lines[-2], "printf '%s\\n' \"$k\" >> /home/root/.ssh/authorized_keys")
            self.assertEqual(list((home / '.ssh').iterdir()), [public_file])
            if os.name == 'posix' and shutil.which('sh'):
                result = subprocess.run(['sh', '-n'], input=output.getvalue(), capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                # Execute the wrapped entry under nounset, redirecting only the
                # destination into this synthetic workspace. Static chunk
                # equality alone misses shell variable-name absorption.
                import shlex
                destination = home / 'authorized_keys.synthetic'
                previous = '# existing synthetic entry\n'
                destination.write_text(previous, encoding='ascii')
                recipe = output.getvalue().replace('/home/root/.ssh/authorized_keys',
                                                   shlex.quote(str(destination)))
                result = subprocess.run([shutil.which('sh'), '-eu', '-c', recipe],
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(destination.read_text(encoding='ascii'),
                                 previous + 'no-port-forwarding,no-agent-forwarding,no-X11-forwarding ' + public + '\n')

    def test_hostkey_helper_transfer_preserves_source_and_checks_digest(self):
        code = next(c for c in python_recipes() if 'payload = Path(' in c)
        payload = b'# public helper fixture only\nprint(42)\n'
        output = io.StringIO()
        with patch.object(Path, 'read_bytes', return_value=payload), contextlib.redirect_stdout(output):
            exec(compile(code, '<documented helper transfer>', 'exec'), {})
        lines = output.getvalue().splitlines()
        self.assertTrue(all(len(line) <= 78 for line in lines))
        chunks = [re.fullmatch(r"printf '%s' '([A-Za-z0-9+/=]+)' >> \"\$f.b64\"", line).group(1)
                  for line in lines if line.startswith("printf '%s'")]
        self.assertEqual(base64.b64decode(''.join(chunks)), payload)
        self.assertIn("assert hashlib.sha256(b).hexdigest() == os.environ['h']", lines)
        self.assertIn('python "$f" --export-public "$h"', lines)
        self.assertIn('rm -f -- "$f" "$f.b64"', lines)
        self.assertIn(r'printf "%s\n" "$d"', lines)
        self.assertIn('f="$d/hostkey_public.py"', lines)
        self.assertIn('export f', lines)
        if os.name == 'posix' and shutil.which('sh'):
            result = subprocess.run(['sh', '-n'], input=output.getvalue(), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            # Exercise the exact transfer, hash check and cleanup using only the
            # synthetic print(42) payload. Redirect its task directory to the
            # managed test workspace; the TV host-key path is never read.
            with tempfile.TemporaryDirectory() as temp:
                env = dict(os.environ, QA_ROOT=temp, QA_PYTHON=sys.executable)
                setup = ('mktemp() { command mktemp -d "$QA_ROOT/key.XXXXXX"; }\n'
                         'python() { command "$QA_PYTHON" "$@"; }\n')
                result = subprocess.run([shutil.which('sh'), '-eu', '-c', setup + output.getvalue()],
                                        env=env, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                printed = result.stdout.splitlines()
                self.assertEqual(len(printed), 2)
                self.assertEqual(Path(printed[0]).parent, Path(temp))
                self.assertEqual(printed[1], '42')
                self.assertEqual(list(Path(temp).iterdir()), [])

    def test_malformed_public_key_does_not_emit_shell_commands(self):
        code = next(c for c in python_recipes() if 'commands = ' in c)
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            (home / '.ssh').mkdir()
            for value in ('ssh-rsa AAAA', 'ssh-ed25519 not!base64', 'ssh-ed25519 AAAA'):
                (home / '.ssh/lg_tv_ed25519.pub').write_text(value, encoding='ascii')
                output = io.StringIO()
                with self.subTest(value=value), patch.object(Path, 'home', return_value=home), contextlib.redirect_stdout(output):
                    with self.assertRaises((ValueError, AssertionError)):
                        exec(compile(code, '<documented key wrap>', 'exec'), {})
                    self.assertEqual(output.getvalue(), '')

    def run_port_recipe(self, effect=None):
        code = next(c for c in python_recipes() if 'socket.create_connection' in c)
        connection = Mock()
        output = io.StringIO()
        error = None
        with patch('socket.create_connection', return_value=connection, side_effect=effect) as connect, \
                patch('sys.argv', ['documented-check', '192.0.2.10']), contextlib.redirect_stdout(output):
            try:
                exec(compile(code, '<documented single-target check>', 'exec'), {})
            except SystemExit as exc:
                error = exc
        connect.assert_called_once_with(('192.0.2.10', 23), timeout=3)
        return error, output.getvalue(), connection

    def test_only_refused_port_is_reported_closed(self):
        error, output, connection = self.run_port_recipe(ConnectionRefusedError('synthetic refusal'))
        self.assertIsNone(error)
        self.assertIn('closed at this check', output)
        connection.close.assert_not_called()

    def test_timeout_is_ambiguous_not_success(self):
        error, output, connection = self.run_port_recipe(socket.timeout('synthetic timeout'))
        self.assertIsNotNone(error)
        self.assertIn('Ambiguous', str(error))
        self.assertNotIn('closed', output)
        connection.close.assert_not_called()

    def test_open_port_is_failure_and_connection_is_closed(self):
        error, output, connection = self.run_port_recipe()
        self.assertIsNotNone(error)
        self.assertIn('still open', str(error))
        self.assertNotIn('closed', output)
        connection.close.assert_called_once_with()

    def test_bootstrap_is_discoverable_and_stages_are_explicit(self):
        text = (ROOT / 'docs/rooting.md').read_text(encoding='utf-8')
        for value in (PIN, '--test-server simple', '--asset-source dir', '--webos-version 5',
                      'Root status: ok', 'telnet "$TV_IP" 23', 'connection.md', 'walkthrough.md',
                      'optional-screensaver/README.md', 'not re-rooted', 'unelevated', 'Ctrl+C'):
            self.assertIn(value, text)
        self.assertIn('docs/rooting.md', (ROOT / 'README.md').read_text(encoding='utf-8'))
        for block in re.findall(r'```sh\n(.*?)```', text, re.S):
            self.assertNotIn('--curl-insecure', block)
            self.assertNotIn('curl -k', block)
            self.assertNotIn('--test-server payload', block)

    def test_root_ssh_stays_off_until_public_key_is_provisioned(self):
        rooting = (ROOT / 'docs/rooting.md').read_text(encoding='utf-8')
        first_console = rooting.split('## 6.', 1)[1].split('## 7.', 1)[0]
        self.assertIn('keep **SSH Server off**', first_console)
        self.assertNotIn('enable **SSH Server**', first_console)
        connection = (ROOT / 'docs/connection.md').read_text(encoding='utf-8')
        provisioned = connection.index('test -s /home/root/.ssh/authorized_keys')
        enable = connection.index('### Enable SSH only after public-key provisioning')
        hostkey = connection.index('## 3. Pin the server host key')
        self.assertLess(provisioned, enable)
        self.assertLess(enable, hostkey)
        self.assertIn('leave **Telnet enabled**', connection[enable:hostkey])
        self.assertIn('reconnect `telnet "$TV_IP" 23`', connection[enable:hostkey])
        self.assertIn('disables certificate and hostname verification', rooting)
        self.assertIn('does **not** prove the response bodies were fully delivered', rooting)

    @unittest.skipUnless(os.name == 'posix' and shutil.which('sh'), 'POSIX collision recipe needs sh')
    def test_existing_root_checkout_stops_before_git_or_python(self):
        text = (ROOT / 'docs/rooting.md').read_text(encoding='utf-8')
        block = next(b for b in re.findall(r'```sh\n(.*?)```', text, re.S) if 'SLOPBRO_REV=' in b)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.local-state/rooting/slopbro').mkdir(parents=True)
            bin_dir = root / 'fake-bin'
            bin_dir.mkdir()
            for name in ('git', 'python3'):
                stub = bin_dir / name
                stub.write_text('#!/bin/sh\nprintf UNEXPECTED_EXECUTION\nexit 99\n', encoding='ascii')
                stub.chmod(0o700)
            env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ.get('PATH', ''))
            result = subprocess.run([shutil.which('sh'), '-c', block], cwd=temp, env=env,
                                    capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('UNEXPECTED_EXECUTION', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
