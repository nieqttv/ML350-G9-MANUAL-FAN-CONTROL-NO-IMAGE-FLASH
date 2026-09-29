"""Run all tests without loading a real CHIF library or contacting iLO."""
import os
import runpy
import sys
import types
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
if sys.platform!='linux':
    print('Portable test mode: Linux flock, ownership and no-follow checks are skipped.')
    shim=types.ModuleType('fcntl')
    shim.LOCK_EX=2
    shim.flock=lambda *args:None
    sys.modules['fcntl']=shim
    # Only the test process receives these substitutes. Production remains Linux-only.
    if not hasattr(os,'O_NOFOLLOW'):os.O_NOFOLLOW=0
    if not hasattr(os,'O_NONBLOCK'):os.O_NONBLOCK=0
    if not hasattr(os,'geteuid'):os.geteuid=lambda:0

for name in ('test_fan_curve.py','test_ilo_chif.py','test_fan_control.py'):
    runpy.run_path(str(ROOT/'tests'/name),run_name='__main__')
suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_portable.py')
result=unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
