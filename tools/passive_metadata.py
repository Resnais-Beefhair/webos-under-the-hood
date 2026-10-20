#!/usr/bin/env python
"""Bounded passive Ethernet metadata probe, Python 2.7/3.x.
No promiscuous mode, packet files, application payload logs or settings changes.
"""
from __future__ import print_function
import collections
import json
import os
import select
import socket
import struct
import sys
import time

def byte(data,index):
    value=data[index]
    return value if isinstance(value,int) else ord(value)
def u16(data,offset): return struct.unpack_from('!H',data,offset)[0]
def dns_name(data,offset,seen=None):
    seen=set() if seen is None else seen
    if offset in seen or len(seen)>24: raise ValueError('DNS pointer cycle/depth')
    seen.add(offset); labels=[]; end=None
    for _ in range(128):
        if offset>=len(data): raise ValueError('DNS truncated label')
        size=byte(data,offset); offset+=1
        if size==0: return '.'.join(labels),(end if end is not None else offset)
        if size & 192 == 192:
            if offset>=len(data): raise ValueError('DNS truncated pointer')
            pointer=((size & 63)<<8)|byte(data,offset)
            suffix,_=dns_name(data,pointer,seen)
            labels.append(suffix)
            return '.'.join(labels),offset+1
        if size>63 or offset+size>len(data): raise ValueError('DNS invalid label')
        labels.append(data[offset:offset+size].decode('ascii','replace'))
        offset+=size
    raise ValueError('DNS too many labels')
def dns_summary(data):
    if len(data)<12: raise ValueError('DNS truncated header')
    flags=u16(data,2); count=u16(data,4); offset=12; questions=[]
    if count>32: raise ValueError('DNS unreasonable question count')
    for _ in range(count):
        name,offset=dns_name(data,offset)
        if offset+4>len(data): raise ValueError('DNS truncated question')
        questions.append({'name':name,'type':u16(data,offset)})
        offset+=4
    return {'response':bool(flags & 32768),'rcode':flags & 15,'questions':questions}
def parse_frame(frame):
    if len(frame)<14: return None
    typ=u16(frame,12); start=14
    for _ in range(2):
        if typ not in (33024,34984): break
        if len(frame)<start+4: return None
        typ=u16(frame,start+2); start+=4
    packet=frame[start:]
    if typ==2048:
        if len(packet)<20 or byte(packet,0)>>4!=4: return None
        hlen=(byte(packet,0)&15)*4
        if hlen<20 or len(packet)<hlen: return None
        if u16(packet,6)&8191: return None
        proto=byte(packet,9); src=socket.inet_ntoa(packet[12:16]); dst=socket.inet_ntoa(packet[16:20])
        size=u16(packet,2); payload=packet[hlen:]
    elif typ==34525:
        if len(packet)<40: return None
        proto=byte(packet,6)
        src=socket.inet_ntop(socket.AF_INET6,packet[8:24]); dst=socket.inet_ntop(socket.AF_INET6,packet[24:40])
        size=40+u16(packet,4); payload=packet[40:]
    else: return None
    if proto not in (6,17) or len(payload)<4: return None
    sport,dport=struct.unpack_from('!HH',payload,0)
    result={'src':src,'dst':dst,'sport':sport,'dport':dport,'protocol':'tcp' if proto==6 else 'udp','wire_ip_bytes':size}
    if proto==6 and len(payload)>=14:
        result['syn']=bool(byte(payload,13)&2)
    if proto==17 and (sport==53 or dport==53) and len(payload)>=20:
        try: result['dns']=dns_summary(payload[8:])
        except (ValueError,struct.error): result['dns_parse_error']=True
    return result

def main():
    if len(sys.argv)!=3 or sys.argv[1]!='--ack-private-metadata':
        raise SystemExit('Usage: python passive_metadata.py --ack-private-metadata SECONDS (1..180); private metadata output, no promiscuous mode')
    seconds=float(sys.argv[2])
    label='private-observation'
    if not 1<=seconds<=180: raise ValueError('Duration must be 1..180 seconds')
    if os.getuid()!=0 or open('/etc/version').read().strip()!='20260421173614':
        raise RuntimeError('Root and the documented tested firmware build required')
    started=time.time(); flows=collections.defaultdict(lambda:{'packets':0,'ip_bytes':0,'syn_packets':0})
    dns=[]; errors=0; frames=0; stopped_by_limit=False
    sock=socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(3))
    try:
        sock.bind(('eth0',0)); sock.setblocking(False)
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,65536)
        while time.time()-started<seconds:
            ready,_,_=select.select([sock],[],[],min(.5,max(0,seconds-(time.time()-started))))
            if not ready: continue
            frame=sock.recv(2048); frames+=1
            if frames>=100000: stopped_by_limit=True; break
            try: item=parse_frame(frame)
            except (ValueError,IndexError,struct.error): errors+=1; continue
            if not item: continue
            key=(item['protocol'],item['src'],item['sport'],item['dst'],item['dport'])
            flow=flows[key]; flow['packets']+=1; flow['ip_bytes']+=item['wire_ip_bytes']; flow['syn_packets']+=int(item.get('syn',False))
            if 'dns' in item:
                if len(dns)<2000:
                    event=dict(item['dns']); event.update({'t':round(time.time()-started,3),'src':item['src'],'dst':item['dst']}); dns.append(event)
            errors+=int(item.get('dns_parse_error',False))
    finally: sock.close()
    output=[]
    for key,value in flows.items():
        row=dict(zip(('protocol','src','sport','dst','dport'),key)); row.update(value); output.append(row)
    output.sort(key=lambda row:(-row['ip_bytes'],row['dst'],row['dport']))
    print(json.dumps({'label':label,'pid':os.getpid(),'started_unix':started,'duration_seconds':round(time.time()-started,3),
         'frames_seen':frames,'stopped_by_packet_limit':stopped_by_limit,'parse_errors':errors,
         'flows':output,'dns_events':dns,'limits':['metadata only; no payload stored','DNS cache may hide lookups',
         'DNS-over-HTTPS/TLS and HTTPS payload are opaque','IPv6 extension-header traffic is not parsed',
         'no controlled app playback or exhaustive coverage']},sort_keys=True))
if __name__=='__main__': main()
