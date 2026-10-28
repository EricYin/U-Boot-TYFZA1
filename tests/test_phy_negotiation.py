#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run the actual generic PHY advertisement, restart and negotiated-mode code."""
import ctypes as C
from pathlib import Path
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
def extract(text,signature):
    a=text.index(signature);return text[a:text.index('\n}',a)+2]
class PhyNegotiationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=(ROOT/'build/u-boot/drivers/net/phy/phy.c').read_text()
        bodies='\n'.join(extract(source,s) for s in ['static int genphy_config_advert(', 'static int genphy_setup_forced(',
                    'int genphy_restart_aneg(', 'int genphy_config_aneg(', 'int genphy_config(', 'int genphy_parse_link('])
        header=r'''
#include <stdint.h>
#include <string.h>
#include <errno.h>
#include <linux/mii.h>
#include <linux/ethtool.h>
typedef uint32_t u32;
#define MDIO_DEVAD_NONE (-1)
#define SUPPORTED_1000baseX_Half (1 << 21)
#define SUPPORTED_1000baseX_Full (1 << 22)
#define ADVERTISED_1000baseX_Half (1 << 21)
#define ADVERTISED_1000baseX_Full (1 << 22)
#define PHY_1000BTSR_1000FD LPA_1000FULL
#define PHY_1000BTSR_1000HD LPA_1000HALF
#define debug(...) ((void)0)
struct phy_device {u32 supported,advertising;int autoneg,speed,duplex,pause,asym_pause;};
static int regs[32],read_fail,write_fail;
static struct phy_device phy;
static int phy_read(struct phy_device *p,int d,int r){(void)p;(void)d;return r==read_fail?-EIO:regs[r];}
static int phy_write(struct phy_device *p,int d,int r,int v){(void)p;(void)d;if(r==write_fail)return -EIO;regs[r]=v;return 0;}
'''
        tail=r'''
void setup(int speed,int duplex,int read_error,int write_error){
 memset(regs,0,sizeof(regs));read_fail=read_error;write_fail=write_error;
 phy=(struct phy_device){.autoneg=AUTONEG_ENABLE,.speed=-1,.duplex=-1,
 .supported=SUPPORTED_Autoneg|SUPPORTED_10baseT_Half|SUPPORTED_10baseT_Full|SUPPORTED_100baseT_Half|SUPPORTED_100baseT_Full|SUPPORTED_1000baseT_Half|SUPPORTED_1000baseT_Full};
 phy.advertising=phy.supported;
 regs[MII_BMSR]=BMSR_ANEGCAPABLE|BMSR_ANEGCOMPLETE|BMSR_LSTATUS|BMSR_ERCAP|BMSR_ESTATEN|BMSR_10FULL|BMSR_10HALF|BMSR_100FULL|BMSR_100HALF;
 regs[MII_ESTATUS]=ESTATUS_1000_TFULL|ESTATUS_1000_THALF;
 regs[MII_ADVERTISE]=ADVERTISE_10FULL|ADVERTISE_10HALF|ADVERTISE_100FULL|ADVERTISE_100HALF;
 regs[MII_CTRL1000]=ADVERTISE_1000FULL|ADVERTISE_1000HALF;
 regs[MII_STAT1000]=speed==1000?(duplex?LPA_1000FULL:LPA_1000HALF):0;
 regs[MII_LPA]=speed==100?(duplex?LPA_100FULL:LPA_100HALF):(duplex?LPA_10FULL:LPA_10HALF);
 regs[MII_BMCR]=BMCR_ANENABLE;
}
int configure(void){regs[MII_ADVERTISE]=0;regs[MII_CTRL1000]=0;return genphy_config(&phy);}
int parse(void){return genphy_parse_link(&phy);}
int metric(int n){return n==0?phy.speed:n==1?phy.duplex:regs[n-2];}
void extended_only(void){regs[MII_BMSR]&=~BMSR_ERCAP;}
void forced(int speed,int duplex){phy.autoneg=AUTONEG_DISABLE;regs[MII_BMCR]=(duplex?BMCR_FULLDPLX:0)|(speed==1000?BMCR_SPEED1000:speed==100?BMCR_SPEED100:0);}
'''
        w=ROOT/'build/phy-negotiation-test';w.mkdir(exist_ok=True,parents=True)
        (w/'test.c').write_text(header+bodies+tail)
        subprocess.run(['cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',str(w/'test.c'),'-o',str(w/'test.so')],check=True)
        cls.lib=C.CDLL(str(w/'test.so'))
    def test_negotiated_speed_and_duplex_from_real_partner_registers(self):
        for speed in (10,100,1000):
            for duplex in (0,1):
                self.lib.setup(speed,duplex,-1,-1)
                self.assertEqual(self.lib.parse(),0)
                self.assertEqual(self.lib.metric(0),speed);self.assertEqual(self.lib.metric(1),duplex)
    def test_gigabit_advertisement_and_autonegotiation_restart(self):
        self.lib.setup(1000,1,-1,-1)
        self.assertEqual(self.lib.configure(),0)
        self.assertEqual(self.lib.metric(2+9)&0x300,0x300)
        self.assertEqual(self.lib.metric(2)&0x1200,0x1200)
    def test_write_errors_at_each_configuration_stage_are_returned(self):
        for reg in (4,9,0):
            self.lib.setup(1000,1,-1,reg)
            self.assertEqual(self.lib.configure(),-5)
    def test_partner_read_errors_are_not_reported_as_successful_negotiation(self):
        for reg in (1,10,9,4,5):
            self.lib.setup(100,1,reg,-1)
            with self.subTest(register=reg):self.assertEqual(self.lib.parse(),-5)
    def test_forced_modes_keep_normal_speed_and_duplex(self):
        for speed in (10,100,1000):
            for duplex in (0,1):
                self.lib.setup(speed,duplex,-1,-1);self.lib.forced(speed,duplex)
                self.assertEqual(self.lib.parse(),0)
                self.assertEqual(self.lib.metric(0),speed);self.assertEqual(self.lib.metric(1),duplex)
    def test_extended_status_error_is_returned(self):
        self.lib.setup(100,1,15,-1);self.lib.extended_only()
        self.assertEqual(self.lib.parse(),-5)
    def test_forced_control_read_error_is_returned(self):
        self.lib.setup(100,1,0,-1);self.lib.forced(100,1)
        self.assertEqual(self.lib.parse(),-5)
if __name__=='__main__':unittest.main()
