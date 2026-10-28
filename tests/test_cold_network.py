#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute real NI reset and generic PHY configuration with injected I/O errors."""
import ctypes as C
from pathlib import Path
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
def function(text, signature):
    at=text.index(signature);return text[at:text.index('\n}',at)+2]
class ColdNetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        work=ROOT/'build/cold-network-test';work.mkdir(parents=True,exist_ok=True)
        phy=(ROOT/'build/u-boot/drivers/net/phy/phy.c').read_text()
        ni=(ROOT/'build/u-boot/board/realtek/tyfza1/vendor/eth_ni.c').read_text()
        reset=function(ni,'static '+('int' if 'static int cortina_ni_reset' in ni else 'void')+' cortina_ni_reset(')
        body=function(phy,'int genphy_config(')
        header=r'''
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
#include <linux/mii.h>
#include <linux/ethtool.h>
typedef uint32_t u32;
#define SUPPORTED_1000baseX_Half (1 << 21)
#define SUPPORTED_1000baseX_Full (1 << 22)
#define MDIO_DEVAD_NONE (-1)
struct phy_device {u32 supported,advertising;};
static int cfg_result,selected,writes,wait_result;
static int phy_read(struct phy_device *p,int d,int reg){(void)p;(void)d;return reg==MII_BMSR?BMSR_ANEGCAPABLE|BMSR_ESTATEN|BMSR_10FULL|BMSR_100FULL:ESTATUS_1000_TFULL;}
static int genphy_config_aneg(struct phy_device *p){(void)p;return cfg_result;}
struct cortina_ni_priv {int active_port;void (*aal_set_active_port)(unsigned int);};
typedef union {unsigned int wrd;struct {unsigned int ni_init_done:1;}bf;} NI_HV_GLB_INIT_DONE_t;
typedef union {unsigned int wrd;struct {unsigned int reset_ni:1;}bf;} GLOBAL_BLOCK_RESET_t;
#define GLOBAL_BLOCK_RESET 1
#define NI_HV_GLB_INIT_DONE 2
#define REG_TIMEOUT_US 500000
#define CORTINA_CA_REG_READ(reg) 0
#define CORTINA_CA_REG_WRITE(v,r) ((void)(v),(void)(r),writes++)
#define readl_poll_timeout(a,val,cond,time) ((void)(a),(void)(time),(val)=0,wait_result)
static void select_port(unsigned int port){(void)port;selected++;}
'''
        tail=r'''
int configure(int err){cfg_result=err;struct phy_device p={0xffffffff,0xffffffff};return genphy_config(&p);}
int reset(int err){wait_result=err;selected=writes=0;struct cortina_ni_priv p={0,select_port};RESET_CALL;}
int metric(int key){return key?selected:writes;}
'''
        tail=tail.replace('RESET_CALL','return cortina_ni_reset(&p)' if 'static int cortina_ni_reset' in reset else 'cortina_ni_reset(&p);return 0')
        (work/'test.c').write_text(header+body+reset+tail)
        subprocess.run(['cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',str(work/'test.c'),'-o',str(work/'test.so')],check=True)
        cls.lib=C.CDLL(str(work/'test.so'))
        cls.ni=ni
    def test_configuration_failure_reaches_caller(self):
        for err in (-5,-110):self.assertEqual(self.lib.configure(err),err)
        self.assertEqual(self.lib.configure(0),0)
    def test_reset_timeout_never_selects_uninitialized_mac(self):
        self.assertEqual(self.lib.reset(-110),-110)
        self.assertEqual(self.lib.metric(1),0)
    def test_reset_success_selects_mac(self):
        self.assertEqual(self.lib.reset(0),0)
        self.assertEqual(self.lib.metric(1),1)
    def test_probe_propagates_reset_failure_before_allocating_mdio(self):
        body=function(self.ni,'static int cortina_ni_probe(')
        self.assertIn('ret = cortina_ni_reset(priv);\n\tif (ret) return ret;',body)
        self.assertLess(body.index('cortina_ni_reset'),body.index('mdio_alloc'))
if __name__=='__main__':unittest.main()
