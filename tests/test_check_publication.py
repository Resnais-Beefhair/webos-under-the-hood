"""Regression tests for the offline publication backstop; all leak data is synthetic."""
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('check_publication', ROOT / 'tools/check_publication.py')
if _spec is None or _spec.loader is None:
    raise RuntimeError('could not load publication checker')
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)

PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
PROJECT_NAME = 'webOS Under the Hood contributors'
PROJECT_EMAIL = '294102483+Resnais-Beefhair@users.noreply.github.com'


def png_chunk(kind, payload):
    return (struct.pack('>I', len(payload)) + kind + payload
            + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff))


def png_with_text(kind, payload):
    ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
    return (PNG_SIGNATURE + png_chunk(b'IHDR', ihdr) + png_chunk(b'IDAT', b'')
            + png_chunk(kind, payload) + png_chunk(b'IEND', b''))


def run_git(root, *args, env=None):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          capture_output=True, text=True, env=merged)


def init_repo(root):
    run_git(root, 'init', '-q')
    (root / 'README.md').write_text('# Synthetic publication fixture\n')
    run_git(root, 'add', 'README.md')


def make_commit(root, message='Synthetic safe fixture'):
    run_git(root, '-c', 'commit.gpgsign=false', 'commit', '--no-gpg-sign', '-m', message,
            env={
                'GIT_AUTHOR_NAME': PROJECT_NAME,
                'GIT_AUTHOR_EMAIL': PROJECT_EMAIL,
                'GIT_COMMITTER_NAME': PROJECT_NAME,
                'GIT_COMMITTER_EMAIL': PROJECT_EMAIL,
            })


def cli(root):
    return subprocess.run([sys.executable, str(ROOT / 'tools/check_publication.py'), '--root', str(root)],
                          capture_output=True, text=True)


class PublicationHardeningTests(unittest.TestCase):
    def test_identifier_context_is_detected_but_schema_names_and_git_shas_are_not(self):
        key = 'device' + '-' + 'id'
        leak = key + ': SYNTHETIC-UNIT-483920'
        self.assertTrue(checker.scan_text(leak, 'synthetic'))
        self.assertEqual(checker.scan_text(key, 'synthetic'), [])
        self.assertEqual(checker.scan_text('{"' + key + '": "string"}', 'synthetic'), [])
        schema_value = 'serial' + '_' + 'number'
        self.assertEqual(checker.scan_text(key + ': ' + schema_value.upper(), 'synthetic'), [])
        self.assertEqual(checker.scan_text(('ab' * 20), 'synthetic'), [])
        self.assertEqual(checker.scan_text('commit SHA: ' + ('ab' * 20), 'synthetic'), [])

    def test_serial_and_long_nduid_contexts_are_detected(self):
        serial_key = 'serial' + ' number'
        long_id_key = 'nd' + 'uid'
        long_id = 'c2' * 20
        self.assertTrue(checker.scan_text(serial_key + ': SYNTHETIC-SERIAL-483920', 'synthetic'))
        self.assertTrue(checker.scan_text(long_id_key + '=' + long_id, 'synthetic'))

    def test_public_ipv4_is_detected_except_exact_approved_dns_resolvers(self):
        exposed = '.'.join(('8', '8', '4', '4'))
        allowed_one = '.'.join(('1', '1', '1', '1'))
        allowed_two = '.'.join(('9', '9', '9', '9'))
        self.assertTrue(checker.scan_text(exposed, 'synthetic'))
        self.assertEqual(checker.scan_text(allowed_one + ' ' + allowed_two, 'synthetic'), [])
        self.assertEqual(checker.scan_text('192.0.2.7 198.51.100.9 203.0.113.11 255.255.255.255', 'synthetic'), [])

    def test_unix_and_windows_user_home_paths_are_detected_root_service_path_is_allowed(self):
        unix_path = '/' + 'home' + '/' + 'synthetic-user' + '/.config/app'
        slash = chr(92)
        windows_path = 'C:' + slash + 'Users' + slash + 'synthetic-user' + slash + 'Desktop'
        system_path = '/' + 'home' + '/' + 'root' + '/.ssh/authorized_keys'
        self.assertTrue(checker.scan_text(unix_path, 'synthetic'))
        self.assertTrue(checker.scan_text(windows_path, 'synthetic'))
        self.assertEqual(checker.scan_text(system_path, 'synthetic'), [])

    def test_png_uncompressed_text_chunks_are_scanned(self):
        text_type = b'tEXt'
        payload = b'Comment\x00' + ('serial' + ': SYNTHETIC-PNG-728391').encode()
        issues = checker.scan_png(png_with_text(text_type, payload), 'synthetic.png')
        self.assertTrue(issues)
        self.assertIn('PNG text', issues[0])

    def test_png_ztext_and_compressed_itxt_are_decompressed_and_scanned(self):
        key = 'device' + '-' + 'id'
        content = (key + ': SYNTHETIC-COMPRESSED-728391').encode()
        ztxt = b'Comment\x00\x00' + zlib.compress(content)
        itxt = b'Comment\x00\x01\x00en\x00Comment\x00' + zlib.compress(content)
        self.assertTrue(checker.scan_png(png_with_text(b'zTXt', ztxt), 'ztext.png'))
        self.assertTrue(checker.scan_png(png_with_text(b'iTXt', itxt), 'itext.png'))

    def test_malformed_png_and_bad_compressed_text_fail_closed(self):
        malformed = PNG_SIGNATURE + b'\x00\x00\x00\x10tEXtshort'
        self.assertTrue(checker.scan_png(malformed, 'truncated.png'))
        bad_ztxt = b'Comment\x00\x00not-a-zlib-stream'
        issues = checker.scan_png(png_with_text(b'zTXt', bad_ztxt), 'bad-compression.png')
        self.assertTrue(issues)
        self.assertTrue(any('malformed PNG' in item for item in issues))

    def test_png_expansion_limit_fails_closed(self):
        expanded = b'x' * (checker.MAX_PNG_TEXT_BYTES + 1)
        payload = b'Comment\x00\x00' + zlib.compress(expanded)
        issues = checker.scan_png(png_with_text(b'zTXt', payload), 'oversized-text.png')
        self.assertTrue(any('malformed PNG' in item for item in issues))

    @unittest.skipUnless(shutil.which('git'), 'Git integration tests need git')
    def test_clean_role_noreply_metadata_is_accepted_by_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            init_repo(root)
            make_commit(root)
            result = cli(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)['issues'], [])

    @unittest.skipUnless(shutil.which('git'), 'Git integration tests need git')
    def test_leaked_text_png_and_commit_metadata_make_cli_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            init_repo(root)
            key = 'device' + '-' + 'id'
            (root / 'leak.txt').write_text(key + ': SYNTHETIC-UNIT-483920\n')
            image_text = ('serial' + ': SYNTHETIC-PNG-728391').encode()
            (root / 'leak.png').write_bytes(
                png_with_text(b'tEXt', b'Comment\x00' + image_text))
            long_id = 'nd' + 'uid' + '=' + ('c2' * 20)
            run_git(root, 'add', 'leak.txt', 'leak.png')
            make_commit(root, 'Synthetic metadata leak: ' + long_id)

            result = cli(root)
            self.assertEqual(result.returncode, 1, result.stderr)
            issues = json.loads(result.stdout)['issues']
            self.assertTrue(any(x.startswith('index:leak.txt:') for x in issues), issues)
            self.assertTrue(any(x.startswith('index:leak.png:') for x in issues), issues)
            self.assertTrue(any(x.startswith('history:leak.png:') for x in issues), issues)
            self.assertTrue(any(x.startswith('commit:') for x in issues), issues)
            self.assertFalse(any('metadata email' in x for x in issues), issues)

    @unittest.skipUnless(shutil.which('git'), 'Git metadata tests need git')
    def test_commit_author_and_committer_emails_are_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            init_repo(root)
            make_commit(root)
            run_git(root, 'commit', '--allow-empty', '--no-gpg-sign', '-m', 'Synthetic author metadata',
                    env={
                        'GIT_AUTHOR_NAME': 'Synthetic Test Author',
                        'GIT_AUTHOR_EMAIL': 'author@example.invalid',
                        'GIT_COMMITTER_NAME': PROJECT_NAME,
                        'GIT_COMMITTER_EMAIL': PROJECT_EMAIL,
                    })
            run_git(root, 'commit', '--allow-empty', '--no-gpg-sign', '-m', 'Synthetic committer metadata',
                    env={
                        'GIT_AUTHOR_NAME': PROJECT_NAME,
                        'GIT_AUTHOR_EMAIL': PROJECT_EMAIL,
                        'GIT_COMMITTER_NAME': 'Synthetic Test Committer',
                        'GIT_COMMITTER_EMAIL': 'committer@example.invalid',
                    })
            issues = checker.scan_commit_metadata(root)
            self.assertTrue(any('author email: unapproved metadata email' in item for item in issues), issues)
            self.assertTrue(any('committer email: unapproved metadata email' in item for item in issues), issues)

    @unittest.skipUnless(shutil.which('git'), 'Git index tests need git')
    def test_staged_png_is_scanned_even_when_worktree_and_history_are_clean(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            init_repo(root)
            clean = png_with_text(b'tEXt', b'Comment\x00synthetic clean image')
            image = root / 'staged.png'
            image.write_bytes(clean)
            run_git(root, 'add', 'staged.png')
            make_commit(root)

            value = ('serial' + ': SYNTHETIC-STAGED-PNG-728391').encode()
            image.write_bytes(png_with_text(b'tEXt', b'Comment\x00' + value))
            run_git(root, 'add', 'staged.png')
            image.write_bytes(clean)
            result = cli(root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            issues = json.loads(result.stdout)['issues']
            self.assertTrue(any(x.startswith('index:staged.png: PNG text') for x in issues), issues)
            self.assertFalse(any(x.startswith('staged.png: PNG text') for x in issues), issues)
            self.assertFalse(any(x.startswith('history:staged.png: PNG text') for x in issues), issues)

    @unittest.skipUnless(shutil.which('git'), 'Git worktree test needs git')
    def test_linked_worktree_git_file_is_supported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source'
            source.mkdir()
            init_repo(source)
            make_commit(source)
            linked = root / 'linked'
            run_git(source, 'worktree', 'add', '--quiet', '--detach', str(linked), 'HEAD')
            self.assertTrue((linked / '.git').is_file())
            result = cli(linked)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
