#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Real lwIP ACKs with virtual RTT, finite RX FIFO and concurrent CPU draining.

The peer is already established and has a fixed 10-segment congestion window;
this isolates receive-window effects, not congestion control or hardware speed.
"""
import ctypes as C
import heapq
import json
import re
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


def simulate(library, rtt_us, service_us, target=1460*200):
    lib=C.CDLL(str(library))
    lib.packet.argtypes=[C.c_uint32,C.c_uint16]
    lib.metric.restype=C.c_uint32
    lib.setup()
    events=[]; serial=0; now=0; wire_free=0; cpu_free=0; fifo=0; drops=0; sent=0
    next_seq=1; ack=1; window=lib.metric(4); last_ack_event=0
    # Include Ethernet preamble/IFG on the wire and per-frame XRAM headers.
    wire_us=(1518+8+12)*8/1000
    slot=(1518+16+7)&~7
    capacity=lib.metric(5)-8
    delivered_at=0

    def event(at,kind,value):
        nonlocal serial
        serial+=1;heapq.heappush(events,(at,serial,kind,value))

    def observe_ack():
        nonlocal last_ack_event
        count=lib.metric(3)
        if count!=last_ack_event:
            event(now+rtt_us/2,'ack',(lib.metric(1),lib.metric(2)))
            last_ack_event=count

    def send():
        nonlocal next_seq,wire_free,sent
        edge=min(ack+window,ack+10*1460,target+1)
        while next_seq+1460<=edge:
            wire_free=max(wire_free,now)+wire_us
            event(wire_free+rtt_us/2,'arrival',next_seq)
            next_seq+=1460;sent+=1

    send();event(250000,'timer',None)
    while events and now<5000000:
        now,_,kind,value=heapq.heappop(events)
        if kind=='arrival':
            if fifo+slot>capacity:
                drops+=1
                continue
            cpu_free=max(cpu_free,now)+service_us
            event(cpu_free,'consume',value)
            fifo+=slot
        elif kind=='consume':
            fifo-=slot
            lib.packet(value,1460)
            observe_ack()
            if lib.metric(0)==target:
                delivered_at=now;break
        elif kind=='ack':
            if value[0]>=ack:ack,window=value
            send()
        elif kind=='timer':
            lib.advance(int(now/1000));observe_ack();event(now+250000,'timer',None)
        if drops:break  # No invented retransmission/congestion-control model.
    return {'rtt_us':rtt_us,'cpu_us_per_frame':service_us,'window':lib.metric(4),
            'received':lib.metric(0),'acks':lib.metric(3),'sent':sent,'drops':drops,
            'elapsed_us':delivered_at or now,
            'model_MB_s':target/delivered_at if delivered_at else None}


class UploadWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results={}
        source=ROOT/'sources/uboot-an758x/lib/lwip/lwip/src'
        opts=(ROOT/'build/u-boot/lib/lwip/u-boot/lwipopts.h').read_text()
        ni=(ROOT/'build/u-boot/board/realtek/tyfza1/vendor/eth_ni.h').read_text()
        top=int(re.search(r'#define RX_TOP_ADDR (0x[0-9A-Fa-f]+)',ni)[1],16)
        base=int(re.search(r'#define RX_BASE_ADDR (0x[0-9A-Fa-f]+)',ni)[1],16)
        config=(ROOT/'build/tyfza1/.config').read_text()
        window=int(re.search(r'^CONFIG_LWIP_TCP_WND=(\d+)',config,re.M)[1])
        current_scale=int(re.search(r'#define TCP_RCV_SCALE\s+(\S+)',opts)[1],0)
        for name,wnd,scale in [('small',2920,0),('current',window,current_scale)]:
            work=ROOT/f'build/tcp-review-{name}'
            (work/'arch').mkdir(parents=True,exist_ok=True);(work/'linux').mkdir(exist_ok=True)
            (work/'arch/cc.h').write_text('#include <stdio.h>\n#include <stdlib.h>\n#include <stdint.h>\n')
            (work/'linux/kconfig.h').write_text('''#define CONFIG_IS_ENABLED(x) 0
#define CONFIG_PROT_TCP_LWIP 1
#define CONFIG_PROT_TCP_SACK_LWIP 1
#define CONFIG_CMD_HTTPD 1
''' + f'#define CONFIG_LWIP_TCP_WND {wnd}\n#define NI_TEST_RX_BYTES {(top-base+1)*8}\n')
            (work/'lwipopts.h').write_text(re.sub(r'(#define TCP_RCV_SCALE\s+)\S+',rf'\g<1>{scale}',opts))
            files=list((source/'core').glob('*.c'))+list((source/'core/ipv4').glob('*.c'))+[source/'netif/ethernet.c']
            library=work/'upload.so'
            subprocess.run(['cc','-O2','-shared','-fPIC','-I'+str(work),'-I'+str(source/'include'),
                            str(ROOT/'tests/tcp_upload_io.c'),*[str(p) for p in files],'-o',str(library)],check=True)
            # A fresh process gives each scenario an independent real lwIP heap/state.
            cls.results[name]=[json.loads(subprocess.check_output(
                [sys.executable,__file__,'simulate',str(library),str(rtt),str(cpu)],text=True))
                for rtt,cpu in [(100,2),(1000,2),(3000,2),(10000,2),(100,100)]]
        (ROOT/'build/tcp-upload-results.json').write_text(json.dumps(cls.results,indent=2)+'\n')

    def test_two_mss_window_limits_throughput_despite_no_fifo_loss(self):
        for small,current in zip(self.results['small'][:4],self.results['current'][:4]):
            self.assertEqual(small['drops'],0);self.assertEqual(current['drops'],0)
            self.assertEqual(small['received'],292000);self.assertEqual(current['received'],292000)
            self.assertGreater(current['model_MB_s'],small['model_MB_s']*3)
        self.assertLess(self.results['small'][2]['model_MB_s'],1.1)

    def test_small_window_increases_ack_work(self):
        self.assertGreater(self.results['small'][0]['acks'],self.results['current'][0]['acks'])

    def test_slow_cpu_still_exposes_fifo_limit_with_large_window(self):
        self.assertGreater(self.results['current'][-1]['drops'],0)

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='simulate':
        print(json.dumps(simulate(Path(sys.argv[2]),float(sys.argv[3]),float(sys.argv[4]))))
    else:unittest.main()
