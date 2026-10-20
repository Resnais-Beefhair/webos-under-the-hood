"""Synthetic packet fixtures only; not recorded TV traffic."""
import struct
import socket
import importlib.util
from pathlib import Path
import unittest
_s=importlib.util.spec_from_file_location('passive_metadata',Path(__file__).resolve().parents[1]/'tools/passive_metadata.py')
_m=importlib.util.module_from_spec(_s);_s.loader.exec_module(_m)
dns_name,dns_summary,parse_frame=_m.dns_name,_m.dns_summary,_m.parse_frame

class MetadataParserTests(unittest.TestCase):
    def test_dns_query(self):
        packet=struct.pack('!HHHHHH',1,256,1,0,0,0)+b'\x04test\x07invalid\x00'+struct.pack('!HH',1,1)
        result=dns_summary(packet)
        self.assertEqual(result['questions'],[{'name':'test.invalid','type':1}])
        self.assertFalse(result['response'])
    def test_truncated_dns_rejected(self):
        with self.assertRaises(ValueError): dns_summary(b'abc')
    def test_pointer_cycle_rejected(self):
        with self.assertRaises(ValueError): dns_name(b'\xc0\x00',0)
    def test_valid_compression(self):
        self.assertEqual(dns_name(b'\x03www\x00\xc0\x00',5),('www',7))
    def test_truncated_ethernet_ignored(self):
        self.assertIsNone(parse_frame(b'\x00'*13))
    def test_udp_metadata_without_payload_log(self):
        eth=b'\x00'*12+b'\x08\x00'
        ip=struct.pack('!BBHHHBBH4s4s',69,0,31,1,0,64,17,0,socket.inet_aton('192.0.2.10'),b'\x08\x08\x08\x08')
        udp=struct.pack('!HHHH',1234,123,11,0)+b'abc'
        row=parse_frame(eth+ip+udp)
        self.assertEqual((row['src'],row['dst'],row['protocol']),('192.0.2.10','8.8.8.8','udp'))
        self.assertNotIn('payload',row)
if __name__=='__main__': unittest.main()
