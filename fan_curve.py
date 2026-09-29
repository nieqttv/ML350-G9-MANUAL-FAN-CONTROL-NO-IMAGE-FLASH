"""Host CPU temperatures and bounded, monotonic fan curves."""
import math
from pathlib import Path

DEFAULT_CURVE = [[40,20],[50,30],[60,45],[70,65],[80,100]]
SETTINGS = Path('/var/lib/ml350-fan-control/curve.json')

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
    return result

def cpu_topology(root=Path('/sys/devices/system/cpu')):
    sockets={}
    for cpu in root.glob('cpu[0-9]*'):
        online=cpu/'online'
        if online.exists() and online.read_text().strip()=='0':continue
        sid=int((cpu/'topology/physical_package_id').read_text())
        core=int((cpu/'topology/core_id').read_text())
        sockets.setdefault(sid,set()).add(core)
    if not sockets or len(sockets)>2:raise RuntimeError('One or two CPU packages are required')
    return sockets

def cpu_temperatures(root=Path('/sys/class/hwmon'),topology=None):
    if topology is None and root==Path('/sys/class/hwmon'):
        topology=cpu_topology()
    sockets={}
    found_cores={}
    for hw in root.glob('*'):
        if not (hw/'name').exists() or (hw/'name').read_text().strip()!='coretemp':
            continue
        labels={p.stem.removesuffix('_label'):p.read_text().strip() for p in hw.glob('temp*_label')}
        packages=[key for key,label in labels.items() if label.startswith('Package id ')]
        package=packages[0] if len(packages)==1 else None
        if package is None:
            raise RuntimeError('CPU package sensor missing')
        sid=int(labels[package].split()[-1])
        values={}
        alarm_active=False
        for key,label in labels.items():
            if not (label.startswith('Package id ') or label.startswith('Core ')):continue
            value=int((hw/(key+'_input')).read_text())/1000
            if not math.isfinite(value) or not 0<value<125:
                raise RuntimeError('CPU temperature reading invalid')
            alarm=hw/(key+'_crit_alarm')
            if alarm.exists() and int(alarm.read_text()):
                alarm_active=True
            values[key]=value
        cores=[int(label.split()[-1]) for label in labels.values() if label.startswith('Core ')]
        if not cores or len(cores)!=len(set(cores)):
            raise RuntimeError('CPU core sensors missing or duplicated')
        found_cores[sid]=set(cores)
        critical=int((hw/(package+'_crit')).read_text())/1000
        maximum=max(values.values())
        if not 85<=critical<=125:
            raise RuntimeError('CPU critical threshold unavailable')
        if sid in sockets:raise RuntimeError('Duplicate CPU package')
        sockets[sid]={'id':sid,'celsius':values[package],'maximum':maximum,'critical':critical,'alarm':alarm_active}
    if not sockets or len(sockets)>2 or (topology is not None and found_cores!=topology):
        raise RuntimeError('CPU package/core sensors do not match the online CPU topology')
    return [sockets[k] for k in sorted(sockets)]

def curve_output(points,temperature):
    if not math.isfinite(temperature):
        raise ValueError('CPU temperature unavailable')
    if temperature<=points[0][0]:return points[0][1]
    for (a,low),(b,high) in zip(points,points[1:]):
        if temperature<=b:return math.ceil(low+(high-low)*(temperature-a)/(b-a))
    return points[-1][1]

def cooling_protection(cpus,was_active=False):
    margin=8 if was_active else 3
    return any(c.get('alarm') or c['maximum']>=c['critical']-margin for c in cpus)

def next_target(current,desired,now):
    # The saved curve is authoritative; no hidden delay or downward rate limit.
    return desired

