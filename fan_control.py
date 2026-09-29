"""Root controller with an independent guard and optional CasaOS mailboxes."""
import base64, fcntl, hashlib, http.client, json, math, os, signal, sqlite3, ssl, stat, sys, tempfile, time
from contextlib import contextmanager
from pathlib import Path
from ilo_chif import FanChannel
from fan_curve import DEFAULT_CURVE, SETTINGS, validate_curve, cpu_temperatures as read_cpu_temperatures, cpu_topology, curve_output, next_target, cooling_protection
from fan_config import load_config, credentials, secure_read, require_model
CFG=None
RUN=Path('/run/ml350-fan-control')
USERS=Path('/var/lib/casaos')
INSTALLED_FANS=()
CASAOS=False
CPU_TOPOLOGY=None

def cpu_temperatures():
    return read_cpu_temperatures(topology=CPU_TOPOLOGY)
STATE=RUN/'lease.json'
STATUS=RUN/'status.json'
MAX_ADJUSTMENT=50
BOOST_SECONDS=60
running=True
CLI_REQUEST=RUN/'request.json'

def configure(cfg=None):
    global CFG,RUN,USERS,STATE,STATUS,SETTINGS,INSTALLED_FANS,CASAOS,CLI_REQUEST
    CFG=cfg or load_config()
    RUN=Path(CFG['runtime']);USERS=Path(CFG['casaos_users'])
    STATE=RUN/'lease.json';STATUS=RUN/'status.json';CLI_REQUEST=RUN/'request.json'
    SETTINGS=Path(CFG['settings']);INSTALLED_FANS=tuple(CFG['installed_fans']);CASAOS=CFG['casaos']

def atomic(path,value,mode=0o600):
    # A unique, private temporary file avoids exposing credentials or following links.
    fd,name=tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(value,stream,separators=(',',':'));stream.flush();os.fsync(stream.fileno())
        os.chmod(name,mode)
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

@contextmanager
def locked():
    RUN.mkdir(mode=0o755,parents=True,exist_ok=True)
    info=RUN.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
        raise RuntimeError('Runtime directory must be root-owned and not writable by others')
    fd=os.open(RUN/'control.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a') as f:
        fcntl.flock(f,fcntl.LOCK_EX)
        yield

def state():
    try:return json.loads(STATE.read_text())
    except (OSError,ValueError):return {'adjustment':0,'restoreNeeded':True,'ready':False}

def request(adjustment=None,path='/redfish/v1/Chassis/1/Thermal/'):
    cfg=credentials(CFG or load_config())
    pin=hashlib.sha256(ssl.PEM_cert_to_DER_cert(secure_read((CFG or load_config())['certificate']))).digest()
    connection=http.client.HTTPSConnection(cfg['host'],timeout=4,context=ssl._create_unverified_context())
    try:
        connection.connect()
        if hashlib.sha256(connection.sock.getpeercert(binary_form=True)).digest()!=pin:raise RuntimeError('iLO certificate changed')
        auth='Basic '+base64.b64encode((cfg['username']+':'+cfg['password']).encode()).decode()
        body=None if adjustment is None else json.dumps({'Oem':{'Hp':{'FanPercentAdjust':adjustment}}})
        connection.request('GET' if adjustment is None else 'PATCH',path,body=body,headers={'Authorization':auth,'Content-Type':'application/json','Accept':'application/json'})
        response=connection.getresponse();raw=response.read(1048577)
        if len(raw)>1048576:raise RuntimeError('iLO response too large')
        data=json.loads(raw)
        if not isinstance(data,dict):raise RuntimeError('iLO response invalid')
        if response.status!=200:raise RuntimeError('iLO request failed')
        if adjustment is not None and not any(x.get('MessageID')=='Base.0.10.Success' for x in data.get('Messages',[])):raise RuntimeError('iLO did not confirm change')
        return data
    finally:connection.close()

def admins():
    if not CASAOS:return {'root'}
    with sqlite3.connect('file:'+str(USERS/'db/user.db')+'?mode=ro',uri=True,timeout=2) as db:
        return {'root'}|{str(row[0]) for table in ['o_users','sub_users'] for row in db.execute("select id from "+table+" where role='admin'")}

def links(ids):
    if not CASAOS:return
    for directory in USERS.iterdir():
        if not directory.name.isdecimal() or not directory.is_dir():continue
        link=directory/'taelo_fan_control.json'
        if directory.name in ids:
            if not link.exists() and not link.is_symlink():link.symlink_to(STATUS)
        elif link.is_symlink() and link.readlink()==STATUS:link.unlink()

def telemetry(data,baseline=None):
    if not INSTALLED_FANS:raise RuntimeError('Installed fans must be configured')
    raw=data.get('Fans',[])
    named={fan.get('FanName'):fan for fan in raw}
    if len(named)!=len(raw):raise RuntimeError('Duplicate or unnamed fan readings')
    fans=[]
    for name in INSTALLED_FANS:
        fan=named.get(name,{})
        value=fan.get('CurrentReading')
        if fan.get('Status',{}).get('State')=='Absent' or fan.get('Status',{}).get('Health')!='OK' or type(value) not in (int,float) or not math.isfinite(value) or not 0<value<=100:
            raise RuntimeError('Installed fan readings unavailable or unhealthy')
        fans.append({'name':name,'percent':value,'health':'OK'})
    for name,fan in named.items():
        value=fan.get('CurrentReading')
        if name not in INSTALLED_FANS and fan.get('Status',{}).get('State')!='Absent' and type(value) in (int,float) and value>0:
            raise RuntimeError('A running fan is missing from installed_fans')
    temps={}
    for sensor in data.get('Temperatures',[]):
        if sensor.get('Status',{}).get('State')=='Absent':continue
        value=sensor.get('ReadingCelsius')
        name=sensor.get('Name')
        if not isinstance(name,str) or name in temps or type(value) not in (int,float) or not math.isfinite(value) or not -20<value<125:
            raise RuntimeError('Temperature readings unavailable')
        temps[name]=sensor
    if not temps:raise RuntimeError('Temperature readings unavailable')
    for sensor in temps.values():
        limits=[sensor[key]-5 for key in ('UpperThresholdCritical','UpperThresholdNonCritical') if type(sensor.get(key)) in (int,float) and math.isfinite(sensor[key]) and sensor[key]>0]
        if sensor.get('Status',{}).get('Health') not in (None,'OK') or (limits and sensor['ReadingCelsius']>=min(limits)):raise RuntimeError('Temperature limit reached')
    if baseline and not set(baseline).issubset(temps):raise RuntimeError('Temperature sensor missing')
    return fans,{name:sensor['ReadingCelsius'] for name,sensor in temps.items()}

def validate(command,now):
    if isinstance(command,dict) and command.get('mode')=='curve':
        if set(command)!={'id','createdAt','mode','curve'}:raise ValueError('Invalid curve request')
        validate({'id':command['id'],'createdAt':command['createdAt'],'mode':'percentage','output':100},now)
        return 'curve',validate_curve(command['curve'])
    if not isinstance(command,dict) or set(command) not in ({'id','createdAt','output'},{'id','createdAt','output','mode'}):raise ValueError('Invalid request')
    if not isinstance(command['id'],str) or not 8<=len(command['id'])<=80:raise ValueError('Invalid request ID')
    if type(command['createdAt']) not in (int,float) or not now-15<=command['createdAt']<=now+5:raise ValueError('Request expired')
    mode=command.get('mode','automatic')
    if not isinstance(mode,str) or mode not in ('automatic','full','percentage'):raise ValueError('Invalid fan mode')
    if type(command['output']) is not int:raise ValueError('Fan speed must be an integer')
    if mode=='percentage':
        if not 1<=command['output']<=100:raise ValueError('Fan speed must be 1–100%')
        return mode,command['output']
    if not 100-MAX_ADJUSTMENT<=command['output']<=100:raise ValueError('Output must be 50–100% of automatic')
    if mode=='full' and command['output']!=100:raise ValueError('Full speed requires 100% output')
    return ('percentage',100) if mode=='full' else (mode,100-command['output'])

def manual(current):
    return bool(current.get('adjustment') or current.get('boostActive'))

def chif_present():
    return Path('/dev/hpilo/d0ccb0').exists()

def restore(current,reason=''):
    current.update(restoreNeeded=True,ready=False)
    atomic(STATE,current)
    failures=[]
    if chif_present() or current.get('boostActive'):
        try:
            with FanChannel() as channel:channel.default()
            current.update(boostActive=False,boostAvailable=True,boostRemaining=0,targetPercent=None,requestedPercent=None,thermalProtection=False)
        except Exception:
            failures.append('Fan override restoration pending')
            current['boostAvailable']=False
    else:current.update(boostActive=False,boostAvailable=False,boostRemaining=0,targetPercent=None)
    # Always attempt both restoration paths, even when one is unavailable.
    try:
        request(0)
        current['adjustment']=0
    except Exception:failures.append('Automatic cooling restoration pending')
    if failures:
        current.update(error='; '.join(failures),ready=False,expiresAt=0)
    else:
        current.update(restoreNeeded=False,expiresAt=0,activatedAt=0,owner=None,baseline={},curveActive=False,ready=True,error=reason)
    atomic(STATE,current)
    return current

def publish(current):
    public={key:current.get(key) for key in ['adjustment','expiresAt','ready','error','ack','fans','sampledAt','restoreNeeded','boostActive','boostAvailable','targetPercent','curveActive','curve','cpuTemperatures','curveTemperature','requestedPercent','thermalProtection']}
    public.update(version=3,updatedAt=time.time(),minimumOutput=1,maximumOutput=100,mode='curve' if current.get('curveActive') else 'percentage' if current.get('boostActive') else 'automatic')
    atomic(STATUS,public,0o644)

def read_command(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size>8192 or (path==CLI_REQUEST and (info.st_uid!=0 or info.st_mode&0o077)):raise ValueError('Invalid request file')
        with os.fdopen(fd,'r',closefd=False) as stream:return json.loads(stream.read(8193))
    finally:os.close(fd)

def consume_cli(current,ids):
    if CLI_REQUEST.exists() or CLI_REQUEST.is_symlink():
        try:
            command=read_command(CLI_REQUEST)
            CLI_REQUEST.unlink()
            current=process(current,'root',command,ids,time.time())
        except (OSError,ValueError):
            CLI_REQUEST.unlink(missing_ok=True)
    return current

def start_boost(current):
    with FanChannel() as channel:
        channel.default()
        channel.boost(BOOST_SECONDS)
        channel.set_percentage(current.get('targetPercent') or 100)
        result=channel.query()
        if not result['active'] or result['remaining']<=0:raise RuntimeError('Fan speed was not confirmed')
    current.update(boostActive=True,boostAvailable=True,boostRemaining=result['remaining'])
    return current

def process(current,uid,command,ids,now):
    nonce=command.get('id') if isinstance(command,dict) else None
    try:
        if uid not in ids:raise ValueError('Administrator access required')
        mode,adjustment=validate(command,now)
        if mode in ('percentage','curve') or adjustment:
            if not current.get('ready') or current.get('restoreNeeded'):raise ValueError('Fan control unavailable')
            if mode in ('percentage','curve') and not current.get('boostAvailable'):raise ValueError('Fan speed control unavailable')
            if now-current.get('lastCommandAt',0)<2:raise ValueError('Please wait before changing again')
            fans,baseline=telemetry(request(),current.get('baseline'))
            cpus=cpu_temperatures()
            current.update(cpuTemperatures=cpus,curveTemperature=max(x['maximum'] for x in cpus))
            started=current.get('activatedAt') or now
            current.update(restoreNeeded=True,ready=False,expiresAt=0,heartbeat=now)
            atomic(STATE,current)
            if mode in ('percentage','curve'):
                request(0)
                current['adjustment']=0
                # Persist the possible override before issuing the command.
                current['boostActive']=True
                current['curveActive']=mode=='curve'
                if mode=='curve':current['curve']=adjustment
                current['requestedPercent']=None if mode=='curve' else adjustment
                current['thermalProtection']=cooling_protection(cpus)
                desired=curve_output(adjustment,current['curveTemperature']) if mode=='curve' else adjustment
                current['targetPercent']=100 if current['thermalProtection'] else desired
                current.pop('fallSince',None)
                atomic(STATE,current)
                start_boost(current)
                if mode=='curve':
                    SETTINGS.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
                    atomic(SETTINGS,adjustment)
            else:
                current['curveActive']=False
                if current.get('boostActive'):
                    with FanChannel() as channel:channel.default()
                    current.update(boostActive=False,boostRemaining=0,targetPercent=None)
                request(adjustment)
                current['adjustment']=adjustment
            current.update(restoreNeeded=False,ready=True,owner=uid,baseline=current.get('baseline') or baseline,activatedAt=started,fans=fans,sampledAt=time.time(),error='')
        else:current=restore(current)
        current['lastCommandAt']=now
        current['ack']={'id':nonce,'user':uid,'ok':current.get('ready',False),'error':current.get('error','')}
    except Exception as error:
        reason=str(error) if isinstance(error,(ValueError,RuntimeError)) else 'Fan request failed'
        if current.get('restoreNeeded') or manual(current):current=restore(current,reason)
        current['ack']={'id':nonce,'user':uid,'ok':False,'error':reason}
    atomic(STATE,current)
    return current

def overdue(current,now):
    return (manual(current) or current.get('restoreNeeded')) and (current.get('restoreNeeded') or now-current.get('heartbeat',0)>15)

def poll_boost(current):
    if not current.get('boostActive'):return current
    with FanChannel() as channel:
        result=channel.query()
        value=channel.percentage()
    if not result['active'] or not value['locked']:raise RuntimeError('Fan override ended unexpectedly')
    expected=((current.get('targetPercent') or 100)*255+99)//100
    if value['raw']!=expected:raise RuntimeError('Fan speed readback changed')
    current['boostRemaining']=result['remaining']
    if result['remaining']<20:
        current.update(restoreNeeded=True,ready=False)
        atomic(STATE,current)
        start_boost(current)
        current.update(restoreNeeded=False,ready=True)
    return current

def poll_curve(current):
    cpus=cpu_temperatures()
    current.update(cpuTemperatures=cpus,curveTemperature=max(x['maximum'] for x in cpus))
    if not current.get('boostActive'):return current
    current['thermalProtection']=cooling_protection(cpus,current.get('thermalProtection',False))
    desired=curve_output(current['curve'],current['curveTemperature']) if current.get('curveActive') else current.get('requestedPercent') or current['targetPercent']
    target=100 if current['thermalProtection'] else next_target(current,desired,time.monotonic())
    if target!=current.get('targetPercent'):
        current.update(restoreNeeded=True,ready=False)
        atomic(STATE,current)
        with FanChannel() as channel:channel.set_percentage(target)
        current.update(targetPercent=target,restoreNeeded=False,ready=True)
    return current

def saved_curve():
    try:return validate_curve(json.loads(SETTINGS.read_text()))
    except (OSError,ValueError):return [point[:] for point in DEFAULT_CURVE]

def main(mode):
    global running,CPU_TOPOLOGY
    configure()
    require_model()
    if mode=='controller':CPU_TOPOLOGY=cpu_topology()
    signal.signal(signal.SIGTERM,lambda *args:stop())
    signal.signal(signal.SIGINT,lambda *args:stop())
    seen={};last_poll=0
    if mode=='restore':
        with locked():publish(restore(state()))
        return
    if mode=='controller':
        with locked():
            current=restore(state());current['curve']=saved_curve();current['heartbeat']=time.time();atomic(STATE,current);publish(current)
            CLI_REQUEST.unlink(missing_ok=True)
            for directory in (USERS.iterdir() if CASAOS else []):
                path=directory/'taelo_fan_request.json'
                if directory.name.isdecimal() and path.exists():seen[str(path)]=path.stat().st_mtime_ns
    try:
        while running:
            with locked():
                current=state();now=time.time()
                if mode=='guard':
                    if overdue(current,now):current=restore(current,'Returned to Default')
                    current['guardHeartbeat']=time.time();atomic(STATE,current);publish(current)
                else:
                    current['heartbeat']=now;atomic(STATE,current)
                    try:
                        ids=admins();links(ids)
                        if manual(current) and current.get('owner') not in ids:current=restore(current)
                        if now-last_poll>=3:
                            try:
                                fans,temps=telemetry(request(),current.get('baseline'))
                                current.update(fans=fans,sampledAt=time.time(),baseline=current.get('baseline') or temps)
                                current=poll_boost(current)
                                current=poll_curve(current)
                                current['ready']=not current.get('restoreNeeded') and time.time()-current.get('guardHeartbeat',0)<12
                            except Exception as error:
                                reason=str(error) if isinstance(error,RuntimeError) else 'Fan or temperature readings unavailable'
                                current=restore(current,reason)
                                current['ready']=False
                            last_poll=now
                        if time.time()-current.get('guardHeartbeat',0)>=12 and manual(current):current=restore(current,'Restoration guard unavailable')
                        current=consume_cli(current,ids)
                        for uid in sorted(ids-{'root'}):
                            path=USERS/uid/'taelo_fan_request.json'
                            try:
                                modified=path.lstat().st_mtime_ns
                                if seen.get(str(path))==modified:continue
                                seen[str(path)]=modified
                                current=process(current,uid,read_command(path),ids,time.time())
                            except (OSError,ValueError):continue
                    except Exception:
                        current=restore(current,'Administrator check unavailable')
                    current['heartbeat']=time.time();atomic(STATE,current);publish(current)
            time.sleep(1)
    finally:
        if mode=='controller':
            with locked():publish(restore(state()))

def stop():
    global running
    running=False

if __name__=='__main__':
    if os.geteuid()!=0:raise SystemExit('Run as root')
    if len(sys.argv)!=2 or sys.argv[1] not in ('controller','guard','restore'):raise SystemExit('controller, guard or restore')
    main(sys.argv[1])


