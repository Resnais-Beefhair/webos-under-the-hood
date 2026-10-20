#!/usr/bin/env python3
"""Offline publication backstop: source, links, assets and available Git history.

Not an anonymizer, secret detector guarantee, or substitute for image review.
Generated private state is ignored unless someone force-adds it to Git.
"""
import argparse
import ipaddress
import json
import re
import subprocess
import sys
from pathlib import Path

SKIP = {'.git','.local-state','.local-build','__pycache__','.pytest_cache','.venv','venv','dist'}
DOC_NETS = [ipaddress.ip_network(x) for x in ('192.0.2.0/24','198.51.100.0/24','203.0.113.0/24')]
SECRET = re.compile(r'-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----|(?:ssh-ed25519|ssh-rsa) [A-Za-z0-9+/]{40,}={0,3}')
IPV4 = re.compile(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])')
MAC = re.compile(r'(?i)(?<![0-9a-f])(?:[0-9a-f]{2}:){5}[0-9a-f]{2}(?![0-9a-f])')
CONNMAN = re.compile(r'ethernet_([0-9a-fA-F]{12})_cable')
ALLOWED_SYNTHETIC_MAC = {'00:00:00:00:00:01','aa:bb:cc:dd:ee:ff'}
ALLOWED_SYNTHETIC_SERVICE = {'000000000001','aabbccddeeff'}


def scan_text(text, name):
    issues=[]
    if SECRET.search(text): issues.append(name+': possible key material')
    for match in IPV4.finditer(text):
        try: addr=ipaddress.ip_address(match.group())
        except ValueError: continue
        # Limited broadcast is a protocol constant, not a device identifier.
        if str(addr) != '255.255.255.255' and not addr.is_global and not addr.is_loopback and not addr.is_unspecified and not any(addr in net for net in DOC_NETS):
            issues.append(name+': non-documentation private/special IPv4 address')
    if any(x.group().lower() not in ALLOWED_SYNTHETIC_MAC for x in MAC.finditer(text)):
        issues.append(name+': literal device MAC address')
    if any(x.group(1).lower() not in ALLOWED_SYNTHETIC_SERVICE for x in CONNMAN.finditer(text)):
        issues.append(name+': literal ConnMan device identifier')
    if re.search(r'(?i)(?:password|api_key|access_token|client_secret)\s*[:=]\s*[\"\'][^\"\'\n]{12,}[\"\']',text):
        issues.append(name+': possible assigned credential; review manually')
    return sorted(set(issues))


def run_git(root, *args):
    result=subprocess.run(['git','-C',str(root),*args],capture_output=True,check=False)
    if result.returncode:
        raise RuntimeError('Git audit read failed; cannot claim a clean index/history')
    return result.stdout


def forbidden_name(rel):
    p=Path(rel)
    return (any(part in SKIP for part in p.parts)
            or p.suffix.lower() in ('.key','.pem','.ppk','.qml','.pcap','.pcapng','.bak')
            or p.name.startswith(('id_ed25519','id_rsa','authorized_keys','known_hosts')))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    args=parser.parse_args();root=args.root.resolve();issues=[];checked=0;links=0;history=0
    if not (root/'README.md').is_file():raise SystemExit('Root must be this project, not an arbitrary directory')
    files=[p for p in root.rglob('*') if (p.is_file() or p.is_symlink()) and not any(part in SKIP for part in p.relative_to(root).parts)]
    # A force-added private state file must not disappear just because it is ignored.
    entries=run_git(root,'ls-files','--stage','-z').decode('utf-8','replace').split('\0') if (root/'.git').exists() else []
    for entry in filter(None,entries):
        metadata,rel=entry.split('\t',1)
        mode,sha,stage=metadata.split()
        p=root/rel
        if stage!='0':issues.append(rel+': unmerged index')
        if mode not in ('100644','100755'):issues.append(rel+': symlink/submodule mode in index')
        if forbidden_name(rel):
            issues.append(rel+': private/generated or firmware file tracked by Git')
        # Inspect the actual staged blob, which can differ from the worktree.
        data=run_git(root,'cat-file','blob',sha)
        if Path(rel).suffix.lower() not in ('.png','.jpg','.webp'):
            try:issues.extend(scan_text(data.decode('utf-8'),'index:'+rel))
            except UnicodeDecodeError:issues.append('index:'+rel+': unreviewed binary')
        elif b'Exif\x00\x00' in data or b'eXIf' in data:
            issues.append('index:'+rel+': image EXIF must be reviewed/removed')
        if p.is_file() and p not in files:files.append(p)
    for p in sorted(files):
        rel=p.relative_to(root).as_posix()
        if p.is_symlink():issues.append(rel+': symlink not permitted in release');continue
        if p.suffix.lower() in ('.key','.pem','.ppk','.qml','.pcap','.pcapng','.bak') or p.name.startswith(('id_ed25519','id_rsa','authorized_keys','known_hosts')):
            issues.append(rel+': forbidden release filename')
        data=p.read_bytes();checked+=1
        if p.suffix.lower() in ('.png','.jpg','.webp'):
            if b'Exif\x00\x00' in data or b'eXIf' in data:issues.append(rel+': image EXIF must be reviewed/removed')
            continue
        try:text=data.decode('utf-8')
        except UnicodeDecodeError:issues.append(rel+': unreviewed binary');continue
        issues.extend(scan_text(text,rel))
        if p.suffix=='.md':
            for target in re.findall(r'\]\(([^)]+)\)',text):
                target=target.split(' "',1)[0]
                if '://' in target or target.startswith(('#','mailto:')):continue
                dest=(p.parent/target.split('#',1)[0]).resolve();links+=1
                if not dest.is_relative_to(root):issues.append(rel+': local link escapes repository')
                elif not dest.exists():issues.append(rel+': broken local link '+target)
    if (root/'.git').exists():
        objects=run_git(root,'rev-list','--objects','--all').decode().splitlines()
        for row in objects:
            sha,_,name=row.partition(' ')
            if not name or run_git(root,'cat-file','-t',sha).strip()!=b'blob':continue
            if forbidden_name(name):issues.append('history:'+name+': forbidden release filename')
            data=run_git(root,'cat-file','blob',sha);history+=1
            if name.endswith(('.png','.jpg','.webp')):continue
            try:issues.extend(scan_text(data.decode('utf-8'), 'history:'+name))
            except UnicodeDecodeError:pass
    result={'files_checked':checked,'local_links_checked':links,'historical_blobs_checked':history,'issues':sorted(set(issues)),'scope':'Offline text/link/EXIF backstop; manually review pixels, attribution and complete unpublished history before publication.'}
    print(json.dumps(result,indent=2));return bool(result['issues'])


if __name__=='__main__':sys.exit(main())
