"""Read-only iLO telemetry. Credentials stay on the server; no control endpoints."""
import base64,datetime,hashlib,http.client,json,ssl,sqlite3,threading,time
from pathlib import Path
ROOT=Path('/DATA/.taelo/zimaos-dashboard')
DB=Path('/media/nvme/taelo-dashboard-metrics/ilo-history.sqlite3')
OUT=Path('/run/taelo-system-stats/history.json')
def stamp(value):
 return datetime.datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
def atomic(path,data):
 tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,separators=(',',':')));tmp.chmod(0o644);tmp.replace(path)
class PowerHistory:
 def __init__(self,path=DB):
  self.db=sqlite3.connect(path)
  self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA wal_autocheckpoint=128')
  self.db.execute('PRAGMA journal_size_limit=1048576');self.db.execute('PRAGMA max_page_count=8192')
  self.db.execute('CREATE TABLE IF NOT EXISTS power (end REAL PRIMARY KEY,start REAL,watts REAL,peak REAL,source TEXT)')
  self.db.commit()
 def ingest(self,points,source,now,clock_offset=0):
  rows=sorted((stamp(p['Time'])-clock_offset,p) for p in points if 'Time' in p and isinstance(p.get('Average'),(int,float)))
  maximum=400 if source=='ilo_5min' else 15
  for (start,_),(end,p) in zip(rows,rows[1:]):
   if not 0<end-start<=maximum or end>now+30 or start<now-31*86400:continue
   if self.db.execute('SELECT 1 FROM power WHERE start<? AND end>? LIMIT 1',(end,start)).fetchone():continue
   self.db.execute('INSERT OR IGNORE INTO power VALUES (?,?,?,?,?)',(end,start,p['Average'],p.get('Peak',p['Average']),source))
  self.db.execute('DELETE FROM power WHERE end<?',(now-31*86400,));self.db.commit()
 def window(self,now,seconds,bucket):
  rows=self.db.execute('SELECT start,end,watts,peak FROM power WHERE end>? AND start<? ORDER BY end',(now-seconds,now)).fetchall()
  groups={};duration=joules=0;peak=None
  for start,end,watts,p in rows:
   start=max(start,now-seconds);end=min(end,now);dt=end-start
   if dt<=0:continue
   duration+=dt;joules+=watts*dt;peak=max(peak or 0,p)
   cursor=start
   while cursor<end:
    b=int(cursor//bucket)*bucket;stop=min(end,b+bucket);d=stop-cursor
    v=groups.setdefault(b,[0,0,0]);v[0]+=d;v[1]+=watts*d;v[2]=max(v[2],p);cursor=stop
  return {'start':now-seconds,'end':now,'bucketSeconds':bucket,
   'points':[{'t':max(now-seconds,t),'watts':round(j/d,1),'peakWatts':p,'observedSeconds':round(d,1)} for t,(d,j,p) in groups.items()],
   'observedSeconds':round(duration,1),'energyKwh':round(joules/3600000,5),
   'averageWatts':round(joules/duration,1) if duration else None,'peakWatts':peak}
 def publish(self,now,voltage=None,error=None,path=OUT):
  first=self.db.execute('SELECT MIN(start) FROM power').fetchone()[0]
  atomic(path,{'version':1,'updatedAt':now,'recordingSince':first,'scope':'whole_server','wholeServer':True,
   'source':'HPE iLO power meter','voltage':voltage,'error':error,
   'windows':{'24h':self.window(now,86400,300),'30d':self.window(now,30*86400,3600)}})
class Ilo:
 def __init__(self):
  self.value={'iloConnected':False,'model':'HP ProLiant ML350 Gen9'}
  self.positions=json.loads((ROOT/'temperature-map.json').read_text())['sensors']
  self.stop_event=threading.Event()
  self.thread=threading.Thread(target=self.run,name='ilo-readonly',daemon=True);self.thread.start()
 def get(self,path):
  # Certificate pin is checked on the SAME connection before sending credentials.
  conn=http.client.HTTPSConnection(self.config['host'],timeout=8,context=ssl._create_unverified_context())
  try:
   conn.connect()
   if hashlib.sha256(conn.sock.getpeercert(binary_form=True)).digest()!=self.pin:raise RuntimeError('iLO certificate changed')
   conn.request('GET',path,headers={'Authorization':self.auth,'Accept':'application/json'})
   r=conn.getresponse()
   if r.status!=200:raise RuntimeError('iLO HTTP '+str(r.status))
   return json.loads(r.read())
  finally:conn.close()
 def run(self):
  history=None
  try:
   self.config=json.loads((ROOT/'ilo-credentials.json').read_text())
   self.auth='Basic '+base64.b64encode((self.config['username']+':'+self.config['password']).encode()).decode()
   self.pin=hashlib.sha256(ssl.PEM_cert_to_DER_cert((ROOT/'ilo-certificate.pem').read_text())).digest()
   history=PowerHistory();last_history=0;boot=True;offset=0
   while not self.stop_event.is_set():
    started=time.time()
    try:
     power=self.get('/redfish/v1/Chassis/1/Power/')
     thermal=self.get('/redfish/v1/Chassis/1/Thermal/')
     supplies=[{'name':'PSU '+str(p.get('Oem',{}).get('Hp',{}).get('BayNumber',i+1)),
       'state':p.get('Status',{}).get('State'),'health':p.get('Status',{}).get('Health'),
       'voltage':p.get('LineInputVoltage'),'watts':p.get('LastPowerOutputWatts'),'capacityWatts':p.get('PowerCapacityWatts')}
       for i,p in enumerate(power.get('PowerSupplies',[]))]
     fans=[{'name':f.get('FanName',f.get('Name','Fan')),'percent':f.get('CurrentReading'),
       'state':f.get('Status',{}).get('State'),'health':f.get('Status',{}).get('Health')} for f in thermal.get('Fans',[])]
     temperatures=[{'name':t['Name'],'celsius':t.get('ReadingCelsius'),'health':t.get('Status',{}).get('Health'),
       'critical':t.get('UpperThresholdCritical'),'caution':t.get('UpperThresholdNonCritical'),**self.positions.get(t['Name'],{})} for t in thermal.get('Temperatures',[]) if t.get('Status',{}).get('State')!='Absent']
     self.value={'iloConnected':True,'sampledAt':time.time(),'host':self.config['host'],'firmware':'iLO 4 v2.82',
       'model':'HP ProLiant ML350 Gen9','clockCorrectionSeconds':offset,'wholeServerWatts':power.get('PowerConsumedWatts'),
       'powerMetrics':power.get('PowerMetrics',{}),'supplies':supplies,'fans':fans,'temperatures':temperatures}
     if started-last_history>=60:
      root=self.get('/redfish/v1/')
      offset=round((stamp(root['Time'])-time.time())/60)*60
      self.value=dict(self.value,clockCorrectionSeconds=offset)
      fast=self.get('/redfish/v1/Chassis/1/Power/FastPowerMeter/').get('PowerDetail',[])
      history.ingest(fast,'ilo_10sec',time.time(),offset)
      if boot:
       slow=self.get('/redfish/v1/Chassis/1/Power/PowerMeter/').get('PowerDetail',[])
       history.ingest(slow,'ilo_5min',time.time(),offset);boot=False
      history.publish(time.time(),next((p['voltage'] for p in supplies if p['voltage'] is not None),None));last_history=started
    except Exception as e:
     self.value=dict(self.value,iloConnected=False,error=type(e).__name__)
     if history:history.publish(time.time(),error='iLO readings unavailable; retained history is shown.')
    self.stop_event.wait(max(1,15-(time.time()-started)))
  except Exception as e:
   self.value=dict(self.value,iloConnected=False,error=type(e).__name__)
  finally:
   if history:history.db.close()
 def snapshot(self):
  return self.value.copy()
 def close(self):
  self.stop_event.set();self.thread.join(timeout=10)

