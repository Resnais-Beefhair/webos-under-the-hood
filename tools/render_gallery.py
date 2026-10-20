#!/usr/bin/env python3
"""Render original evidence illustrations from allowlisted REAL observations.

Optional developer dependency: Pillow. No network, TV access or screenshot upload.
Images are reformatted measurements, not fabricated terminal screenshots.
"""
import argparse
import json
from pathlib import Path


def main():
    from PIL import Image, ImageDraw, ImageFont
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--font-directory', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    data = json.loads((root/'assets/evidence/cx-internals.json').read_text())
    folders = [args.font_directory] if args.font_directory else []
    folders += [Path('/usr/share/fonts/truetype/dejavu'), Path('/usr/share/fonts/dejavu')]
    fonts = next((x for x in folders if x and (x/'DejaVuSans.ttf').is_file()), None)
    if fonts is None:
        raise SystemExit('Supply --font-directory with DejaVuSans.ttf, DejaVuSans-Bold.ttf and DejaVuSansMono.ttf. Fonts are not bundled.')
    bg, ink, muted = '#f4f1e8', '#173335', '#566c6b'
    green, pale, red, line = '#17675a', '#dcebe2', '#c54d34', '#d2d9d0'
    def font(n, bold=False, mono=False):
        file = 'DejaVuSansMono.ttf' if mono else 'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'
        return ImageFont.truetype(str(fonts/file),n)
    def canvas(h):
        im=Image.new('RGB',(1600,h),bg)
        return im,ImageDraw.Draw(im)
    def text(d,xy,s,n=30,color=ink,bold=False,mono=False):
        d.text(xy,s,font=font(n,bold,mono),fill=color,spacing=9)
    def card(d,box):d.rounded_rectangle(box,radius=22,fill='#fffdf8',outline=line,width=2)
    def label(d,xy,s):text(d,xy,s,23,muted,True)
    def footer(d,y):
        d.line((64,y,1536,y),fill=line,width=2)
        text(d,(64,y+20),'REAL DEVICE DATA / '+data['capture_date']+' / IDENTIFIERS OMITTED',22,muted,True)
        text(d,(64,y+55),'Reformatted observations, not a terminal screenshot. One rooted CX, not a universal claim.',22,muted)
    # Editorial overview: measured Linux state, not fake output.
    im,d=canvas(1060)
    label(d,(64,52),'WEBOS UNDER THE HOOD  /  FIELD NOTES 01')
    text(d,(64,112),'The TV beneath the TV.',75,ink,True)
    text(d,(64,216),'A read-only operating system. Small, reversible changes on top.',30,muted)
    card(d,(64,310,760,790));card(d,(800,310,1536,790))
    label(d,(102,347),'THE FOUNDATION')
    text(d,(102,402),'Linux '+data['kernel_release'],29,ink,False,True)
    text(d,(102,463),'SquashFS firmware',42,ink,True)
    text(d,(102,526),'Root mount: '+next(m['mode'] for m in data['mounts'] if m['target']=='/').upper(),30,green,True)
    text(d,(102,600),'webOS '+data['os_info']['webos_release']+' / build '+data['os_info']['webos_build_id'],29,ink)
    text(d,(102,652),'Firmware '+data['os_info']['webos_manufacturing_version'],29,ink)
    text(d,(102,710),'No firmware bytes overwritten.',26,muted)
    label(d,(838,347),'THE INTERVENTIONS')
    for i,(unit,caption) in enumerate([('voiceinput.service','effective unit mask'),('contentminer.service','existing mask preserved'),('voiceconductor.service','left running deliberately')]):
        y=410+i*115;state=data['services'][unit]
        text(d,(838,y),unit,30,ink,True,True)
        text(d,(838,y+42),state['LoadState']+' / '+state['ActiveState']+'  ·  '+caption,23,green if state['LoadState']=='masked' else muted)
    text(d,(64,845),'Preserve the television. Do not “debloat” its dependencies.',32,ink,True)
    footer(d,922);im.save(root/'assets/inside-webos.png',optimize=True)
    # Direct service state view.
    im,d=canvas(1030)
    label(d,(64,52),'WEBOS UNDER THE HOOD  /  FIELD NOTES 02')
    text(d,(64,112),'A mask is a state, not a command.',60,ink,True)
    text(d,(64,206),'Read back what the service manager actually believes.',30,muted)
    columns=[64,716,1015,1290]
    for x,s in zip(columns,['SYSTEMD UNIT','LOAD','ACTIVE','FILE STATE']):label(d,(x,306),s)
    for i,unit in enumerate(['voiceinput.service','contentminer.service','voiceconductor.service']):
        y=366+i*136;state=data['services'][unit]
        d.rounded_rectangle((64,y-18,1536,y+93),radius=18,fill=pale if state['LoadState']=='masked' else '#e8e8de')
        text(d,(86,y+9),unit,31,ink,True,True)
        text(d,(716,y+12),state['LoadState'],29,green,True)
        text(d,(1015,y+12),state['ActiveState'],29,ink)
        text(d,(1290,y+14),state['UnitFileState'],22,muted,False,True)
    text(d,(64,812),'An active voice-related process is not evidence of microphone recording.',27,ink,True)
    footer(d,900);im.save(root/'assets/service-states.png',optimize=True)
    # Native paths and verified mount mode: the optional overlay does not replace firmware.
    im,d=canvas(1230)
    label(d,(64,52),'WEBOS UNDER THE HOOD  /  FIELD NOTES 03')
    text(d,(64,112),'A different view of the same file.',61,ink,True)
    text(d,(64,212),'Optional Home preview overlay. Original firmware stays underneath.',29,muted)
    mounts=[m for m in data['mounts'] if 'com.webos.app.home' in m['target']]
    for i,m in enumerate(mounts):
        y=310+i*190;card(d,(64,y,1536,y+160))
        label(d,(96,y+23),'QML VIEW' if i==0 else 'HOME SNAPSHOT PATH / '+str(i))
        path=m['target'];parts=path.rsplit('/',1)
        text(d,(96,y+68),parts[0]+'/',26,ink,False,True)
        text(d,(96,y+108),parts[1],27,ink,True,True)
        text(d,(1362,y+24),m['mode'].upper(),34,green,True)
    text(d,(64,934),'Producer guard → owned read-only bind → fresh Home process',30,ink,True)
    text(d,(64,990),'No binary replacement. No deleted snapshots. No SAM restart.',28,muted)
    footer(d,1086);im.save(root/'assets/home-overlays.png',optimize=True)
    print('Rendered inside-webos.png, service-states.png and home-overlays.png from real allowlisted evidence.')


if __name__=='__main__':main()
