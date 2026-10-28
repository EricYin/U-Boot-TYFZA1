#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute physical discovery, real C45 transfers and late init in simulated MMIO."""
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / 'overlay/board/realtek/tyfza1'


class BoardIdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory()
        source = (BOARD / 'tyfza1.c').read_text()
        late = source[source.index('int board_late_init('):source.index('static int tyfza1_boot(')]
        source = (BOARD / 'ni-board.inc').read_text()
        detector = source[source.index('static void tyf_gpio_output('):source.index('static int tyf_ni_board_prepare(')]
        prelude = r'''
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
typedef uint32_t u32,ca_uint32_t;
typedef uint16_t u16,ca_uint16_t;
typedef int ca_status_t;
#define BIT(n) (1U << (n))
#define PER_WDT_CTRL 0xf432901cUL
#define GLOBAL_SCRATCH 0xf4329000UL
#define DMA_SEC_SSP_FRAME_CTRL0 0xf4320000UL
#define PER_MDIO_ADDR 0xf432911cUL
#define PER_MDIO_WRDATA 0xf4329120UL
#define PER_MDIO_RDDATA 0xf4329124UL
#define PER_MDIO_CTRL 0xf4329128UL
#define MDIO_MMD_PMAPMD 1
#define MII_PHYSID1 2
#define MII_PHYSID2 3
#define CONFIG_MTDIDS_DEFAULT "nand0=nand0"
#define CONFIG_MTDPARTS_DEFAULT "mtdparts=nand0:2m(boot),-(data)"
enum {TYFZA1_LEDS_HELD};
static bool reset_requested;
static char variant[16], conf[16], bootcmd[32];
static u32 phy_id, address, control, regnum, datareg, seed;
static unsigned int elapsed, reset_at, released_at, enabled_at;
static unsigned int starts, clears, fail_phase, strap_reads, sequence_errors;
static uintptr_t locations[64];static u32 values[64];static unsigned int writes;
static unsigned int phases[4], registers[4];
static u32 readl(uintptr_t reg) {
 if(reg==0xf4329334UL){strap_reads++;return 0;}
 if(reg==PER_MDIO_CTRL)return starts==fail_phase?control:control|1;
 if(reg==PER_MDIO_RDDATA) {
  if(elapsed < enabled_at+300000 || !enabled_at)sequence_errors++;
  if(regnum!=2 && regnum!=3)sequence_errors++;
  return regnum==2?phy_id>>16:phy_id&0xffff;
 }
 for(unsigned int i=writes;i>0;i--)if(locations[i-1]==reg)return values[i-1];
 return seed;
}
static void writel(u32 value,uintptr_t reg) {
 if(reg==PER_MDIO_ADDR)address=value;
 if(reg==PER_MDIO_WRDATA)datareg=value;
 if(reg==PER_MDIO_CTRL) {
  if(value==1){control&=~1U;clears++;}
  if(value==128){
   if(control&1)sequence_errors++;
   if(starts<4){phases[starts]=address;registers[starts]=datareg;}
   starts++;if(!(address & (3U<<18)))regnum=datareg;
  }
 }
 if(reg==0xf4329354UL) {
  if(!(value&1))reset_at=elapsed;
  else {released_at=elapsed;if(released_at-reset_at<30000)sequence_errors++;}
 }
 if(reg==0xf43292c4UL && value&BIT(14)) {
  enabled_at=elapsed;if(enabled_at-released_at<300000)sequence_errors++;
 }
 if(writes<64){locations[writes]=reg;values[writes++]=value;}
}
static void setbits_le32(uintptr_t reg,u32 mask){writel(readl(reg)|mask,reg);}
static void clrbits_le32(uintptr_t reg,u32 mask){writel(readl(reg)&~mask,reg);}
static void clrsetbits_le32(uintptr_t reg,u32 mask,u32 value){writel((readl(reg)&~mask)|value,reg);}
static void udelay(unsigned int us){elapsed+=us;}
static void mdelay(unsigned int ms){elapsed+=1000*ms;}
static void tyfza1_recovery_leds(int state){(void)state;}
static int env_set(const char *name,const char *value) {
 char *target=!strcmp(name,"board_variant")?variant:!strcmp(name,"b_conf")?conf:!strcmp(name,"bootcmd")?bootcmd:NULL;
 if(target)strcpy(target,value?value:"");
 return 0;
}
'''
        tail = r'''
int run(uint32_t id,unsigned int fail,uint32_t previous,int stale) {
 phy_id=id;fail_phase=fail;seed=previous;control=1;writes=starts=clears=0;
 elapsed=reset_at=released_at=enabled_at=strap_reads=sequence_errors=0;
 strcpy(variant,stale?"2p5g":"4ge");strcpy(conf,stale?"conf-0":"conf-1");strcpy(bootcmd,"stale");
 return board_late_init();
}
const char *setting(int key){return key==0?variant:key==1?conf:bootcmd;}
unsigned int metric(int key){switch(key){case 0:return elapsed;case 1:return starts;case 2:return clears;
 case 3:return strap_reads;case 4:return sequence_errors;default:return readl(0xf4329118);}}
unsigned int phase(int index){return phases[index];}
unsigned int reg_at(int index){return registers[index];}
'''
        path = Path(cls.work.name) / 'board.c'
        path.write_text(prelude + (BOARD / 'mdio.inc').read_text() + detector + late + tail)
        library = Path(cls.work.name) / 'board.so'
        subprocess.run(['cc', '-O2', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-function', str(path), '-o', str(library)], check=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.run.argtypes = [C.c_uint32, C.c_uint, C.c_uint32, C.c_int]
        cls.lib.setting.restype = C.c_char_p
        cls.lib.metric.restype = C.c_uint

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def detect(self, phy_id, fail=0, seed=0, stale=0):
        self.assertEqual(self.lib.run(phy_id, fail, seed, stale), 0)
        self.assertEqual(self.lib.metric(3), 0, 'GPIO strap must not decide board identity')
        self.assertEqual(self.lib.metric(4), 0, 'PHY power/reset/MDIO ordering violation')
        self.assertEqual(self.lib.metric(5), seed | 1, 'Preserve the MDC prescaler')
        return tuple(self.lib.setting(i).decode() for i in range(3))

    def test_four_ge_absent_external_phy_ignores_zero_strap_and_stale_variant(self):
        for seed in (0, 0xa5a5a5a5, 0xffffffff):
            self.assertEqual(self.detect(0xffffffff, seed=seed, stale=1), ('4ge', 'conf-1', 'bootmenu 3'))

    def test_rtl8221b_revisions_ignore_stale_four_ge_variant(self):
        for revision in range(16):
            self.assertEqual(self.detect(0x001cc840 | revision), ('2p5g', 'conf-0', 'bootmenu 3'))

    def test_power_sequence_and_actual_clause45_id_transactions(self):
        self.detect(0x001cc848)
        self.assertEqual([self.lib.metric(i) for i in (0, 1, 2)], [630000, 4, 8])
        self.assertEqual([self.lib.phase(i) for i in range(4)], [0x10107, 0xd8107, 0x10107, 0xd8107])
        self.assertEqual([self.lib.reg_at(i) for i in (0, 2)], [2, 3])

    def test_each_mdio_phase_timeout_is_an_error_not_an_absent_phy(self):
        for phase in range(1, 5):
            for phy in (0x001cc848, 0xffffffff):
                self.assertEqual(self.detect(phy, fail=phase), ('unknown', '', 'tyfrecovery'))
                self.assertEqual(self.lib.metric(1), phase)
                self.assertEqual(self.lib.metric(0), 680000)

    def test_zero_partial_or_unexpected_ids_are_not_valid_board_identifiers(self):
        for phy in (0, 0xffff, 0xffff0000, 0x001ccac4, 0x001cc849 ^ 0x10000):
            self.assertEqual(self.detect(phy), ('unknown', '', 'tyfrecovery'))


if __name__ == '__main__':
    unittest.main()
