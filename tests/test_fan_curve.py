import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fan_curve import *

for bad in ([],[[40,20],[40,100]],[[40,50],[60,20],[80,100]],[[40,20],[90,100]],[[40,20],[80,90]],[[True,20],[80,100]]):
    try:validate_curve(bad);raise AssertionError('bad curve accepted')
    except ValueError:pass
points=validate_curve([[40,20],[60,50],[80,100]])
assert [curve_output(points,t) for t in (20,40,50,60,70,80,95)]==[20,20,35,50,75,100,100]
current={'targetPercent':60}
assert next_target(current,30,0)==60
assert next_target(current,30,9)==60
assert next_target(current,30,10)==55
assert next_target(current,90,11)==90 and 'fallSince' not in current
assert next_target(current,100,12)==100
with tempfile.TemporaryDirectory() as td:
    root=Path(td)
    for sid in (0,1):
        hw=root/str(sid);hw.mkdir();(hw/'name').write_text('coretemp')
        for index in range(17):
            label='Package id '+str(sid) if index==0 else 'Core '+str(index-1)
            stem=hw/('temp'+str(index+1))
            Path(str(stem)+'_label').write_text(label)
            Path(str(stem)+'_input').write_text(str((60 if sid==0 else 50)*1000))
        (hw/'temp1_crit').write_text('100000')
    readings=cpu_temperatures(root)
    assert [r['maximum'] for r in readings]==[60,50]
    (root/'1/temp2_input').write_text('75000')
    assert cpu_temperatures(root)[1]['maximum']==75
    (root/'1/temp2_input').write_text('95000')
    try:cpu_temperatures(root);raise AssertionError('hot CPU accepted')
    except RuntimeError:pass
    (root/'1/temp2_input').unlink()
    try:cpu_temperatures(root);raise AssertionError('missing sensor accepted')
    except OSError:pass
print('PASS monotonic curves, interpolation, fast rise/slow fall, dual CPU and missing/critical sensor protection')
