"""Host CPU temperatures and bounded, monotonic fan curves."""
import math
from pathlib import Path

DEFAULT_CURVE = [[40,20],[50,30],[60,45],[70,65],[80,100]]
SETTINGS = Path('/var/lib/casaos/taelo-fan-settings/curve.json')

def validate_curve(points):
    if not isinstance(points,list) or not 2 <= len(points) <= 8:
        raise ValueError('Use 2–8 curve points')
    previous = None
    result = []
    for point in points:
        if not isinstance(point,list) or len(point)!=2 or any(type(v) is not int for v in point):
            raise ValueError('Curve points require whole degrees and percentages')
        temperature,output = point
        if not 20<=temperature<=85 or not 1<=output<=100:
            raise ValueError('Curve points must be 20–85°C and 1–100%')
        if previous and (temperature<=previous[0] or output<previous[1]):
            raise ValueError('Temperatures must increase and fan speeds cannot decrease')
        previous=point
        result.append(point[:])
    if result[-1][1]!=100:
        raise ValueError('The final curve point must reach 100%')
    return result

def cpu_temperatures(root=Path('/sys/class/hwmon')):
    sockets={}
    for hw in root.glob('*'):
        if (hw/'name').read_text().strip()!='coretemp':
            continue
        labels={p.stem.removesuffix('_label'):p.read_text().strip() for p in hw.glob('temp*_label')}
        package=next((key for key,label in labels.items() if label.startswith('Package id ')),None)
        if package is None:
            raise RuntimeError('CPU package sensor missing')
        sid=int(labels[package].split()[-1])
        values={}
        for key,label in labels.items():
            if not (label.startswith('Package id ') or label.startswith('Core ')):continue
            value=int((hw/(key+'_input')).read_text())/1000
            if not math.isfinite(value) or not 0<value<125:
                raise RuntimeError('CPU temperature reading invalid')
            alarm=hw/(key+'_crit_alarm')
            if alarm.exists() and int(alarm.read_text()):
                raise RuntimeError('CPU temperature alarm')
            values[key]=value
        if len(values)!=17:
            raise RuntimeError('CPU core sensors missing')
        critical=int((hw/(package+'_crit')).read_text())/1000
        maximum=max(values.values())
        if not 85<=critical<=125 or maximum>=critical-8:
            raise RuntimeError('CPU temperature limit reached')
        if sid in sockets:raise RuntimeError('Duplicate CPU package')
        sockets[sid]={'id':sid,'celsius':values[package],'maximum':maximum,'critical':critical}
    if set(sockets)!={0,1}:
        raise RuntimeError('Both CPU temperature sensors are required')
    return [sockets[k] for k in sorted(sockets)]

def curve_output(points,temperature):
    if not math.isfinite(temperature):
        raise ValueError('CPU temperature unavailable')
    if temperature<=points[0][0]:return points[0][1]
    for (a,low),(b,high) in zip(points,points[1:]):
        if temperature<=b:return math.ceil(low+(high-low)*(temperature-a)/(b-a))
    return 100

def next_target(current,desired,now):
    previous=current.get('targetPercent') or desired
    if desired>=previous:
        current.pop('fallSince',None)
        return desired if desired>=previous+2 or desired==100 else previous
    if desired>previous-3:
        current.pop('fallSince',None)
        return previous
    since=current.setdefault('fallSince',now)
    if now-since<10:return previous
    current['fallSince']=now
    return max(desired,previous-5)
