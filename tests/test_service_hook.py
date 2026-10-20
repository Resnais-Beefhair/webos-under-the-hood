#!/usr/bin/env python3
"""Fake-root tests of the TV hook; no actual systemd or mount calls."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK=Path(__file__).resolve().parents[1]/'services/privacy-services.sh'
FAKE='''#!PYTHON
import json,os,sys
from pathlib import Path
p=Path(os.environ['FAKE_STATE']); s=json.loads(p.read_text())
args=sys.argv[1:]; tool=Path(sys.argv[0]).name
if tool=='id': print(0); sys.exit(0)
if tool=='stat':
    print('foreign' if s['scenario']=='foreignmount' and args[-1]!='/dev/null' else 'owned-null')
    sys.exit(0)
if tool=='systemctl': s.setdefault('systemctl_calls',[]).append(args)
if tool=='mount':
    s['mount_calls']+=1
    if s['scenario']=='mountfail': sys.exit(1)
    with open(os.environ['WEBOS_PRIVACY_MOUNTS'],'a') as f:
        f.write('devtmpfs '+args[-1]+' devtmpfs rw 0 0\\n')
    if s['scenario']!='ineffective': s['voice_masked']=True
elif args[0]=='stop': pass
elif args[0]=='mask': pass
elif args[0]=='daemon-reload': pass
elif args[0]=='show':
    unit=args[1]; prop=args[3]
    if prop=='LoadState':
        print('LoadState='+('masked' if unit.startswith('contentminer') or s['voice_masked'] else 'loaded'))
    elif prop=='ActiveState':
        print('ActiveState='+('active' if s['scenario']=='stillactive' else 'inactive'))
elif args[0]=='is-enabled':
    print('masked-runtime' if args[1].startswith('contentminer') else ('masked' if s['voice_masked'] else 'enabled-runtime'))
else: raise RuntimeError(args)
p.write_text(json.dumps(s))
'''

class HookTests(unittest.TestCase):
    def run_case(self,scenario='normal',repeat=False,missing=False,version='20260421173614',foreign_link=False,locked=False):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name); (root/'bin').mkdir(); (root/'units').mkdir(); (root/'base').mkdir()
            if not missing: (root/'units/voiceinput.service').write_text('[Service]\nExecStart=/usr/sbin/voiceinput\n')
            if scenario=='symlink':
                (root/'units/voiceinput.service').unlink()
                (root/'units/voiceinput.service').symlink_to('/dev/null')
            (root/'mounts').write_text('')
            (root/'version').write_text(version)
            (root/'run').mkdir()
            if locked: (root/'run/.privacy-services.lock').mkdir()
            if foreign_link: (root/'run/contentminer.service').symlink_to('/foreign/unit')
            if scenario in ('foreignmount','stacked'):
                row='foreign '+str(root/'units/voiceinput.service')+' ext4 rw 0 0\n'
                (root/'mounts').write_text(row*(2 if scenario=='stacked' else 1))
            (root/'state').write_text(json.dumps({'scenario':scenario,'mount_calls':0,'voice_masked':False}))
            for tool in ('systemctl','mount','id','stat'):
                p=root/'bin'/tool; p.write_text(FAKE.replace('PYTHON',sys.executable)); p.chmod(0o755)
            env=dict(os.environ,PATH=str(root/'bin')+':'+os.environ['PATH'],
                     FAKE_STATE=str(root/'state'),WEBOS_PRIVACY_BASE=str(root/'base'),
                     WEBOS_PRIVACY_UNITDIR=str(root/'units'),WEBOS_PRIVACY_MOUNTS=str(root/'mounts'),
                     WEBOS_PRIVACY_VERSIONFILE=str(root/'version'),WEBOS_PRIVACY_RUNDIR=str(root/'run'))
            result=subprocess.run(['sh',str(HOOK),'--apply-services'],env=env,capture_output=True,text=True)
            if repeat and result.returncode==0:
                result=subprocess.run(['sh',str(HOOK),'--apply-services'],env=env,capture_output=True,text=True)
            state=json.loads((root/'state').read_text())
            state['lock_left']=(root/'run/.privacy-services.lock').exists()
            return result,state,(root/'base/privacy.log').read_text()
    def test_no_argument_is_not_an_apply(self):
        r=subprocess.run(['sh',str(HOOK)],capture_output=True,text=True)
        self.assertEqual(r.returncode,2)
        self.assertIn('--apply-services',r.stderr)
    def test_effective_mask(self):
        r,s,log=self.run_case(); self.assertEqual(r.returncode,0,r.stderr)
        self.assertTrue(s['voice_masked']); self.assertIn('[ok] voiceinput.service: masked, inactive',log)
        self.assertFalse(s['lock_left'])
    def test_foreign_lock_is_preserved_and_services_are_not_stopped(self):
        r,s,log=self.run_case(locked=True); self.assertNotEqual(r.returncode,0)
        self.assertTrue(s['lock_left'])
        self.assertEqual(s.get('systemctl_calls',[]),[])
    def test_idempotent_no_stacked_mounts(self):
        r,s,log=self.run_case(repeat=True); self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(s['mount_calls'],1)
    def test_bind_failure_is_not_success(self):
        r,s,log=self.run_case('mountfail'); self.assertNotEqual(r.returncode,0)
        self.assertNotIn('[ok] voiceinput.service',log)
    def test_ineffective_mask_is_not_success(self):
        r,s,log=self.run_case('ineffective'); self.assertNotEqual(r.returncode,0)
        self.assertIn('not masked',r.stderr)
    def test_missing_unit_is_rejected(self):
        r,s,log=self.run_case(missing=True); self.assertNotEqual(r.returncode,0)
        self.assertEqual(s['mount_calls'],0)
        self.assertEqual(s.get('systemctl_calls',[]),[])
    def test_wrong_firmware_is_rejected_before_stopping_services(self):
        r,s,log=self.run_case(version='unknown'); self.assertNotEqual(r.returncode,0)
        self.assertEqual(s.get('systemctl_calls',[]),[])
    def test_foreign_or_stacked_mounts_refuse_before_service_changes(self):
        for scenario in ('foreignmount','stacked'):
            with self.subTest(scenario=scenario):
                r,s,log=self.run_case(scenario); self.assertNotEqual(r.returncode,0)
                self.assertEqual(s.get('systemctl_calls',[]),[])
    def test_foreign_runtime_link_is_not_adopted(self):
        r,s,log=self.run_case(foreign_link=True); self.assertNotEqual(r.returncode,0)
        self.assertEqual(s.get('systemctl_calls',[]),[])
    def test_voice_unit_symlink_refuses_before_service_changes(self):
        r,s,log=self.run_case('symlink'); self.assertNotEqual(r.returncode,0)
        self.assertEqual(s.get('systemctl_calls',[]),[])
    def test_still_running_service_is_rejected(self):
        r,s,log=self.run_case('stillactive'); self.assertNotEqual(r.returncode,0)
        self.assertEqual(s['mount_calls'],0)

if __name__=='__main__': unittest.main()
