import importlib.machinery, importlib.util, tempfile, time, json, sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
loader=importlib.machinery.SourceFileLoader('fan_under_test',str(root/'fan_control.py'))
spec=importlib.util.spec_from_loader(loader.name,loader)
f=importlib.util.module_from_spec(spec);loader.exec_module(f)
events=[];hardware={'active':False,'remaining':0,'failDefault':False}
class Channel:
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def default(self):
  events.append('default')
  if hardware['failDefault']:raise RuntimeError('transport unavailable')
  hardware.update(active=False,remaining=0)
  return self.query()
 def boost(self,seconds):
  events.append(('boost',seconds));hardware.update(active=True,remaining=seconds)
 def set_percentage(self,percent):
  events.append(('percentage',percent));hardware['raw']=(percent*255+50)//100
 def percentage(self):return {'locked':hardware['active'],'raw':hardware.get('raw',255)}
 def query(self):return {key:hardware[key] for key in ('active','remaining')}
def request(adjustment=None):
 if adjustment is not None:events.append(('adjust',adjustment));return {}
 return {'Fans':[{'FanName':'Fan '+str(i),'CurrentReading':21,'Status':{'Health':'OK'}} for i in (1,2,3)],
 'Temperatures':[{'Name':'CPU','ReadingCelsius':45,'UpperThresholdCritical':90,'Status':{'State':'Enabled','Health':'OK'}}]}
f.FanChannel=Channel;f.request=request;f.chif_present=lambda:True
f.cpu_temperatures=lambda:[{'id':0,'celsius':55,'maximum':55,'critical':100},{'id':1,'celsius':45,'maximum':45,'critical':100}]
with tempfile.TemporaryDirectory() as td:
 f.STATE=Path(td)/'state.json';f.STATUS=Path(td)/'status.json';f.SETTINGS=Path(td)/'settings/curve.json'
 now=time.time()
 def cmd(mode='automatic',output=100):
  return {'id':'test-'+str(time.time_ns()),'createdAt':time.time(),'output':output,'mode':mode}
 current={'ready':True,'restoreNeeded':False,'boostAvailable':True,'heartbeat':now,'guardHeartbeat':now}
 current=f.process(current,'1',cmd('full'),{'1'},now)
 assert current['boostActive'] and current['ack']['ok'] and hardware['active']
 assert events.index(('adjust',0))<events.index(('boost',60))
 assert f.overdue(current,now+16)
 current['lastCommandAt']=0
 current=f.process(current,'1',cmd(output=80),{'1'},time.time())
 assert current['adjustment']==20 and not current['boostActive'] and not hardware['active']
 assert events[-2:]==['default',('adjust',20)]
 current=f.process(current,'1',cmd(),{'1'},time.time())
 assert not f.manual(current) and current['ready'] and current['ack']['ok']
 current['lastCommandAt']=0
 current=f.process(current,'1',cmd('full'),{'1'},time.time())
 hardware['remaining']=15
 f.poll_boost(current)
 assert hardware['remaining']==60 and current['boostActive'] and not current['restoreNeeded']
 for target in (1,50,75,100):
  current['lastCommandAt']=0
  current=f.process(current,'1',cmd('percentage',target),{'1'},time.time())
  assert current['ack']['ok'] and current['targetPercent']==target
  assert hardware['raw']==(target*255+50)//100
  hardware['remaining']=15
  f.poll_boost(current)
  assert hardware['raw']==(target*255+50)//100 and hardware['remaining']==60
 current['lastCommandAt']=0
 curve=[[40,20],[60,50],[80,100]]
 current=f.process(current,'1',{'id':'curve-test-123','createdAt':time.time(),'mode':'curve','curve':curve},{'1'},time.time())
 assert current['curveActive'] and current['targetPercent']==43 and current['ack']['ok']
 assert f.saved_curve()==curve
 f.cpu_temperatures=lambda:[{'id':0,'celsius':75,'maximum':75,'critical':100},{'id':1,'celsius':45,'maximum':45,'critical':100}]
 f.poll_curve(current)
 assert current['targetPercent']==88
 hardware['remaining']=15;f.poll_boost(current)
 assert hardware['raw']==(88*255+50)//100
 hardware['raw']=0
 try:f.poll_boost(current);raise AssertionError('readback drift ignored')
 except RuntimeError:pass
 hardware['failDefault']=True
 restored=f.restore(current)
 assert restored['restoreNeeded'] and not restored['ready'] and restored['boostActive']
 assert events[-1]==('adjust',0), 'REST Default must still run when CHIF fails'
 hardware['failDefault']=False
 restored=f.restore(restored)
 assert not restored['restoreNeeded'] and not restored['boostActive']
 for bad in [cmd('full',50),cmd('unsupported'),cmd(output=200),cmd(output=True),cmd('percentage',0),cmd('percentage',101),cmd('percentage',50.5)]:
  try:f.validate(bad,time.time());raise AssertionError('bad request accepted')
  except ValueError:pass
 restored=f.process(restored,'9',cmd('full'),{'1'},time.time())
 assert not restored['ack']['ok'] and not hardware['active']
 f.publish(restored)
 public=json.loads(f.STATUS.read_text())
 assert public['mode']=='automatic' and 'baseline' not in public and 'owner' not in public
 # Thermal safety and missing sensors must reject continued manual control.
 hot=request();hot['Temperatures'][0]['ReadingCelsius']=86
 for readings,baseline in [(hot,None),(request(),{'missing':20})]:
  try:f.telemetry(readings,baseline);raise AssertionError('unsafe telemetry accepted')
  except RuntimeError:pass
print('PASS percentage targets, quantization, renewal, drift, restoration, faults, strict bounds and admin checks')

