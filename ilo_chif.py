"""Narrow CHIF access to iLO 4's timed fan override and verified ML350 Gen9 PWM record."""
import ctypes as c
import json
import struct
import sys
import time
from pathlib import Path

ROOT = Path('/DATA/.taelo/zimaos-dashboard')

class FanChannel:
    def __enter__(self):
        self.lib = c.CDLL(str(ROOT / 'fan-research/ilorest_chif.so'))
        self.lib.ChifInitialize.argtypes = [c.c_void_p]
        self.lib.ChifInitialize.restype = c.c_uint32
        self.lib.ChifCreate.argtypes = [c.POINTER(c.c_void_p)]
        self.lib.ChifCreate.restype = c.c_uint32
        self.lib.ChifClose.argtypes = [c.c_void_p]
        self.lib.ChifClose.restype = c.c_uint32
        self.lib.ChifPacketExchangeSpecifyTimeout.argtypes = [c.c_void_p,c.c_void_p,c.c_void_p,c.c_uint32,c.c_uint32]
        self.lib.ChifPacketExchangeSpecifyTimeout.restype = c.c_uint32
        self.handle = c.c_void_p()
        self.sequence = 0
        if self.lib.ChifInitialize(None) or self.lib.ChifCreate(c.byref(self.handle)):
            raise RuntimeError('Local iLO channel unavailable')
        try:
            request = c.create_string_buffer(struct.pack('<HHHH',8,1,2,0))
            response = c.create_string_buffer(65536)
            rc = self.lib.ChifPacketExchangeSpecifyTimeout(self.handle,request,response,len(response),3000)
            raw = bytes(response)
            if rc or struct.unpack_from('<HHHH',raw) != (100,1,0x8002,0) or raw[8:12] != b'\0'*4 or raw[16:18] != bytes((82,2)):
                raise RuntimeError('Fan control requires verified iLO 4 firmware 2.82')
            self.sequence = 1
        except Exception:
            self.__exit__()
            raise
        return self

    def __exit__(self, *args):
        if self.handle.value:
            self.lib.ChifClose(self.handle)
            self.handle = c.c_void_p()

    def exchange(self, operation, duration=0):
        if type(operation) is not int or operation not in (0,1,2):
            raise ValueError('Unsupported fan operation')
        if type(duration) is not int or (operation == 1 and not 1 <= duration <= 3600) or (operation != 1 and duration != 0):
            raise ValueError('Invalid fan duration')
        self.sequence = self.sequence % 65535 + 1
        request = c.create_string_buffer(struct.pack('<HHHHHHII',20,self.sequence,0x8c,0,4,operation,duration,0))
        response = c.create_string_buffer(65536)
        rc = self.lib.ChifPacketExchangeSpecifyTimeout(self.handle,request,response,len(response),3000)
        raw = bytes(response)
        if rc or struct.unpack_from('<HHHH',raw) != (68,self.sequence,0x808c,0):
            raise RuntimeError('Local iLO fan response invalid')
        result, flags, remaining = struct.unpack_from('<III',raw,8)
        if result:
            raise RuntimeError('Local iLO fan request rejected')
        return {'active':bool(flags & 1),'remaining':remaining}


    def _platform(self, value=None):
        # Firmware 2.82, ML350 Gen9: record 80, type 3, Global PWM.
        # This helper cannot address any other record or write any other field.
        payload = bytearray(4024)
        struct.pack_into('<H',payload,4,6 if value is None else 5)
        if value is None:
            struct.pack_into('<H',payload,20,80)
        else:
            if type(value) is not int or not 3 <= value <= 255:
                raise ValueError('Invalid PWM value')
            struct.pack_into('<I',payload,8,5)
            struct.pack_into('<H',payload,22,1)
            payload[24:29] = struct.pack('<HHB',80,0x1063,value)
        self.sequence = self.sequence % 65535 + 1
        request = c.create_string_buffer(struct.pack('<HHHH',4032,self.sequence,0x200,0)+payload)
        response = c.create_string_buffer(65536)
        rc = self.lib.ChifPacketExchangeSpecifyTimeout(self.handle,request,response,len(response),3000)
        raw = bytes(response)
        if rc or struct.unpack_from('<HHHH',raw) != (4032,self.sequence,0x8200,0) or struct.unpack_from('<I',raw,8)[0]:
            raise RuntimeError('Fan speed request rejected')
        if value is None:
            record = raw[32:160]
            if struct.unpack_from('<I',raw,16)[0] != 128 or record[:4] != bytes((3,8,80,0)) or record[16:32] != b'Global PWM'+b'\0'*6:
                raise RuntimeError('Fan speed record does not match this server')
            return record

    def percentage(self):
        record = self._platform()
        return {'locked':bool(record[0x59]&1),'raw':record[0x63]}

    def set_percentage(self, percent):
        if type(percent) is not int or not 1 <= percent <= 100:
            raise ValueError('Fan speed must be 1–100%')
        timed = self.query()
        before = self.percentage()
        if not timed['active'] or timed['remaining'] <= 10 or not before['locked']:
            raise RuntimeError('Timed fan override unavailable')
        raw = (percent*255+50)//100
        self._platform(raw)
        after = self.percentage()
        if not after['locked'] or after['raw'] != raw:
            raise RuntimeError('Fan speed was not confirmed')
        return after

    def query(self):
        return self.exchange(0)

    def boost(self, seconds):
        return self.exchange(1,seconds)

    def default(self):
        self.exchange(2)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            current = self.query()
            if not current['active']:
                return current
            time.sleep(.2)
        raise RuntimeError('Local iLO fan restoration pending')

if __name__ == '__main__':
    if sys.argv[1:] not in (['query'],['default']):
        raise SystemExit('query or default')
    with FanChannel() as channel:
        print(json.dumps(channel.query() if sys.argv[1] == 'query' else channel.default()))

