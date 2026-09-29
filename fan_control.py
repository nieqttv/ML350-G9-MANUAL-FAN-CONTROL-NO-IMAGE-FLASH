"""Administrator fan controls using native ZimaOS custom storage."""
import base64, fcntl, hashlib, http.client, json, os, signal, sqlite3, ssl, stat, sys, time
from contextlib import contextmanager
from pathlib import Path
from ilo_chif import FanChannel
ROOT=Path('/DATA/.taelo/zimaos-dashboard')
RUN=Path('/run/taelo-fan-control')
USERS=Path('/var/lib/casaos')
STATE=RUN/'lease.json'
STATUS=RUN/'status.json'
MAX_ADJUSTMENT=50
BOOST_SECONDS=3600
running=True

def atomic(path,value,mode=0o600):
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,separators=(',',':')))
    tmp.chmod(mode)
    tmp.replace(path)

@contextmanager
def locked():
    RUN.mkdir(mode=0o755,parents=True,exist_ok=True)
    with (RUN/'control.lock').open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX)
        yield

def state():
    try:return json.loads(STATE.read_text())
    except (OSError,ValueError):return {'adjustment':0,'restoreNeeded':True,'ready':False}

def request(adjustment=None):
    cfg=json.loads((ROOT/'ilo-credentials.json').read_text())
    pin=hashlib.sha256(ssl.PEM_cert_to_DER_cert((ROOT/'ilo-certificate.pem').read_text())).digest()
    connection=http.client.HTTPSConnection(cfg['host'],timeout=4,context=ssl._create_unverified_context())
    try:
        connection.connect()
        if hashlib.sha256(connection.sock.getpeercert(binary_form=True)).digest()!=pin:raise RuntimeError('iLO certificate changed')
        auth='Basic '+base64.b64encode((cfg['username']+':'+cfg['password']).encode()).decode()
        body=None if adjustment is None else json.dumps({'Oem':{'Hp':{'FanPercentAdjust':adjustment}}})
        connection.request('GET' if adjustment is None else 'PATCH','/redfish/v1/Chassis/1/Thermal/',body=body,headers={'Authorization':auth,'Content-Type':'application/json','Accept':'application/json'})
        response=connection.getresponse();data=json.loads(response.read())
        if response.status!=200:raise RuntimeError('iLO request failed')
        if adjustment is not None and not any(x.get('MessageID')=='Base.0.10.Success' for x in data.get('Messages',[])):raise RuntimeError('iLO did not confirm change')
        return data
    finally:connection.close()

def admins():
    with sqlite3.connect('file:/var/lib/casaos/db/user.db?mode=ro',uri=True,timeout=2) as db:
        return {str(row[0]) for table in ['o_users','sub_users'] for row in db.execute("select id from "+table+" where role='admin'")}

def links(ids):
    for directory in USERS.iterdir():
        if not directory.name.isdecimal() or not directory.is_dir():continue
        link=directory/'taelo_fan_control.json'
        if directory.name in ids:
            if not link.exists() and not link.is_symlink():link.symlink_to(STATUS)
        elif link.is_symlink() and link.readlink()==STATUS:link.unlink()

def telemetry(data,baseline=None):
    fans=[{'name':fan.get('FanName'),'percent':fan.get('CurrentReading'),'health':fan.get('Status',{}).get('Health')} for fan in data.get('Fans',[]) if fan.get('FanName') in ('Fan 1','Fan 2','Fan 3')]
    temps={sensor.get('Name'):sensor for sensor in data.get('Temperatures',[]) if sensor.get('Status',{}).get('State')!='Absent' and isinstance(sensor.get('ReadingCelsius'),(int,float))}
    if len(fans)!=3 or any(fan['health']!='OK' or not isinstance(fan['percent'],(int,float)) or fan['percent']<=0 for fan in fans):raise RuntimeError('Installed fan readings unavailable or unhealthy')
    if not temps:raise RuntimeError('Temperature readings unavailable')
    for sensor in temps.values():
        limits=[sensor[key]-5 for key in ('UpperThresholdCritical','UpperThresholdNonCritical') if isinstance(sensor.get(key),(int,float)) and sensor[key]>0]
        if sensor.get('Status',{}).get('Health') not in (None,'OK') or (limits and sensor['ReadingCelsius']>=min(limits)):raise RuntimeError('Temperature limit reached')
    if baseline and not set(baseline).issubset(temps):raise RuntimeError('Temperature sensor missing')
    return fans,{name:sensor['ReadingCelsius'] for name,sensor in temps.items()}

def validate(command,now):
    if not isinstance(command,dict) or set(command) not in ({'id','createdAt','output'},{'id','createdAt','output','mode'}):raise ValueError('Invalid request')
    if not isinstance(command['id'],str) or not 8<=len(command['id'])<=80:raise ValueError('Invalid request ID')
    if type(command['createdAt']) not in (int,float) or not now-15<=command['createdAt']<=now+5:raise ValueError('Request expired')
    mode=command.get('mode','automatic')
    if not isinstance(mode,str) or mode not in ('automatic','full'):raise ValueError('Invalid fan mode')
    if type(command['output']) is not int or not 100-MAX_ADJUSTMENT<=command['output']<=100:raise ValueError('Output must be 50–100% of automatic')
    if mode=='full' and command['output']!=100:raise ValueError('Full speed requires 100% output')
    return mode,100-command['output']

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
            current.update(boostActive=False,boostAvailable=True,boostRemaining=0)
        except Exception:
            failures.append('Full-speed restoration pending')
            current['boostAvailable']=False
    else:current.update(boostActive=False,boostAvailable=False,boostRemaining=0)
    # Always attempt both restoration paths, even when one is unavailable.
    try:
        request(0)
        current['adjustment']=0
    except Exception:failures.append('Automatic cooling restoration pending')
    if failures:
        current.update(error='; '.join(failures),ready=False,expiresAt=0)
    else:
        current.update(restoreNeeded=False,expiresAt=0,activatedAt=0,owner=None,baseline={},ready=True,error=reason)
    atomic(STATE,current)
    return current

def publish(current):
    public={key:current.get(key) for key in ['adjustment','expiresAt','ready','error','ack','fans','sampledAt','restoreNeeded','boostActive','boostAvailable']}
    public.update(version=1,updatedAt=time.time(),minimumOutput=50,maximumOutput=100,mode='full' if current.get('boostActive') else 'automatic')
    atomic(STATUS,public,0o644)

def read_command(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size>8192:raise ValueError('Invalid request file')
        with os.fdopen(fd,'r',closefd=False) as stream:return json.loads(stream.read(8193))
    finally:os.close(fd)

def start_boost(current):
    with FanChannel() as channel:
        channel.default()
        channel.boost(BOOST_SECONDS)
        result=channel.query()
        if not result['active'] or result['remaining']<=0:raise RuntimeError('Full speed was not confirmed')
    current.update(boostActive=True,boostAvailable=True,boostRemaining=result['remaining'])
    return current

def process(current,uid,command,ids,now):
    nonce=command.get('id') if isinstance(command,dict) else None
    try:
        if uid not in ids:raise ValueError('Administrator access required')
        mode,adjustment=validate(command,now)
        if mode=='full' or adjustment:
            if not current.get('ready') or current.get('restoreNeeded'):raise ValueError('Fan control unavailable')
            if mode=='full' and not current.get('boostAvailable'):raise ValueError('Full speed unavailable')
            if now-current.get('lastCommandAt',0)<2:raise ValueError('Please wait before changing again')
            fans,baseline=telemetry(request(),current.get('baseline'))
            started=current.get('activatedAt') or now
            current.update(restoreNeeded=True,ready=False,expiresAt=0,heartbeat=now)
            atomic(STATE,current)
            if mode=='full':
                request(0)
                current['adjustment']=0
                # Persist the possible override before issuing the command.
                current['boostActive']=True
                atomic(STATE,current)
                start_boost(current)
            else:
                if current.get('boostActive'):
                    with FanChannel() as channel:channel.default()
                    current.update(boostActive=False,boostRemaining=0)
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
    with FanChannel() as channel:result=channel.query()
    if not result['active']:raise RuntimeError('Full speed ended unexpectedly')
    current['boostRemaining']=result['remaining']
    if result['remaining']<120:
        current.update(restoreNeeded=True,ready=False)
        atomic(STATE,current)
        start_boost(current)
        current.update(restoreNeeded=False,ready=True)
    return current

def main(mode):
    global running
    signal.signal(signal.SIGTERM,lambda *args:stop())
    signal.signal(signal.SIGINT,lambda *args:stop())
    seen={};last_poll=0
    if mode=='restore':
        with locked():publish(restore(state()))
        return
    if mode=='controller':
        with locked():
            current=restore(state());current['heartbeat']=time.time();atomic(STATE,current);publish(current)
            for directory in USERS.iterdir():
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
                                current.update(fans=fans,sampledAt=time.time())
                                current=poll_boost(current)
                                current['ready']=not current.get('restoreNeeded') and time.time()-current.get('guardHeartbeat',0)<12
                            except Exception as error:
                                reason=str(error) if isinstance(error,RuntimeError) else 'Fan or temperature readings unavailable'
                                current=restore(current,reason)
                                current['ready']=False
                            last_poll=now
                        if time.time()-current.get('guardHeartbeat',0)>=12 and manual(current):current=restore(current,'Restoration guard unavailable')
                        for uid in sorted(ids):
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
    if len(sys.argv)!=2 or sys.argv[1] not in ('controller','guard','restore'):raise SystemExit('controller, guard or restore')
    main(sys.argv[1])
