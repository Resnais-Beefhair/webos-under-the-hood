"""Pure synthetic scanner inputs; no real credentials or device addresses."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_spec=importlib.util.spec_from_file_location('check_publication',Path(__file__).resolve().parents[1]/'tools/check_publication.py')
m=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(m)

class PublicationTests(unittest.TestCase):
    def test_documentation_addresses_allowed(self):
        self.assertEqual(m.scan_text('192.0.2.10 198.51.100.20 203.0.113.4 127.0.0.1 ::1','synthetic'),[])
    def test_limited_broadcast_is_a_protocol_constant_not_a_host(self):
        self.assertEqual(m.scan_text('255.255.255.255','synthetic'),[])
    def test_private_network_detected(self):
        ip='.'.join(['10','1','2','3'])
        self.assertTrue(m.scan_text(ip,'synthetic'))
    def test_private_key_header_detected(self):
        header='-----BEGIN '+'OPENSSH PRIVATE KEY-----'
        self.assertTrue(m.scan_text(header,'synthetic'))
    def test_plain_prose_not_a_credential(self):
        self.assertEqual(m.scan_text('Never share a password. A key is private.','synthetic'),[])
    def test_unknown_connman_identity_detected(self):
        value='ethernet_'+('12'*6)+'_cable'
        self.assertTrue(m.scan_text(value,'synthetic'))
    def test_documented_synthetic_service_allowed(self):
        self.assertEqual(m.scan_text('ethernet_aabbccddeeff_cable','synthetic'),[])

    @unittest.skipUnless(shutil.which('git'), 'Git index tests need git')
    def test_actual_staged_blob_is_scanned_even_if_worktree_is_clean(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            subprocess.run(['git','-C',temp,'init','-q'],check=True)
            (root/'README.md').write_text('# Synthetic publication fixture\n')
            fixture=root/'fixture.txt'
            fixture.write_text('.'.join(['10','1','2','3']))
            subprocess.run(['git','-C',temp,'add','README.md','fixture.txt'],check=True)
            fixture.write_text('Clean worktree is not a clean index.\n')
            result=subprocess.run([sys.executable,m.__file__,'--root',temp],capture_output=True,text=True)
            self.assertEqual(result.returncode,1,result.stderr)
            self.assertTrue(any(x.startswith('index:fixture.txt:') for x in json.loads(result.stdout)['issues']))

    @unittest.skipUnless(os.name == 'posix' and shutil.which('git'), 'Symlink-index test needs POSIX/WSL and git')
    def test_directory_symlink_in_release_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            subprocess.run(['git','-C',temp,'init','-q'],check=True)
            (root/'README.md').write_text('# Synthetic publication fixture\n')
            (root/'alias').symlink_to(root,target_is_directory=True)
            subprocess.run(['git','-C',temp,'add','README.md','alias'],check=True)
            result=subprocess.run([sys.executable,m.__file__,'--root',temp],capture_output=True,text=True)
            self.assertEqual(result.returncode,1,result.stderr)
            self.assertTrue(any('symlink' in x for x in json.loads(result.stdout)['issues']))

if __name__=='__main__':unittest.main()
