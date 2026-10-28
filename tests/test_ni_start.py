#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run production NI startup/port selection with per-PHY failures."""
import ctypes as C
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NiStartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        vendor = (ROOT / 'build/u-boot/board/realtek/tyfza1/vendor/eth_ni.c').read_text()
        bodies = ''
        for signature in ('static inline int is_valid_port(', 'static void ni_auto_scan_active_port(',
                          'static struct phy_device *__get_curr_phydev(', 'static int cortina_ni_start('):
            begin = vendor.index(signature)
            bodies += vendor[begin:vendor.index('\n}', begin) + 2] + '\n'
        prelude = r'''
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define PORT_MAX 6
#define MODULE_NAME "NI"
#define PHY_INTERFACE_MODE_RGMII 1
#define MDIO_DEVAD_NONE (-1)
#define MII_BMCR 0
#define BMCR_PDOWN 0x800
#define DUPLEX_HALF 0
#define FOR_DEBUG 0
#define RX_TOP_ADDR 1023
#define RX_BASE_ADDR 0
#define TX_TOP_ADDR 1023
#define TX_BASE_ADDR 0
#define NI_HV_XRAM_CPUXRAM_ADRCFG_RX 0
#define NI_HV_XRAM_CPUXRAM_ADRCFG_TX_0 1
#define NI_HV_XRAM_CPUXRAM_CFG 2
#define CORTINA_CA_REG_READ(reg) 0
#define CORTINA_CA_REG_WRITE(value,reg) ((void)(value),(void)(reg))
#define debug(...) ((void)0)
typedef unsigned char u8;
typedef union {unsigned int wrd;struct{unsigned int rx_top_addr:10,rx_base_addr:10,unused:12;}bf;} NI_HV_XRAM_CPUXRAM_ADRCFG_RX_t;
typedef union {unsigned int wrd;struct{unsigned int tx_top_addr:10,tx_base_addr:10,unused:12;}bf;} NI_HV_XRAM_CPUXRAM_ADRCFG_TX_0_t;
typedef union {unsigned int wrd;struct{unsigned int xram_mgmt_promisc_mode:2,rx_0_cpu_pkt_dis:1,tx_0_cpu_pkt_dis:1,unused:28;}bf;} NI_HV_XRAM_CPUXRAM_CFG_t;
struct phy_driver {const char *name;};
struct phy_device {struct phy_driver *drv;unsigned int phy_id;int addr,link,speed,duplex,is_c45,port;};
struct port_phy_map_t {int phy_id,sds_mode;};
struct mii_dev {struct phy_device *phymap[8];};
struct cortina_ni_priv {
 struct port_phy_map_t maps[6];int is_phyinited,active_port,active_scan,rxmode;
 struct mii_dev *bus_int;struct phy_device *phydev;
 int (*aal_mode_sync)(unsigned int,int,struct phy_device *);
 void (*aal_set_active_port)(unsigned int);
};
struct udevice {struct cortina_ni_priv *priv;};
static struct cortina_ni_priv priv;
static struct mii_dev bus;
static struct phy_device phys[8];
static struct phy_driver driver={"mock PHY"};
static unsigned int missing,config_errors,read_errors,write_errors,links;
static int configured,enabled,selected_speed,failed_scans,status_calls,drop_after;
static void *dev_get_priv(struct udevice *d){return d->priv;}
static struct phy_device *phy_connect(struct mii_dev *b,int addr,struct udevice *d,int interface){
 (void)b;(void)d;(void)interface;return missing&(1U<<phys[addr].port)?NULL:&phys[addr];
}
static int phy_config(struct phy_device *p){if(config_errors&(1U<<p->port))return -ETIMEDOUT;configured++;return 0;}
static int phy_read(struct phy_device *p,int d,int r){(void)d;(void)r;return read_errors&(1U<<p->port)?-EIO:BMCR_PDOWN;}
static int phy_write(struct phy_device *p,int d,int r,int v){(void)d;(void)r;(void)v;return write_errors&(1U<<p->port)?-EIO:0;}
static int tyf_ni_phy_status(struct phy_device *p){
 if((missing|config_errors|read_errors|write_errors)&(1U<<p->port))failed_scans++;
 status_calls++;p->link=drop_after && status_calls>=drop_after?0:!!(links&(1U<<p->port));return 0;
}
static void ni_enable_tx_rx(int port,int on){if(on)enabled=port;else if(enabled==port)enabled=-1;}
static void udelay(unsigned int n){(void)n;}
static int sync_mode(unsigned int p,int m,struct phy_device *phy){(void)p;(void)m;selected_speed=phy->speed;return 0;}
static void select_port(unsigned int p){(void)p;}
'''
        tail = r'''
int run(int two,unsigned int absent,unsigned int config,unsigned int rd,unsigned int wr,
        unsigned int up,int active,int scan){
 missing=absent;config_errors=config;read_errors=rd;write_errors=wr;links=up;
 configured=failed_scans=selected_speed=status_calls=0;enabled=-1;
 memset(&priv,0,sizeof(priv));memset(&bus,0,sizeof(bus));memset(phys,0,sizeof(phys));
 (void)two;int ids[]={1,2,3,4,-1,-1};
 for(int i=0;i<6;i++){
  priv.maps[i].phy_id=ids[i];if(ids[i]<0)continue;
  struct phy_device *p=&phys[ids[i]];
  p->drv=&driver;p->addr=ids[i];p->port=i;p->phy_id=i==4?0x1cc848:0x1ccac4;
  p->is_c45=i==4;p->speed=i==4?2500:1000;p->duplex=1;bus.phymap[ids[i]]=p;
 }
 priv.bus_int=&bus;priv.active_port=active;priv.active_scan=scan;
 priv.aal_mode_sync=sync_mode;priv.aal_set_active_port=select_port;
 struct udevice dev={&priv};return cortina_ni_start(&dev);
}
void drop(int n){drop_after=n;}
int restart(unsigned int up){links=up;struct udevice dev={&priv};return cortina_ni_start(&dev);}
int metric(int key){
 switch(key){case 0:return enabled;case 1:return priv.active_port;case 2:return priv.is_phyinited;
 case 3:return configured;case 4:return priv.maps[4].phy_id;case 5:return selected_speed;
 case 6:return failed_scans;case 7:return priv.active_scan;}return -1;
}
'''
        work = ROOT / 'build/ni-start-test'
        work.mkdir(parents=True, exist_ok=True)
        source = work / 'start.c'
        source.write_text(prelude + bodies + tail)
        library = work / 'start.so'
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                        str(source), '-o', str(library)], check=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.run.argtypes = [C.c_int] * 8

    def start(self, two=1, missing=0, config=0, read=0, write=0, up=1, active=0, scan=1):
        return self.lib.run(two, missing, config, read, write, up, active, scan)

    def test_link_lost_after_scan_waits_instead_of_failing_start(self):
        self.lib.drop(2)
        try:
            self.assertEqual(self.start(up=1),0)
            self.assertEqual(self.lib.metric(0),-1)
        finally:
            self.lib.drop(0)

    def test_disabled_external_phy_does_not_affect_each_gigabit_port(self):
        for failure in ('missing', 'config'):
            for port in range(4):
                with self.subTest(failure=failure, port=port):
                    self.assertEqual(self.start(**{failure: 1 << 4}, up=1 << port), 0)
                    self.assertEqual(self.lib.metric(0), port)
                    self.assertEqual(self.lib.metric(2), 1)
                    self.assertEqual(self.lib.metric(4), -1)
                    self.assertEqual(self.lib.metric(6), 0)

    def test_external_port_never_enabled(self):
        self.assertEqual(self.start(up=1 << 4), 0)
        self.assertEqual(self.lib.metric(0), -1)
        self.assertEqual(self.lib.metric(4), -1)

    def test_each_internal_failure_is_isolated(self):
        for failure in ('missing', 'config', 'read', 'write'):
            for port in range(4):
                with self.subTest(failure=failure, port=port):
                    self.assertEqual(self.start(**{failure: 1 << port}, up=15), 0)
                    self.assertNotEqual(self.lib.metric(0), port)
                    self.assertEqual(self.lib.metric(6), 0)

    def test_invalid_internal_driver_selection_falls_back(self):
        self.assertEqual(self.start(missing=1 << 4, active=4, scan=0), 0)
        self.assertEqual(self.lib.metric(0), 0)
        self.assertEqual(self.lib.metric(7), 1)

    def test_recovery_can_wait_for_cable_after_external_failure(self):
        self.assertEqual(self.start(config=1 << 4, up=0), 0)
        self.assertEqual(self.lib.metric(0), -1)
        for port in range(4):
            self.assertEqual(self.lib.restart(1 << port), 0)
            self.assertEqual(self.lib.metric(0), port)
            self.assertEqual(self.lib.metric(6), 0)

    def test_no_usable_phy_still_reports_failure(self):
        self.assertEqual(self.start(missing=0x1f), -19)
        self.assertEqual(self.lib.metric(0), -1)

    def test_four_ge_board_keeps_all_four_ports(self):
        for port in range(4):
            self.assertEqual(self.start(two=0, up=1 << port), 0)
            self.assertEqual(self.lib.metric(0), port)


if __name__ == '__main__':
    unittest.main()
