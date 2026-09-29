"""Portable paths and root-owned configuration; no implicit legacy migration."""
import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath

CONFIG = Path(os.environ.get('ML350_FAN_CONFIG', '/etc/ml350-fan-control/config.json'))
DEFAULTS = {
    'credentials': '/etc/ml350-fan-control/ilo-credentials.json',
    'certificate': '/etc/ml350-fan-control/ilo-certificate.pem',
    'chif_library': '/usr/local/lib/ml350-fan-control/ilorest_chif.so',
    'runtime': '/run/ml350-fan-control',
    'settings': '/var/lib/ml350-fan-control/curve.json',
    'installed_fans': [],
    'casaos': False,
    'casaos_users': '/var/lib/casaos',
}

def secure_read(path):
    """Open without following links and check the opened file, not a prior stat."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_size > 65536:
            raise ValueError('Configuration and credentials must be root-owned regular files, mode 600')
        with os.fdopen(fd, 'r', closefd=False) as stream:
            return stream.read(65537)
    finally:
        os.close(fd)

def load_config(path=CONFIG):
    value = json.loads(secure_read(path))
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError('Unknown configuration fields')
    cfg = dict(DEFAULTS, **value)
    for key in ('credentials', 'certificate', 'chif_library', 'runtime', 'settings', 'casaos_users'):
        if not isinstance(cfg[key], str) or not PurePosixPath(cfg[key]).is_absolute() or '..' in PurePosixPath(cfg[key]).parts:
            raise ValueError('Configuration paths must be absolute')
    fans = cfg['installed_fans']
    if not isinstance(fans, list) or not 1 <= len(fans) <= 8 or any(
        not isinstance(name, str) or not re.fullmatch(r'Fan [1-8]', name) for name in fans
    ) or len(set(fans)) != len(fans):
        raise ValueError('List every physically installed fan using its iLO name')
    if type(cfg['casaos']) is not bool:
        raise ValueError('casaos must be true or false')
    return cfg

def credentials(cfg):
    value = json.loads(secure_read(cfg['credentials']))
    if not isinstance(value, dict) or set(value) != {'host', 'username', 'password'} or any(
        not isinstance(v, str) or not v for v in value.values()
    ):
        raise ValueError('Credentials require host, username and password')
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', value['host']):
        raise ValueError('Use an iLO DNS name or IPv4 address without a scheme or port')
    if ':' in value['username'] or any(c in value['username'] for c in '\r\n'):
        raise ValueError('Invalid iLO username')
    return value

def require_model(root=Path('/sys/class/dmi/id')):
    model = (root / 'product_name').read_text().strip()
    if model not in ('ProLiant ML350 Gen9', 'HP ProLiant ML350 Gen9', 'HPE ProLiant ML350 Gen9'):
        raise RuntimeError('Only HP/HPE ProLiant ML350 Gen9 is verified')
    return model

CHIF_SHA256='33620a23d3356a9e3d7140f1bce9b91df515cbbed86a05514aff6a49a58673d0'

def verify_library(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or info.st_size>16*1024*1024:
            raise RuntimeError('CHIF library must be a root-owned regular file, not writable by others')
        with os.fdopen(fd,'rb',closefd=False) as stream:
            digest=hashlib.sha256(stream.read(16*1024*1024+1)).hexdigest()
        if digest!=CHIF_SHA256:raise RuntimeError('CHIF library does not match verified ilorest 7.4.0.0')
    finally:
        os.close(fd)

def library_path():
    path=Path(load_config()['chif_library'])
    verify_library(path)
    return path
