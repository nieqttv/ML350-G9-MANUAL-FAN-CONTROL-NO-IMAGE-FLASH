import contextlib
import hashlib
import io
import json
import os
import stat
import struct
import ctypes as c
import ilo_chif
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import fan_cli as cli
import fan_config as config
import fan_control as f
import fan_curve
import install
import importlib.util

spec=importlib.util.spec_from_file_location('extract_chif',Path(__file__).resolve().parents[1]/'tools/extract_chif.py')
extractor=importlib.util.module_from_spec(spec);spec.loader.exec_module(extractor)
LINUX_ROOT=sys.platform=='linux' and os.geteuid()==0

def thermal(count=3):
    return {'Fans':[{'FanName':'Fan '+str(i),'CurrentReading':21,'Status':{'State':'Enabled','Health':'OK'}} for i in range(1,count+1)],
            'Temperatures':[{'Name':'CPU','ReadingCelsius':45,'UpperThresholdCritical':90,'Status':{'State':'Enabled','Health':'OK'}}]}

class PortableTests(unittest.TestCase):
    def test_config_schema_without_casaos(self):
        with patch.object(config,'secure_read',return_value=json.dumps({'installed_fans':['Fan 1','Fan 2','Fan 3','Fan 4']})):
            self.assertFalse(config.load_config()['casaos'])
        for value in ({'installed_fans':[]},{'installed_fans':['Fan 1','Fan 1']},{'installed_fans':['Fan 9']},
                      {'installed_fans':['Fan 1'],'runtime':'relative'},{'installed_fans':['Fan 1'],'casaos':1},
                      {'installed_fans':['Fan 1'],'unknown':True}):
            with patch.object(config,'secure_read',return_value=json.dumps(value)),self.assertRaises(ValueError):
                config.load_config()

    def test_four_fans_and_faults(self):
        with patch.object(f,'INSTALLED_FANS',('Fan 1','Fan 2','Fan 3','Fan 4')):
            self.assertEqual(len(f.telemetry(thermal(4))[0]),4)
            with self.assertRaises(RuntimeError):f.telemetry(thermal())
            for value in (0,float('nan'),True,101):
                data=thermal(4);data['Fans'][3]['CurrentReading']=value
                with self.assertRaises(RuntimeError):f.telemetry(data)
        with patch.object(f,'INSTALLED_FANS',('Fan 1','Fan 2','Fan 3')):
            with self.assertRaises(RuntimeError):f.telemetry(thermal(4))
            data=thermal(4);data['Fans'][3].update(CurrentReading=0,Status={'State':'Enabled','Health':'Critical'})
            self.assertEqual(len(f.telemetry(data)[0]),3) # Explicit, physically absent fan only.
            data['Temperatures'][0]['ReadingCelsius']=float('nan')
            with self.assertRaises(RuntimeError):f.telemetry(data)

    def test_one_cpu_and_missing_core_label(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);hw=root/'hwmon0';hw.mkdir();(hw/'name').write_text('coretemp')
            for index,label in enumerate(('Package id 0','Core 0','Core 2','Core 4','Core 6'),1):
                (hw/('temp'+str(index)+'_label')).write_text(label)
                (hw/('temp'+str(index)+'_input')).write_text('60000')
            (hw/'temp1_crit').write_text('93000')
            topology={0:{0,2,4,6}}
            self.assertEqual(len(fan_curve.cpu_temperatures(root,topology)),1)
            (hw/'temp5_label').unlink()
            with self.assertRaises(RuntimeError):fan_curve.cpu_temperatures(root,topology)
            with self.assertRaises(RuntimeError):fan_curve.cpu_temperatures(root,{0:{0,2,4},1:{0}})

    def test_topology_deduplicates_smt(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for n,(sid,cid) in enumerate(((0,0),(0,0),(0,2),(1,0))):
                p=root/('cpu'+str(n));(p/'topology').mkdir(parents=True)
                (p/'topology/physical_package_id').write_text(str(sid))
                (p/'topology/core_id').write_text(str(cid))
            self.assertEqual(fan_curve.cpu_topology(root),{0:{0,2},1:{0}})

    def test_staging_repeat_install_uninstall_preserves_private_data(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'stage'
            with patch.object(install,'command',side_effect=AssertionError('Host command during staging')),patch.object(install.subprocess,'run',side_effect=AssertionError('Host operation')):
                self.assertEqual(install.main(['install','--root',str(root)]),0)
                private=root/'etc/ml350-fan-control/ilo-credentials.json'
                private.write_text('private sentinel')
                settings=root/'var/lib/ml350-fan-control/curve.json'
                settings.write_text('[[40,10],[50,13],[60,17],[70,21],[85,34]]')
                lib=root/'usr/local/lib/ml350-fan-control/ilorest_chif.so';lib.write_bytes(b'private library')
                self.assertEqual(install.main(['install','--root',str(root)]),0)
                self.assertEqual(private.read_text(),'private sentinel')
                self.assertEqual(json.loads(settings.read_text()),[[40,10],[50,13],[60,17],[70,21],[85,34]])
                self.assertEqual(install.main(['uninstall','--root',str(root)]),0)
                self.assertTrue(private.exists());self.assertTrue(settings.exists());self.assertTrue(lib.exists())
                self.assertFalse((root/'usr/local/bin/ml350-fan').exists())

    def test_uninstall_failure_keeps_guard_and_program(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            install.install(root,True)
            seen=[]
            def fail(*args):
                seen.append(args)
                if args[0]=='/usr/local/bin/ml350-fan':raise RuntimeError('Restoration pending')
            with patch.object(install,'command',side_effect=fail),self.assertRaises(RuntimeError):
                install.uninstall(root,False)
            self.assertTrue((root/'usr/local/bin/ml350-fan').exists())
            self.assertFalse(any('disable' in call for call in seen))

    def test_unowned_install_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'usr/local/bin/ml350-fan';p.parent.mkdir(parents=True);p.write_text('unowned')
            with self.assertRaises(RuntimeError):install.install(root,True)
            self.assertEqual(p.read_text(),'unowned')

    def test_extractor_requires_terms_and_exact_wheel(self):
        with tempfile.TemporaryDirectory() as td:
            wheel=Path(td)/'unknown.whl';wheel.write_bytes(b'untrusted')
            for accepted in (False,True):
                with self.assertRaises(ValueError):extractor.extract(wheel,Path(td)/'out',accepted)
            self.assertFalse((Path(td)/'out').exists())

    def test_firmware_handshake_gate_and_channel_cleanup(self):
        class Function:
            def __init__(self,callback):self.callback=callback
            def __call__(self,*args):return self.callback(*args)
        class Library:
            def __init__(self,minor):
                self.closed=False
                self.ChifInitialize=Function(lambda p:0)
                self.ChifCreate=Function(self.create)
                self.ChifClose=Function(self.close)
                self.ChifPacketExchangeSpecifyTimeout=Function(self.exchange)
                self.minor=minor
            def create(self,pointer):
                c.cast(pointer,c.POINTER(c.c_void_p))[0]=c.c_void_p(1)
                return 0
            def close(self,handle):self.closed=True;return 0
            def exchange(self,handle,request,response,size,timeout):
                self.request=bytes(request)[:8]
                raw=bytearray(100);struct.pack_into('<HHHH',raw,0,100,1,0x8002,0)
                raw[16:18]=bytes((self.minor,2))
                c.memmove(response,bytes(raw),len(raw))
                return 0
        for minor in (82,83):
            lib=Library(minor)
            with patch.object(ilo_chif,'require_model'),patch.object(ilo_chif,'library_path',return_value=Path('fake.so')),patch.object(ilo_chif.c,'CDLL',return_value=lib):
                if minor==82:
                    with ilo_chif.FanChannel():pass
                else:
                    with self.assertRaisesRegex(RuntimeError,'2.82'):
                        with ilo_chif.FanChannel():self.fail('Unsupported firmware accepted')
                self.assertTrue(lib.closed)

    def test_pin_failure_sends_no_authentication(self):
        class Sock:
            def getpeercert(self,**kwargs):return b'changed certificate'
        class Connection:
            sock=Sock()
            def connect(self):pass
            def request(self,*args,**kwargs):raise AssertionError('Credentials were sent before pin verification')
            def close(self):pass
        with patch.object(f,'CFG',config.DEFAULTS),patch.object(f,'credentials',return_value={'host':'ilo.test','username':'test','password':'SECRET'}),patch.object(f,'secure_read',return_value='cert'),patch.object(f.ssl,'PEM_cert_to_DER_cert',return_value=b'pinned'),patch.object(f.http.client,'HTTPSConnection',return_value=Connection()):
            with self.assertRaisesRegex(RuntimeError,'certificate changed'):f.request()

    def test_cli_validation_no_hardware(self):
        with patch.object(cli.control,'configure'),patch.object(cli,'require_model'),patch.object(cli.control,'validate',wraps=f.validate),patch.object(cli.control,'locked',side_effect=AssertionError('Invalid request reached mailbox')):
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                for value in ('0','101'):
                    self.assertEqual(cli.main(['manual',value]),1)
                self.assertEqual(cli.main(['curve','--points','[[40,50],[50,20]]']),1)

    def test_cli_status_freshness(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'status.json'
            p.write_text(json.dumps({'ready':True,'heartbeat':time.time()-16,'guardHeartbeat':time.time()}))
            with patch.object(f,'STATUS',p):self.assertFalse(cli.status()['ready'])

    def test_cli_automatic_cancels_pending_command_and_preserves_curve(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'request.json';p.write_text('pending')
            current={'restoreNeeded':False,'curve':[[40,10],[85,34]]}
            with patch.object(f,'locked',contextlib.nullcontext),patch.object(f,'CLI_REQUEST',p),patch.object(f,'state',return_value=current),patch.object(f,'restore',return_value=current),patch.object(f,'publish'):
                self.assertEqual(cli.automatic()['mode'],'automatic')
                self.assertFalse(p.exists());self.assertEqual(current['curve'],[[40,10],[85,34]])

    def test_cli_ack_and_timeout_restore(self):
        now=time.time()
        ready={'ready':True,'heartbeat':now,'guardHeartbeat':now}
        def ack(path,command):
            ready['ack']={'id':command['id'],'ok':True}
        with tempfile.TemporaryDirectory() as td,patch.object(f,'RUN',Path(td)),patch.object(f,'locked',contextlib.nullcontext),patch.object(cli,'status',return_value=ready),patch.object(f,'atomic',side_effect=ack):
            self.assertTrue(cli.submit({'mode':'percentage','output':50})['ack']['ok'])
            with patch.object(cli,'automatic',return_value={'ok':True}) as restore,self.assertRaisesRegex(RuntimeError,'acknowledged'):
                cli.submit({'mode':'percentage','output':50},timeout=0)
            restore.assert_called_once()

    def test_wrong_iLO_identity_is_rejected_before_CHIF(self):
        with patch.object(f,'CFG',config.DEFAULTS),patch.object(cli,'require_model'),patch.object(cli,'credentials'),patch.object(cli,'secure_read'),patch.object(cli,'verify_library'),patch.object(Path,'is_char_device',return_value=True),patch.object(Path,'read_text',return_value='HOST-UUID'),patch.object(f,'request',return_value={'Model':'ProLiant ML350 Gen9','UUID':'OTHER-UUID'}),patch.object(f,'FanChannel',side_effect=AssertionError('CHIF accessed before identity validation')):
            with self.assertRaisesRegex(RuntimeError,'UUID'):cli.preflight()

    @unittest.skipUnless(LINUX_ROOT,'Linux root ownership/no-follow check')
    def test_secure_config_permissions_and_symlinks(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'secret';p.write_text('private');p.chmod(0o600)
            self.assertEqual(config.secure_read(p),'private')
            p.chmod(0o644)
            with self.assertRaises(ValueError):config.secure_read(p)
            link=Path(td)/'link';link.symlink_to(p)
            with self.assertRaises(OSError):config.secure_read(link)

    @unittest.skipUnless(LINUX_ROOT,'Linux root file validation')
    def test_cli_mailbox_rejects_symlink_and_world_readable_request(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);request=root/'request.json';source=root/'other.json'
            source.write_text('{}');request.symlink_to(source)
            with patch.object(f,'CLI_REQUEST',request),self.assertRaises(OSError):f.read_command(request)
            request.unlink();request.write_text('{}');request.chmod(0o644)
            with patch.object(f,'CLI_REQUEST',request),self.assertRaises(ValueError):f.read_command(request)

    @unittest.skipUnless(LINUX_ROOT,'Linux root filesystem')
    def test_actual_controller_guard_and_cli_with_fake_hardware(self):
        import threading
        hardware={'active':False,'remaining':0,'raw':255}
        class Channel:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def query(self):return {'active':hardware['active'],'remaining':hardware['remaining']}
            def percentage(self):return {'locked':hardware['active'],'raw':hardware['raw']}
            def default(self):hardware.update(active=False,remaining=0);return self.query()
            def boost(self,seconds):hardware.update(active=True,remaining=seconds);return self.query()
            def set_percentage(self,p):hardware['raw']=(p*255+99)//100;return self.percentage()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);cfg=dict(config.DEFAULTS,runtime=str(root/'run'),settings=str(root/'settings/curve.json'),installed_fans=['Fan 1','Fan 2','Fan 3'])
            cpu=[{'id':0,'celsius':60,'maximum':60,'critical':93,'alarm':False}]
            old_running=f.running
            with patch.object(f,'load_config',return_value=cfg),patch.object(f,'require_model'),patch.object(f,'cpu_topology',return_value={0:{0}}),patch.object(f,'cpu_temperatures',return_value=cpu),patch.object(f,'chif_present',return_value=True),patch.object(f,'FanChannel',Channel),patch.object(f,'request',side_effect=lambda adjustment=None:thermal() if adjustment is None else {}),patch.object(f.signal,'signal'):
                f.configure();f.running=True
                workers=[threading.Thread(target=f.main,args=(mode,),daemon=True) for mode in ('guard','controller')]
                try:
                    for worker in workers:worker.start()
                    deadline=time.monotonic()+8
                    while time.monotonic()<deadline:
                        try:
                            if cli.status()['ready']:break
                        except OSError:pass
                        time.sleep(.1)
                    result=cli.submit({'mode':'percentage','output':50})
                    self.assertEqual(result['targetPercent'],50);self.assertTrue(hardware['active'])
                    self.assertEqual(cli.automatic()['mode'],'automatic');self.assertFalse(hardware['active'])
                    # Stop both daemon threads, then exercise the independent guard alone.
                    f.running=False
                    for worker in workers:worker.join(timeout=5)
                    self.assertFalse(any(worker.is_alive() for worker in workers))
                    with f.locked():
                        current=f.state();current.update(boostActive=True,heartbeat=time.time()-20,restoreNeeded=False)
                        hardware['active']=True;f.atomic(f.STATE,current)
                    f.running=True
                    workers=[threading.Thread(target=f.main,args=('guard',),daemon=True)]
                    workers[0].start()
                    deadline=time.monotonic()+3
                    while hardware['active'] and time.monotonic()<deadline:time.sleep(.1)
                    self.assertFalse(hardware['active'],'Independent guard did not restore stale controller')
                finally:
                    f.running=False
                    for worker in workers:worker.join(timeout=5)
                    f.running=old_running
                    self.assertFalse(any(worker.is_alive() for worker in workers))
