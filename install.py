"""Repeatable systemd installation. --root stages files without host operations."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SOURCE=Path(__file__).resolve().parent
APP=Path('/usr/local/lib/ml350-fan-control')
CONFIG=Path('/etc/ml350-fan-control')
UNITS=('ml350-fan-guard.service','ml350-fan-control.service')
MODULES=('fan_config.py','fan_curve.py','ilo_chif.py','fan_control.py','fan_cli.py','load_hpilo.py')
MARKER=APP/'.installation.json'
WRAPPER='#!/bin/sh\nexec /usr/bin/python3 /usr/local/lib/ml350-fan-control/fan_cli.py "$@"\n'

def target(root,path):
    result=root/path.as_posix().lstrip('/')
    # Never redirect an installation into an unrelated location through links.
    for item in (result,*result.parents):
        if item.is_symlink():raise RuntimeError('Installation paths cannot contain symlinks')
        if item==root:break
    return result

def write(path,content,mode):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=path.parent,prefix='.install-')
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as stream:stream.write(content)
        os.chmod(name,mode);os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def command(*args):
    subprocess.run(list(args),check=True,timeout=60)

def installed(root):
    marker=target(root,MARKER)
    if marker.exists():
        if json.loads(marker.read_text())!={'project':'ml350-fan-control','format':1}:
            raise RuntimeError('Unrecognized installation marker')
        return True
    return False

def files():
    return [*(APP/name for name in MODULES),Path('/usr/local/bin/ml350-fan'),
            *(Path('/etc/systemd/system')/name for name in UNITS),MARKER]

def install(root,staged):
    ours=installed(root)
    if not ours:
        for path in files():
            if target(root,path).exists():raise RuntimeError('Existing unowned installation file; refusing to overwrite')
    if not staged:
        for unit in (*UNITS,'taelo-fan-control.service','taelo-fan-guard.service'):
            result=subprocess.run(['systemctl','is-active','--quiet',unit],timeout=15)
            if result.returncode==0:
                raise RuntimeError('A fan service is running. Restore automatic cooling and stop it before installation')
    for name in MODULES:
        write(target(root,APP/name),(SOURCE/name).read_text(encoding='utf-8'),0o644)
    write(target(root,Path('/usr/local/bin/ml350-fan')),WRAPPER,0o755)
    for name in UNITS:
        write(target(root,Path('/etc/systemd/system')/name),(SOURCE/'systemd'/name).read_text(),0o644)
    config=target(root,CONFIG)
    config.mkdir(parents=True,exist_ok=True)
    os.chmod(config,0o700)
    for name in ('config.json','ilo-credentials.json'):
        path=target(root,CONFIG/name)
        if not path.exists():
            write(path,(SOURCE/'examples'/(name.replace('.json','.example.json'))).read_text(),0o600)
    settings=target(root,Path('/var/lib/ml350-fan-control'))
    settings.mkdir(parents=True,exist_ok=True);os.chmod(settings,0o700)
    write(target(root,MARKER),json.dumps({'project':'ml350-fan-control','format':1})+'\n',0o644)
    if not staged:command('systemctl','daemon-reload')
    print('Installed files; services were not enabled or started. Configure credentials, certificate, fans and CHIF; then run sudo ml350-fan preflight.')

def uninstall(root,staged):
    if not installed(root):raise RuntimeError('No owned installation found')
    if not staged:
        # Controller shutdown and ExecStopPost both restore; independently verify
        # restoration afterward. Keep the guard and all files if verification fails.
        command('systemctl','stop','ml350-fan-control.service')
        command('/usr/local/bin/ml350-fan','automatic')
        command('systemctl','disable','--now',*UNITS)
    for path in files():target(root,path).unlink(missing_ok=True)
    if not staged:command('systemctl','daemon-reload')
    print('Removed program and units. Credentials, certificate, curves and separately acquired HPE library were retained.')

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('install','uninstall'))
    p.add_argument('--root',type=Path,help='Offline staging directory; never runs services, drivers, network or hardware checks')
    args=p.parse_args(argv)
    try:
        staged=args.root is not None
        root=args.root.resolve() if staged else Path('/')
        if staged and (root==Path(root.anchor) or root==SOURCE or SOURCE in root.parents):
            raise RuntimeError('Choose a separate staging directory')
        if not staged and (sys.platform!='linux' or os.geteuid()!=0 or not Path('/run/systemd/system').is_dir()):
            raise RuntimeError('Real installation requires root on Linux with systemd')
        if staged:root.mkdir(parents=True,exist_ok=True)
        (install if args.action=='install' else uninstall)(root,staged)
        return 0
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        print('Setup failed: '+(str(error) if isinstance(error,RuntimeError) else type(error).__name__),file=sys.stderr)
        return 1

if __name__=='__main__':
    raise SystemExit(main())
