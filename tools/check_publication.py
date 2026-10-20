#!/usr/bin/env python3
"""Offline publication backstop: source, links, assets and available Git history.

Not an anonymizer, secret detector guarantee, or substitute for image review.
Generated private state is ignored unless someone force-adds it to Git.
"""
import argparse
import ipaddress
import json
import re
import struct
import subprocess
import sys
import zlib
from pathlib import Path

SKIP = {'.git', '.local-state', '.local-build', '__pycache__', '.pytest_cache', '.venv', 'venv', 'dist'}
DOC_NETS = [ipaddress.ip_network(x) for x in ('192.0.2.0/24', '198.51.100.0/24', '203.0.113.0/24')]
# Exact public service exceptions already documented as optional DNS providers.
ALLOWED_PUBLIC_IPV4 = {ipaddress.ip_address(x) for x in (
    '1.1.1.1', '9.9.9.9', '94.140.14.14', '94.140.15.15', '8.8.8.8',
)}  # documented DNS providers and an existing resolver test fixture
# A fixed local system account path used by the connection guide, not a user-home exemption.
ALLOWED_HOME_PATHS = {'/home/root'}
PROJECT_COMMIT_EMAILS = {'294102483+resnais-beefhair@users.noreply.github.com'}
SECRET = re.compile(r'-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----|(?:ssh-ed25519|ssh-rsa) [A-Za-z0-9+/]{40,}={0,3}')
IPV4 = re.compile(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])')
MAC = re.compile(r'(?i)(?<![0-9a-f])(?:[0-9a-f]{2}:){5}[0-9a-f]{2}(?![0-9a-f])')
CONNMAN = re.compile(r'ethernet_([0-9a-fA-F]{12})_cable')
IDENTIFIER = re.compile(
    r'''(?ix)
    (?<![a-z0-9])(?:nduid|device[ _-]?id|serial(?:[ _-](?:number|no))?|s/n)(?![a-z0-9])
    \s*(?:["']?\s*[:=]\s*|\s+(?:is|of)\s+)
    ["']?([a-z0-9][a-z0-9_-]{7,})
    ''')
SAFE_IDENTIFIER_VALUES = {
    'device_id', 'device-id', 'deviceid', 'serial', 'serial_no', 'serial-number',
    'serial_number', 'serialnumber', 'nduid', 'string', 'integer', 'unknown',
}
UNIX_HOME = re.compile(r'(?<![a-z0-9_])(/home/[a-z0-9._-]+)(?=$|[/\\\s"\'<>:;,)!?])', re.IGNORECASE)
WINDOWS_HOME = re.compile(r'(?i)(?<![a-z0-9_])([a-z]:\\Users\\[a-z0-9._-]+)(?=$|[\\/\s"\'<>:;,)!?])')
EMAIL = re.compile(r"(?i)(?<![\w.+-])[\w.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+(?![\w.-])")
ALLOWED_SYNTHETIC_MAC = {'00:00:00:00:00:01', 'aa:bb:cc:dd:ee:ff'}
ALLOWED_SYNTHETIC_SERVICE = {'000000000001', 'aabbccddeeff'}
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
MAX_PNG_BYTES = 64 * 1024 * 1024
MAX_PNG_CHUNKS = 100_000
MAX_PNG_TEXT_CHUNK_BYTES = 4 * 1024 * 1024
MAX_PNG_TEXT_BYTES = 1024 * 1024


def scan_text(text, name):
    issues = []
    if SECRET.search(text):
        issues.append(name + ': possible key material')
    for match in IPV4.finditer(text):
        try:
            addr = ipaddress.ip_address(match.group())
        except ValueError:
            continue
        # Explicit protocol/documentation exceptions; public services are exact-match only.
        if (any(addr in net for net in DOC_NETS)
                or addr == ipaddress.ip_address('255.255.255.255')
                or addr.is_loopback or addr.is_unspecified or addr in ALLOWED_PUBLIC_IPV4):
            continue
        issues.append(name + ': non-allowlisted IPv4 address')
    if any(x.group().lower() not in ALLOWED_SYNTHETIC_MAC for x in MAC.finditer(text)):
        issues.append(name + ': literal device MAC address')
    if any(x.group(1).lower() not in ALLOWED_SYNTHETIC_SERVICE for x in CONNMAN.finditer(text)):
        issues.append(name + ': literal ConnMan device identifier')
    for match in IDENTIFIER.finditer(text):
        if match.group(1).casefold() not in SAFE_IDENTIFIER_VALUES:
            issues.append(name + ': contextual device identifier')
            break
    for match in UNIX_HOME.finditer(text):
        if match.group(1).casefold() not in ALLOWED_HOME_PATHS:
            issues.append(name + ': user home path')
            break
    if WINDOWS_HOME.search(text):
        issues.append(name + ': Windows user home path')
    if re.search(r'(?i)(?:password|api_key|access_token|client_secret)\s*[:=]\s*["\'][^"\'\n]{12,}["\']', text):
        issues.append(name + ': possible assigned credential; review manually')
    return sorted(set(issues))


def _malformed_png(name):
    return [name + ': malformed PNG (fail-closed)']


def _valid_png_keyword(value):
    return bool(value) and len(value) <= 79 and all(byte >= 32 and byte != 127 for byte in value)


def _inflate_png_text(data):
    decompressor = zlib.decompressobj()
    decoded = decompressor.decompress(data, MAX_PNG_TEXT_BYTES + 1)
    if len(decoded) > MAX_PNG_TEXT_BYTES or decompressor.unconsumed_tail:
        raise ValueError('PNG text expansion limit exceeded')
    decoded += decompressor.flush(MAX_PNG_TEXT_BYTES + 1 - len(decoded))
    if (len(decoded) > MAX_PNG_TEXT_BYTES or not decompressor.eof
            or decompressor.unused_data or decompressor.unconsumed_tail):
        raise ValueError('invalid or oversized compressed PNG text')
    return decoded


def _png_text_fields(kind, payload):
    if len(payload) > MAX_PNG_TEXT_CHUNK_BYTES:
        raise ValueError('PNG text chunk exceeds parser limit')
    if kind == b'tEXt':
        keyword, separator, text = payload.partition(b'\x00')
        if not separator or not _valid_png_keyword(keyword):
            raise ValueError('invalid tEXt chunk')
        return [keyword.decode('latin-1'), text.decode('latin-1')]
    if kind == b'zTXt':
        keyword, separator, remainder = payload.partition(b'\x00')
        if not separator or not _valid_png_keyword(keyword) or len(remainder) < 2 or remainder[0] != 0:
            raise ValueError('invalid zTXt chunk')
        return [keyword.decode('latin-1'), _inflate_png_text(remainder[1:]).decode('latin-1')]
    keyword, separator, remainder = payload.partition(b'\x00')
    if not separator or not _valid_png_keyword(keyword) or len(remainder) < 2:
        raise ValueError('invalid iTXt chunk')
    compressed, method = remainder[0], remainder[1]
    if compressed not in (0, 1) or method != 0:
        raise ValueError('unsupported iTXt compression method')
    language, separator, remainder = remainder[2:].partition(b'\x00')
    if not separator:
        raise ValueError('invalid iTXt language field')
    translated, separator, text = remainder.partition(b'\x00')
    if not separator:
        raise ValueError('invalid iTXt translated keyword field')
    if compressed:
        text = _inflate_png_text(text)
    try:
        return [keyword.decode('latin-1'), language.decode('ascii'),
                translated.decode('utf-8'), text.decode('utf-8')]
    except UnicodeDecodeError as exc:
        raise ValueError('invalid iTXt UTF-8') from exc


def scan_png(data, name):
    """Scan PNG text chunks with size, structure, CRC and decompression limits."""
    if len(data) > MAX_PNG_BYTES or not data.startswith(PNG_SIGNATURE):
        return _malformed_png(name)
    position = len(PNG_SIGNATURE)
    count = 0
    saw_ihdr = False
    saw_idat = False
    saw_iend = False
    issues = []
    while position < len(data):
        count += 1
        if count > MAX_PNG_CHUNKS or position + 12 > len(data):
            return _malformed_png(name)
        length = struct.unpack('>I', data[position:position + 4])[0]
        kind = data[position + 4:position + 8]
        end = position + 12 + length
        if (end > len(data) or not all(65 <= byte <= 90 or 97 <= byte <= 122 for byte in kind)
                or kind[2] & 0x20):
            return _malformed_png(name)
        payload = data[position + 8:position + 8 + length]
        stored_crc = struct.unpack('>I', data[position + 8 + length:end])[0]
        if (zlib.crc32(kind + payload) & 0xffffffff) != stored_crc:
            return _malformed_png(name)
        if not saw_ihdr:
            if kind != b'IHDR' or length != 13:
                return _malformed_png(name)
            saw_ihdr = True
        elif kind == b'IHDR':
            return _malformed_png(name)
        if kind == b'IDAT':
            saw_idat = True
        if kind in (b'tEXt', b'zTXt', b'iTXt'):
            try:
                for field in _png_text_fields(kind, payload):
                    issues.extend(scan_text(field, name + ': PNG text'))
            except (ValueError, zlib.error):
                return _malformed_png(name)
        position = end
        if kind == b'IEND':
            if length != 0 or position != len(data):
                return _malformed_png(name)
            saw_iend = True
            break
    if not (saw_ihdr and saw_idat and saw_iend):
        return _malformed_png(name)
    return sorted(set(issues))


def scan_image(data, name):
    issues = []
    if b'Exif\x00\x00' in data or b'eXIf' in data:
        issues.append(name + ': image EXIF must be reviewed/removed')
    if Path(name).suffix.lower() == '.png':
        issues.extend(scan_png(data, name))
    return issues


def run_git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError('Git audit read failed; cannot claim a clean index/history')
    return result.stdout


def scan_commit_metadata(root):
    """Scan available refs' author/committer fields and messages, not commit hashes."""
    raw = run_git(root, 'log', '--all', '-z',
                  '--format=%H%x00%an%x00%ae%x00%cn%x00%ce%x00%B')
    fields = raw.decode('utf-8', 'replace').split('\x00')
    issues = []
    position = 0
    while position + 5 < len(fields):
        commit, author, author_email, committer, committer_email, message = fields[position:position + 6]
        label = 'commit:' + commit[:12] + ':'
        for field_name, value in (('author', author), ('author email', author_email),
                                  ('committer', committer), ('committer email', committer_email),
                                  ('message', message)):
            issues.extend(scan_text(value, label + field_name))
            for email in EMAIL.finditer(value):
                if email.group().casefold() not in PROJECT_COMMIT_EMAILS:
                    issues.append(label + field_name + ': unapproved metadata email')
        position += 6
    return sorted(set(issues))


def forbidden_name(rel):
    p = Path(rel)
    return (any(part in SKIP for part in p.parts)
            or p.suffix.lower() in ('.key', '.pem', '.ppk', '.qml', '.pcap', '.pcapng', '.bak')
            or p.name.startswith(('id_ed25519', 'id_rsa', 'authorized_keys', 'known_hosts')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    issues = []
    checked = 0
    links = 0
    history = 0
    commits = 0
    if not (root / 'README.md').is_file():
        raise SystemExit('Root must be this project, not an arbitrary directory')
    files = [p for p in root.rglob('*') if (p.is_file() or p.is_symlink())
             and not any(part in SKIP for part in p.relative_to(root).parts)]
    # A force-added private state file must not disappear just because it is ignored.
    entries = run_git(root, 'ls-files', '--stage', '-z').decode('utf-8', 'replace').split('\0') if (root / '.git').exists() else []
    for entry in filter(None, entries):
        metadata, rel = entry.split('\t', 1)
        mode, sha, stage = metadata.split()
        p = root / rel
        if stage != '0':
            issues.append(rel + ': unmerged index')
        if mode not in ('100644', '100755'):
            issues.append(rel + ': symlink/submodule mode in index')
        if forbidden_name(rel):
            issues.append(rel + ': private/generated or firmware file tracked by Git')
        # Inspect the actual staged blob, which can differ from the worktree.
        data = run_git(root, 'cat-file', 'blob', sha)
        if Path(rel).suffix.lower() in ('.png', '.jpg', '.webp'):
            issues.extend(scan_image(data, 'index:' + rel))
        else:
            try:
                issues.extend(scan_text(data.decode('utf-8'), 'index:' + rel))
            except UnicodeDecodeError:
                issues.append('index:' + rel + ': unreviewed binary')
        if p.is_file() and p not in files:
            files.append(p)
    for p in sorted(files):
        rel = p.relative_to(root).as_posix()
        if p.is_symlink():
            issues.append(rel + ': symlink not permitted in release')
            continue
        if p.suffix.lower() in ('.key', '.pem', '.ppk', '.qml', '.pcap', '.pcapng', '.bak') or p.name.startswith(('id_ed25519', 'id_rsa', 'authorized_keys', 'known_hosts')):
            issues.append(rel + ': forbidden release filename')
        data = p.read_bytes()
        checked += 1
        if p.suffix.lower() in ('.png', '.jpg', '.webp'):
            issues.extend(scan_image(data, rel))
            continue
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            issues.append(rel + ': unreviewed binary')
            continue
        issues.extend(scan_text(text, rel))
        if p.suffix == '.md':
            for target in re.findall(r'\]\(([^)]+)\)', text):
                target = target.split(' "', 1)[0]
                if '://' in target or target.startswith(('#', 'mailto:')):
                    continue
                dest = (p.parent / target.split('#', 1)[0]).resolve()
                links += 1
                if not dest.is_relative_to(root):
                    issues.append(rel + ': local link escapes repository')
                elif not dest.exists():
                    issues.append(rel + ': broken local link ' + target)
    if (root / '.git').exists():
        objects = run_git(root, 'rev-list', '--objects', '--all').decode('utf-8', 'replace').splitlines()
        for row in objects:
            sha, _, name = row.partition(' ')
            if not name or run_git(root, 'cat-file', '-t', sha).strip() != b'blob':
                continue
            if forbidden_name(name):
                issues.append('history:' + name + ': forbidden release filename')
            data = run_git(root, 'cat-file', 'blob', sha)
            history += 1
            if name.lower().endswith(('.png', '.jpg', '.webp')):
                issues.extend(scan_image(data, 'history:' + name))
                continue
            try:
                issues.extend(scan_text(data.decode('utf-8'), 'history:' + name))
            except UnicodeDecodeError:
                pass
        issues.extend(scan_commit_metadata(root))
        commits = len(run_git(root, 'rev-list', '--all').splitlines())
    result = {
        'files_checked': checked,
        'local_links_checked': links,
        'historical_blobs_checked': history,
        'commits_checked': commits,
        'issues': sorted(set(issues)),
        'scope': 'Offline text/link/PNG-text/EXIF and available Git-history backstop; manually review pixels, attribution and complete unpublished history before publication.',
    }
    print(json.dumps(result, indent=2))
    return bool(result['issues'])


if __name__ == '__main__':
    sys.exit(main())
