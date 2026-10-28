#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Replay an upload sender burst against real lwIP and the documented RX capacity."""
import json
import re
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]

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
        window=int(next(s.split('=')[1] for s in config.splitlines() if s.startswith('CONFIG_LWIP_TCP_WND=')))
        for name,wnd,scale in [('old',3000000,7),('current',window,0)]:
            work=ROOT/f'build/tcp-upload-{name}';(work/'arch').mkdir(parents=True,exist_ok=True);(work/'linux').mkdir(exist_ok=True)
            (work/'arch/cc.h').write_text('#include <stdio.h>\n#include <stdlib.h>\n#include <stdint.h>\n')
            (work/'linux/kconfig.h').write_text('''#define CONFIG_IS_ENABLED(x) 0
#define CONFIG_PROT_TCP_LWIP 1
#define CONFIG_PROT_TCP_SACK_LWIP 1
#define CONFIG_CMD_HTTPD 1
''' + f'#define CONFIG_LWIP_TCP_WND {wnd}\n#define NI_TEST_RX_BYTES {(top-base+1)*8}\n')
            (work/'lwipopts.h').write_text(opts.replace('#define TCP_RCV_SCALE                   0',f'#define TCP_RCV_SCALE                   {scale}'))
            files=list((source/'core').glob('*.c'))+list((source/'core/ipv4').glob('*.c'))+[source/'netif/ethernet.c']
            exe=work/'upload'
            subprocess.run(['cc','-O2','-I'+str(work),'-I'+str(source/'include'),str(ROOT/'tests/tcp_upload_io.c'),*[str(p) for p in files],'-o',str(exe)],check=True,stdout=subprocess.PIPE)
            cls.results[name]=json.loads(subprocess.check_output([str(exe)],text=True).strip().splitlines()[-1])
        (ROOT/'build/tcp-upload-results.json').write_text(json.dumps(cls.results,indent=2)+'\n')

    def test_old_window_reproduces_queue_overflow(self):
        self.assertGreater(self.results['old']['dropped'],0)

    def test_bounded_window_delivers_repeated_bursts_without_loss_or_delayed_ack_stall(self):
        r=self.results['current']
        self.assertEqual(r['dropped'],0)
        self.assertGreaterEqual(r['received'],292000)
        self.assertEqual(r['ack'],r['received']+1)

if __name__=='__main__':unittest.main()
