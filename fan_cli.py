"""Standalone root-only CLI. Commands go through the monitored controller."""
import argparse
import fcntl
import json
import os
import stat
import sys
import time
import uuid
from pathlib import Path
import fan_control as control
from fan_config import credentials, require_model, secure_read, verify_library
from fan_curve import validate_curve

def preflight():
    cfg=control.CFG
    require_model()
    credentials(cfg)
    secure_read(cfg['certificate'])
    library=Path(cfg['chif_library'])
    verify_library(library)
    if not Path('/dev/hpilo/d0ccb0').is_char_device():
        raise RuntimeError('Stock hpilo device missing; run sudo modprobe hpilo')
    system=control.request(path='/redfish/v1/Systems/1/')
    if system.get('Model') not in ('ProLiant ML350 Gen9','HP ProLiant ML350 Gen9','HPE ProLiant ML350 Gen9'):
        raise RuntimeError('Configured iLO does not report an ML350 Gen9')
    local_uuid=Path('/sys/class/dmi/id/product_uuid').read_text().strip().lower()
    if not local_uuid or str(system.get('UUID','')).lower()!=local_uuid:
        raise RuntimeError('Configured iLO UUID does not match this host')
    manager=control.request(path='/redfish/v1/Managers/1/')
    if manager.get('FirmwareVersion') not in ('2.82','iLO 4 v2.82','iLO 4 2.82'):
        raise RuntimeError('Only iLO 4 firmware 2.82 is verified')
    control.telemetry(control.request())
    control.cpu_temperatures()
    with control.FanChannel() as channel:
        channel.query()
        channel.percentage()
    if cfg['casaos']:
        control.admins()
        if not Path(cfg['casaos_users']).is_dir():
            raise RuntimeError('CasaOS custom-storage directory missing')
    return {'ok':True,'model':'ML350 Gen9','firmware':'iLO 4 2.82','checks':'read-only; no fan changes'}

def status():
    value=json.loads(control.STATUS.read_text())
    now=time.time()
    value['controllerFresh']=0<=now-value.get('heartbeat',0)<15
    value['guardFresh']=0<=now-value.get('guardHeartbeat',0)<12
    value['ready']=bool(value.get('ready') and value['controllerFresh'] and value['guardFresh'])
    return value

def automatic():
    # Works even if the controller is stopped. Invalidate a pending CLI command first.
    with control.locked():
        control.CLI_REQUEST.unlink(missing_ok=True)
        value=control.restore(control.state())
        control.publish(value)
        if value.get('restoreNeeded'):
            raise RuntimeError('Restoration pending; keep the guard running and check connectivity')
        return {'ok':True,'mode':'automatic'}

def submit(command,timeout=20):
    command=dict(command,id=str(uuid.uuid4()),createdAt=time.time())
    control.validate(command,time.time())
    # Keep concurrent CLI clients from overwriting each other's single mailbox/ack.
    with control.locked():
        fd=os.open(control.RUN/'cli.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        with control.locked():
            value=status()
            if not value['ready']:
                raise RuntimeError('Controller/guard not ready; run status and preflight')
            command['createdAt']=time.time()
            control.atomic(control.CLI_REQUEST,command)
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            value=status()
            ack=value.get('ack') or {}
            if ack.get('id')==command['id']:
                if not ack.get('ok'):raise RuntimeError(ack.get('error') or 'Fan request rejected')
                return value
            time.sleep(.2)
        automatic()
        raise RuntimeError('Command was not acknowledged; returned to automatic control')

def parser():
    p=argparse.ArgumentParser(description='ML350 Gen9 / iLO 4 2.82 fan control')
    sub=p.add_subparsers(dest='command',required=True)
    for name in ('status','preflight','automatic'):
        sub.add_parser(name)
    sub.add_parser('manual').add_argument('percent',type=int)
    curve=sub.add_parser('curve')
    source=curve.add_mutually_exclusive_group(required=True)
    source.add_argument('--points',help='JSON array of [temperature, percentage] pairs')
    source.add_argument('--file',type=Path,help='JSON curve file')
    source.add_argument('--saved',action='store_true',help='Apply the saved curve explicitly')
    return p

def main(argv=None):
    args=parser().parse_args(argv)
    try:
        if os.geteuid()!=0:raise RuntimeError('Run with sudo/root')
        control.configure()
        require_model()
        if args.command=='status':result=status()
        elif args.command=='preflight':result=preflight()
        elif args.command=='automatic':result=automatic()
        elif args.command=='manual':
            result=submit({'mode':'percentage','output':args.percent})
        else:
            text=args.points if args.points is not None else (
                secure_read(control.SETTINGS) if args.saved else args.file.read_text()
            )
            result=submit({'mode':'curve','curve':validate_curve(json.loads(text))})
        print(json.dumps(result,indent=2))
        return 0
    except RuntimeError as error:
        print(str(error),file=sys.stderr)
        return 1
    except (OSError,ValueError):
        # Never emit exceptions from configuration, JSON, TLS or authentication.
        print('Fan command failed. Check root-owned configuration, status and preflight; no credentials are printed.',file=sys.stderr)
        return 1

if __name__=='__main__':
    raise SystemExit(main())
