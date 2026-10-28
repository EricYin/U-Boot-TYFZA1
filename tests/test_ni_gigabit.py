#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare internal MAC register writes to the pinned Realtek implementation."""
import ctypes as C
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
class GigabitMacTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        work=ROOT/'build/gigabit-mac-test';work.mkdir(exist_ok=True,parents=True)
        vendor=ROOT/'sources/realtek-gpl/bootloader/u-boot-2022.10'
        (work/'registers.h').write_bytes((vendor/'arch/arm/include/asm/arch-taurus/registers.h').read_bytes())
        (work/'ca_types.h').write_text('#include <stdint.h>\ntypedef uint32_t ca_uint32_t;\n')
        header=(vendor/'board/realtek_10G_PON/common/eth_ni.h').read_text()
        definitions='\n'.join(x for x in header.splitlines() if x.startswith('#define GE_MAC_INTF_') or x.startswith('#define NI_PORT_'))
        native=(ROOT/'overlay/board/realtek/tyfza1/ni-gigabit.c').read_text()
        native='\n'.join(x for x in native.splitlines() if not x.startswith('#include'))
        original=(vendor/'board/realtek_10G_PON/common/eth_ni_taurus.c').read_text()
        original=original[original.index('int aal_mode_sync'):].replace('aal_mode_sync(', 'stock_mode(').replace('aal_set_active_port(', 'stock_port(')
        pre=r'''
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
#include "registers.h"
#define SPEED_10 10
#define SPEED_100 100
#define SPEED_1000 1000
#define DUPLEX_HALF 0
#define AAL_SDS_SPEED_DEFAULT 0
#define AAL_SDS_MODE_RGMII 1
struct phy_device {int speed,duplex;};
typedef int aal_sds_mode_t;
typedef int aal_sds_speed_t;
static int is_qxgmii;
static unsigned int seed, count;static uintptr_t addresses[8];static uint32_t values[8];
static uint32_t read_reg(uintptr_t a){for(unsigned int i=count;i>0;i--)if(addresses[i-1]==a)return values[i-1];return seed;}
static void write_reg(uint32_t v,uintptr_t a){if(count>=8)__builtin_trap();addresses[count]=a;values[count++]=v;}
#define CORTINA_CA_REG_READ(a) read_reg(a)
#define CORTINA_CA_REG_WRITE(v,a) write_reg(v,a)
static int _to_aal_speed(int s){return s;}
static int _to_qx_ability_speed(int s){return s;}
static void ca_ni_p6_qxgmii_port_macForceAbility_set(int p,int s){(void)p;(void)s;__builtin_trap();}
static int taurus_aal_sds_mode_set(int p,int m,int s){(void)p;(void)m;(void)s;__builtin_trap();}
'''
        tail=r'''
int run(unsigned int value,unsigned int port,int speed,int duplex,int stock){
 seed=value;count=0;struct phy_device phy={speed,duplex};
 int ret=stock?stock_mode(port,0,&phy):aal_mode_sync(port,0,&phy);
 if(!ret){if(stock)stock_port(port);else aal_set_active_port(port);}return ret;
}
unsigned int nwrite(void){return count;}
uintptr_t addr(unsigned int i){return addresses[i];}
uint32_t val(unsigned int i){return values[i];}
'''
        (work/'test.c').write_text(pre+definitions+'\n'+native+'\n'+original+tail)
        subprocess.run(['cc','-shared','-fPIC','-O2','-I'+str(work),str(work/'test.c'),'-o',str(work/'test.so')],check=True)
        cls.lib=C.CDLL(str(work/'test.so'));cls.lib.addr.restype=C.c_size_t;cls.lib.val.restype=C.c_uint

    def trace(self):return [(self.lib.addr(i),self.lib.val(i)) for i in range(self.lib.nwrite())]

    def test_all_internal_ports_speeds_and_duplex_match_vendor(self):
        for port in range(4):
            for speed in (10,100,1000):
                for duplex in (0,1):
                    for seed in (0,0xa5a5a5a5,0xffffffff):
                        self.assertEqual(self.lib.run(seed,port,speed,duplex,1),0);expected=self.trace()
                        self.assertEqual(self.lib.run(seed,port,speed,duplex,0),0)
                        self.assertEqual(self.trace(),expected)
                        self.assertEqual(len(expected),4)

    def test_external_ports_and_2500_are_rejected_without_writes(self):
        for port,speed in [(4,1000),(5,1000),(6,1000),(0,2500)]:
            self.assertEqual(self.lib.run(0,port,speed,1,0),-22)
            self.assertEqual(self.lib.nwrite(),0)

if __name__=='__main__':unittest.main()
