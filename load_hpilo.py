"""Load the distribution's stock driver, never a private module or force-load."""
import shutil
import subprocess
from pathlib import Path
from fan_config import require_model

def main():
    require_model()
    if not Path('/sys/module/hpilo').exists():
        modprobe = shutil.which('modprobe')
        if not modprobe:
            raise SystemExit('modprobe missing; install your distribution kernel tools')
        subprocess.run([modprobe, 'hpilo'], check=True, timeout=15)
    if not Path('/dev/hpilo/d0ccb0').is_char_device():
        raise SystemExit('Stock hpilo device unavailable; see docs/installation.md')

if __name__ == '__main__':
    main()
