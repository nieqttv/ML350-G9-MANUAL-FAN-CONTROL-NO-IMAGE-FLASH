import ctypes as c
import struct
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ilo_chif import FanChannel

class Transport:
    def __init__(self):
        self.requests=[]
        self.record=bytearray(128)
        self.record[:4]=bytes((3,8,80,0))
        self.record[16:32]=b'Global PWM'+b'\0'*6
        self.record[0x59]=1
        self.record[0x63]=255
        self.reject=False
    def ChifPacketExchangeSpecifyTimeout(self,handle,request,response,size,timeout):
        raw=bytes(request);length,seq,cmd,service=struct.unpack_from('<HHHH',raw)
        assert (length,cmd,service)==(4032,0x200,0)
        assert timeout==3000
        self.requests.append(raw[:length])
        op=struct.unpack_from('<H',raw,12)[0]
        result=bytearray(4032)
        struct.pack_into('<HHHH',result,0,4032,seq,0x8200,0)
        if op==6:
            assert struct.unpack_from('<H',raw,28)[0]==80
            struct.pack_into('<I',result,16,128)
            result[32:160]=self.record
        else:
            assert op==5
            assert struct.unpack_from('<I',raw,16)[0]==5
            assert struct.unpack_from('<H',raw,30)[0]==1
            rid,field,value=struct.unpack_from('<HHB',raw,32)
            assert (rid,field)==(80,0x1063)
            if not self.reject:self.record[0x63]=value
            else:struct.pack_into('<I',result,8,8)
        c.memmove(response,bytes(result),len(result))
        return 0

ch=FanChannel();ch.lib=Transport();ch.handle=c.c_void_p(1);ch.sequence=1
ch.query=lambda:{'active':True,'remaining':30}
for value in (1,25,50,75,100):
    result=ch.set_percentage(value)
    assert result=={'locked':True,'raw':(value*255+99)//100}
for value in (0,101,True,50.5,'50'):
    before=len(ch.lib.requests)
    try:ch.set_percentage(value);raise AssertionError('invalid target accepted')
    except ValueError:pass
    assert len(ch.lib.requests)==before
for query in ({'active':False,'remaining':0},{'active':True,'remaining':5}):
    ch.query=lambda q=query:q
    before=sum(struct.unpack_from('<H',r,12)[0]==5 for r in ch.lib.requests)
    try:ch.set_percentage(50);raise AssertionError('unsafe override accepted')
    except RuntimeError:pass
    assert sum(struct.unpack_from('<H',r,12)[0]==5 for r in ch.lib.requests)==before
ch.query=lambda:{'active':True,'remaining':30}
ch.lib.record[16]=ord('X')
try:ch.set_percentage(50);raise AssertionError('foreign record accepted')
except RuntimeError:pass
ch.lib.record[16]=ord('G');ch.lib.reject=True
try:ch.set_percentage(50);raise AssertionError('write rejection ignored')
except RuntimeError:pass
print('PASS exact packet layout, narrow field writes, bounds, quantization, timed override and foreign-record rejection')
