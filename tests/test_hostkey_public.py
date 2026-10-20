"""A synthetic byte stream proves the private seed is never read."""
import io
import struct
import importlib.util
import unittest
from pathlib import Path

_spec=importlib.util.spec_from_file_location('hostkey_public',Path(__file__).resolve().parents[1]/'tools/hostkey_public.py')
module=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(module)

class GuardedStream(io.BytesIO):
    def read(self, n=-1):
        start=self.tell()
        if n<0 or (start<51 and start+n>19):
            raise AssertionError('Private seed read attempted')
        return super().read(n)

class HostPublicKeyTests(unittest.TestCase):
    def test_only_public_bytes_read(self):
        kind=b'ssh-ed25519'
        data=struct.pack('>I',len(kind))+kind+struct.pack('>I',64)+b'S'*32+b'P'*32
        result=module.public_only(GuardedStream(data))
        self.assertTrue(result.startswith('ssh-ed25519 '))
        self.assertNotIn('SSSS',result)
    def test_wrong_layout_is_not_a_dump(self):
        with self.assertRaises(ValueError):
            module.public_only(io.BytesIO(struct.pack('>I',9999999)))
    def test_truncation_rejected(self):
        with self.assertRaises(ValueError):module.public_only(io.BytesIO(b''))

if __name__=='__main__':unittest.main()
