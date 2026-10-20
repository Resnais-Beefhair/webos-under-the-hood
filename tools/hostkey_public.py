#!/usr/bin/env python
"""Export ONLY the public half of this TV's Dropbear Ed25519 host key.

Device-side Python 2.7/3. This is not a private-key backup or generic parser.
The 32-byte private seed is SEEKED OVER, never read, returned or logged.
Prefer an installed upstream dropbearkey public export when available.
"""
from __future__ import print_function
import base64
import struct
import sys


def read_exact(f, n):
    data = f.read(n)
    if len(data) != n:
        raise ValueError('Truncated supported key container')
    return data


def public_only(f):
    length = struct.unpack('>I', read_exact(f, 4))[0]
    if length != len(b'ssh-ed25519'):
        raise ValueError('Not the supported Dropbear Ed25519 format')
    kind = read_exact(f, length)
    if kind != b'ssh-ed25519':
        raise ValueError('Not the supported Dropbear Ed25519 key type')
    length = struct.unpack('>I', read_exact(f, 4))[0]
    if length != 64:
        raise ValueError('Unexpected Ed25519 key layout; do not dump this file')
    f.seek(32, 1)  # Skip the private seed WITHOUT reading it.
    public = read_exact(f, 32)
    blob = struct.pack('>I', len(kind)) + kind + struct.pack('>I', 32) + public
    return 'ssh-ed25519 ' + base64.b64encode(blob).decode('ascii')


def main():
    if len(sys.argv) != 3 or sys.argv[1] != '--export-public':
        raise SystemExit('Usage on the TV: python hostkey_public.py --export-public /var/lib/webosbrew/sshd/dropbear_ed25519_host_key')
    with open(sys.argv[2], 'rb') as f:
        print(public_only(f))


if __name__ == '__main__':
    main()
