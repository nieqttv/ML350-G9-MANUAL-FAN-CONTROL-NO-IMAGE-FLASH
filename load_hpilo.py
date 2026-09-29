"""Load the stock hpilo module only for the kernel it was built against."""
import gzip, hashlib, json, os, subprocess
from pathlib import Path
ROOT=Path('/DATA/.taelo/zimaos-dashboard/hpilo-module')
manifest=json.loads((ROOT/'manifest.json').read_text())
if os.uname().release!=manifest['kernel']:
    raise SystemExit('hpilo kernel version changed; rebuild required')
if hashlib.sha256(gzip.decompress(Path('/proc/config.gz').read_bytes())).hexdigest()!=manifest['configSha256']:
    raise SystemExit('hpilo kernel configuration changed; rebuild required')
if hashlib.sha256((ROOT/'hpilo.ko').read_bytes()).hexdigest()!=manifest['moduleSha256']:
    raise SystemExit('hpilo module checksum mismatch')
if not Path('/sys/module/hpilo').exists():
    subprocess.run(['/usr/bin/insmod',str(ROOT/'hpilo.ko')],check=True,timeout=15)
if not Path('/dev/hpilo/d0ccb0').exists():
    raise SystemExit('Local iLO device unavailable')
