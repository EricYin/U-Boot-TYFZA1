#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check real NI board helpers, link switching and S3 against public Taurus code."""
import ctypes as C
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "overlay/board/realtek/tyfza1"
WORK = ROOT / "build/ni-board-test"


class NiBoardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        WORK.mkdir(parents=True, exist_ok=True)
        vendor = ROOT / "sources/realtek-gpl/bootloader/u-boot-2022.10"
        registers = vendor / "arch/arm/include/asm/arch-taurus/registers.h"
        (WORK / "registers.h").write_bytes(registers.read_bytes())
        (WORK / "ca_types.h").write_text("#include <stdint.h>\ntypedef uint32_t ca_uint32_t;\n")
        original = (vendor / "board/realtek_10G_PON/common/eth_ni_taurus.c").read_text()
        original = original[original.index("static void __p4_sds_1g_patch"):]
        original = original[:original.index("\n}", original.index("static int __p4_sds_mode_set")) + 2]
        header = r'''
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>
#include <stdio.h>
typedef uint32_t u32;
typedef uint16_t u16;
typedef unsigned long ulong;
#define MDIO_MMD_PMAPMD 1
#define MII_PHYSID1 2
#define MII_PHYSID2 3
static int __ca_mdio_c45_read(unsigned int addr,unsigned int devad,unsigned short reg,unsigned short *data) {
 (void)addr;(void)devad;*data=reg==2?0x001c:0xc848;return 0;
}
#define BIT(n) (1U<<(n))
#define ARRAY_SIZE(a) (sizeof(a)/sizeof(a[0]))
#define __iomem
struct phy_device { int link, speed, duplex, is_c45, addr; };
struct mapping { int phy_id, sds_mode; };
struct cortina_ni_priv {
 struct mapping maps[6];int active_port,is_phyinited,active_scan;
 unsigned long link_polled; struct phy_device *phydev;
 int (*aal_mode_sync)(unsigned int,int,struct phy_device *);
 void (*aal_set_active_port)(unsigned int);
};
#define AAL_SDS_MODE_SGMII 1
typedef enum { AAL_SDS_MODE_NONE=0, AAL_MODE_SGMII=1, AAL_SDS_MODE_FIBER=2 } aal_sds_mode_t;
typedef enum { AAL_SDS_SPEED_DEFAULT=0,AAL_SDS_SPEED_100M=1,AAL_SDS_SPEED_1G=2,AAL_SDS_SPEED_2G5=3,AAL_SDS_SPEED_5G=4,AAL_SDS_SPEED_10G=5,AAL_SDS_SPEED_10M=6 } aal_sds_speed_t;
static uint32_t seed;
static uintptr_t written_address[512];static uint32_t written_value[512];static unsigned int writes;
static uint32_t io_read(uintptr_t address) {
 for(unsigned int i=writes;i>0;i--)if(written_address[i-1]==address)return written_value[i-1];
 return seed;
}
static void io_write(uint32_t value,uintptr_t address) {
 if(writes<512){written_address[writes]=address;written_value[writes++]=value;}
}
#define readl(address) io_read((uintptr_t)(address))
#define writel(value,address) io_write(value,(uintptr_t)(address))
#define CA_NE_SGMII_LP_REG_READ readl
#define CA_NE_SGMII_LP_REG_WRITE writel
#define AAL_GLB_REG_READ readl
#define AAL_GLB_REG_WRITE writel
#define CA_E_PARAM (-22)
#define CA_E_OK 0
static unsigned int delay_ms,delay_us;
static void mdelay(unsigned int value){delay_ms+=value;}
static void udelay(unsigned int value){delay_us+=value;}
static void setbits_le32(uintptr_t addr,uint32_t mask){writel(readl(addr)|mask,addr);}
static void clrbits_le32(uintptr_t addr,uint32_t mask){writel(readl(addr)&~mask,addr);}
static void clrsetbits_le32(uintptr_t addr,uint32_t mask,uint32_t value){writel((readl(addr)&~mask)|value,addr);}
static const char *variant;
static const char *env_get(const char *name){(void)name;return variant;}
static struct phy_device phys[5];static struct cortina_ni_priv priv;
static int status1[5],status2[5],poll_errors[5];
static int sync_error,sync_count,enabled=-1,selected=-1;
static int phy_read(struct phy_device *p,int devad,int reg) { (void)devad;(void)reg;return poll_errors[p->addr]?-5:status1[p->addr]; }
static int genphy_parse_link(struct phy_device *p){p->speed=status2[p->addr];p->duplex=1;return 0;}
static int phy_startup(struct phy_device *p){p->link=!!status1[p->addr];p->speed=status2[p->addr];p->duplex=1;return poll_errors[p->addr]?-5:0;}
#define MDIO_DEVAD_NONE (-1)
#define MII_BMSR 1
#define BMSR_LSTATUS 4
#define BMSR_ANEGCOMPLETE 32
static unsigned long now;
static unsigned long get_timer(unsigned long start){return now-start;}
static struct phy_device *__get_curr_phydev(struct cortina_ni_priv *p){return p->active_port>=0&&p->active_port<5?&phys[p->active_port]:NULL;}
static int is_valid_port(struct cortina_ni_priv *p,int port){(void)p;return port>=0&&port<5;}
static void ni_enable_tx_rx(int port,int enable){if(enable)enabled=port;else if(enabled==port)enabled=-1;}
static int sync_mode(unsigned int port,int mode,struct phy_device *p){(void)port;(void)mode;(void)p;sync_count++;return sync_error;}
static void select_port(unsigned int port){selected=port;}
static int tyf_ni_phy_status(struct phy_device *phy);
static void ni_auto_scan_active_port(struct cortina_ni_priv *p){
 p->active_port=-1;
 for(int i=0;i<5;i++)if(!tyf_ni_phy_status(&phys[i])&&phys[i].link){p->active_port=i;return;}
}
'''
        tail = r'''
void reset(unsigned int value){
 seed=value;writes=delay_ms=delay_us=sync_count=sync_error=now=0;enabled=selected=-1;
 memset(phys,0,sizeof(phys));memset(status1,0,sizeof(status1));memset(status2,0,sizeof(status2));memset(poll_errors,0,sizeof(poll_errors));
 for(int i=0;i<5;i++){phys[i].addr=i;phys[i].is_c45=i==4;}
 priv=(struct cortina_ni_priv){.active_port=-1,.is_phyinited=1,.aal_mode_sync=sync_mode,.aal_set_active_port=select_port};
}
int prepare(int two){variant=two?"2p5g":"4ge";return tyf_ni_board_prepare(&priv);}
int speed(unsigned int value,int stock){
 if(stock){aal_sds_speed_t s=value==2500?AAL_SDS_SPEED_2G5:value==1000?AAL_SDS_SPEED_1G:value==100?AAL_SDS_SPEED_100M:AAL_SDS_SPEED_10M;return __p4_sds_mode_set(AAL_MODE_SGMII,s);}
 struct phy_device p={.link=1,.speed=value};return tyf_ni_port4_speed(&p);
}
unsigned int write_count(void){return writes;}
uintptr_t write_address(unsigned int i){return written_address[i];}
unsigned int write_value(unsigned int i){return written_value[i];}
unsigned int get_value(uintptr_t address){return readl(address);}
int metric(int key){switch(key){case 0:return delay_ms;case 1:return delay_us;case 2:return priv.maps[4].phy_id;case 3:return enabled;case 4:return selected;case 5:return sync_count;}return 0;}
void link(int port,int up,int value,int error){status1[port]=up?36:0;status2[port]=value;poll_errors[port]=error;}
int poll(unsigned int delta,int error){now+=delta;sync_error=error;return tyf_ni_refresh_link(&priv);}
'''
        source = WORK / "board.c"
        source.write_text(header + '\n#include "registers.h"\n' + original +
                          '\n#include "ni-board.inc"\n' + tail)
        library = WORK / "board.so"
        subprocess.run(["cc", "-shared", "-fPIC", "-O2", "-Wall", "-Wextra", "-Werror",
            "-I"+str(WORK), "-I"+str(BOARD), str(source), "-o", str(library)], check=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.write_address.restype = C.c_size_t
        cls.lib.get_value.argtypes = [C.c_size_t]
        cls.lib.get_value.restype = C.c_uint
        cls.rows = []

    def trace(self):
        return [[self.lib.write_address(i), self.lib.write_value(i)] for i in range(self.lib.write_count())]

    def test_s3_speed_sequences_against_vendor(self):
        for speed in (10, 100, 1000, 2500):
            for seed in (0, 0xa5a5a5a5, 0xffffffff):
                self.lib.reset(seed); self.assertEqual(self.lib.speed(speed, 1), 0)
                original = self.trace()
                self.lib.reset(seed); self.assertEqual(self.lib.speed(speed, 0), 0)
                native = self.trace()
                self.assertEqual(native, original, f"speed {speed}, seed {seed:#x}")
                self.assertEqual(self.lib.metric(1), 20)
                self.rows.append({"speed": speed, "seed": seed, "writes": len(native),
                    "trace_sha256": hashlib.sha256(json.dumps(native).encode()).hexdigest()})

    def test_only_2p5g_board_enables_port4_and_s3_without_resetting_detected_phy(self):
        self.lib.reset(0xa5a5a5a5); self.assertEqual(self.lib.prepare(0), 0)
        self.assertEqual(self.lib.write_count(), 0); self.assertEqual(self.lib.metric(2), -1)
        self.lib.reset(0xa5a5a5a5); self.assertEqual(self.lib.prepare(1), 0)
        self.assertEqual(self.lib.metric(2), 7); self.assertEqual(self.lib.metric(0), 0)
        self.assertEqual(self.lib.get_value(0xf4329354), 0xa5a5a5a5)
        self.assertEqual(self.lib.get_value(0xf43292c4), 0xa5a5a5a5)
        self.assertEqual(self.lib.get_value(0xf432036c), (0xa5a5a5a5|0xc0080000)&~0x6020)
        self.assertEqual(self.lib.get_value(0xf460001c), 0x5359)

    def test_late_cable_connect_disconnect_and_switch(self):
        self.lib.reset(0)
        self.assertEqual(self.lib.poll(250, 0), 0); self.assertEqual(self.lib.metric(3), -1)
        self.lib.link(1, 1, 1000, 0)
        self.assertEqual(self.lib.poll(250, 0), 0); self.assertEqual(self.lib.metric(3), 1)
        self.lib.link(1, 0, 1000, 0); self.lib.link(4, 1, 2500, 0)
        self.assertEqual(self.lib.poll(250, 0), 0); self.assertEqual(self.lib.metric(3), 4)
        self.assertEqual(self.lib.metric(4), 4)
        self.lib.link(4, 1, 1000, 0)
        count = self.lib.metric(5)
        self.assertEqual(self.lib.poll(250, 0), 0); self.assertEqual(self.lib.metric(5), count+1)
        self.lib.link(4, 0, 1000, 0)
        self.assertEqual(self.lib.poll(250, 0), 0); self.assertEqual(self.lib.metric(3), -1)

    def test_no_reconfiguration_when_link_unchanged_or_poll_too_soon(self):
        self.lib.reset(0); self.lib.link(4, 1, 2500, 0)
        self.assertEqual(self.lib.poll(250, 0), 0); count = self.lib.metric(5)
        self.assertEqual(self.lib.poll(100, 0), 0)
        self.assertEqual(self.lib.poll(250, 0), 0); self.assertEqual(self.lib.metric(5), count)

    def test_mdio_and_mode_errors_do_not_keep_a_live_path(self):
        self.lib.reset(0); self.lib.link(4, 1, 2500, 0)
        self.assertEqual(self.lib.poll(250, 0), 0)
        self.lib.link(4, 1, 2500, 1)
        self.assertEqual(self.lib.poll(250, 0), 0); self.assertEqual(self.lib.metric(3), -1)
        self.lib.reset(0); self.lib.link(4, 1, 2500, 0)
        self.assertEqual(self.lib.poll(250, -5), -5); self.assertEqual(self.lib.metric(3), -1)

    @classmethod
    def tearDownClass(cls):
        (ROOT / "evidence/ni-board-registers.json").write_text(json.dumps({
            "scope": "Production NI helpers in simulated MMIO, S3 speed writes compared against fixed vendor C/bitfields; no electrical/link acceptance",
            "s3_speed_cases": cls.rows}, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main()
