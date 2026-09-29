import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fan_curve import *

for bad in ([],[[40,20],[40,100]],[[40,50],[60,20],[80,100]],[[40,20],[90,100]],[[True,20],[80,100]]):
    try:validate_curve(bad);raise AssertionError('bad curve accepted')
    except ValueError:pass
points=validate_curve([[40,20],[60,50],[80,100]])
assert [curve_output(points,t) for t in (20,40,50,60,70,80,95)]==[20,20,35,50,75,100,100]
current={'targetPercent':60}
assert next_target(current,30,0)==30
assert next_target(current,30,9)==30
assert next_target(current,30,10)==30
assert next_target(current,90,11)==90
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
    readings=cpu_temperatures(root)
    assert not cooling_protection(readings)
    (root/'1/temp2_input').write_text('98000')
    assert cooling_protection(cpu_temperatures(root))
    (root/'1/temp2_input').unlink()
    try:cpu_temperatures(root);raise AssertionError('missing sensor accepted')
    except OSError:pass
quiet=validate_curve([[40,10],[50,15],[60,20],[70,27],[85,40]])
assert [curve_output(quiet,t) for t in (40,50,60,62,70,85,88)]==[10,15,20,22,27,40,40]
assert not cooling_protection([{'maximum':85,'critical':93}])
assert cooling_protection([{'maximum':90,'critical':93}])
assert cooling_protection([{'maximum':86,'critical':93}],True)
assert not cooling_protection([{'maximum':84,'critical':93}],True)
print('PASS exact quiet curve, endpoint holding, direct response, dual CPU and separate thermal protection')
