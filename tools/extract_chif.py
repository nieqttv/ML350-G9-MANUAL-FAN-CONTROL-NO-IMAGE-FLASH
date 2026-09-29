"""Extract the verified HPE wheel locally; never downloads or executes its code."""
import argparse
import hashlib
import io
import os
import sys
import zipfile
from pathlib import Path

WHEEL_SHA256='bbe31c050f7ac79a8cf2fb48163655da5a4e9a4fe2ab88a05430639372624a9d'

def extract(wheel,destination,accepted):
    if not accepted:raise ValueError('Review HPE CHIF terms and pass --accept-hpe-terms only if you accept them')
    data=wheel.read_bytes()
    if hashlib.sha256(data).hexdigest()!=WHEEL_SHA256:raise ValueError('Wheel checksum does not match verified ilorest 7.4.0.0')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members=[m for m in archive.infolist() if m.filename=='ilorest/chiflibrary/ilorest_chif.so']
        if len(members)!=1 or members[0].file_size>16*1024*1024:raise ValueError('Unexpected CHIF library layout')
        library=archive.read(members[0])
    if not library.startswith(b'\x7fELF\x02\x01') or library[18:20]!=b'\x3e\x00':
        raise ValueError('Expected a Linux x86-64 CHIF library')
    if hashlib.sha256(library).hexdigest()!='33620a23d3356a9e3d7140f1bce9b91df515cbbed86a05514aff6a49a58673d0':
        raise ValueError('CHIF library checksum mismatch')
    destination.mkdir(parents=True,exist_ok=True)
    path=destination/'ilorest_chif.so'
    # Refuse overwrites and links. Keep source wheel/notices with your private copy.
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o644)
    with os.fdopen(fd,'wb') as stream:stream.write(library)
    return hashlib.sha256(library).hexdigest()

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('wheel',type=Path)
    p.add_argument('--destination',type=Path,default=Path('chif'))
    p.add_argument('--accept-hpe-terms',action='store_true')
    args=p.parse_args(argv)
    try:
        digest=extract(args.wheel,args.destination,args.accept_hpe_terms)
        print('Extracted ilorest_chif.so; SHA256 '+digest)
        return 0
    except (OSError,ValueError,zipfile.BadZipFile) as error:
        print(str(error),file=sys.stderr)
        return 1

if __name__=='__main__':
    raise SystemExit(main())
