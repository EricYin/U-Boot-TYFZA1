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
        detector = source[source.index('static int tyf_gpio_output('):source.index('static int tyf_ni_board_prepare(')]
        prelude = r"""
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
typedef uint32_t u32,ca_uint32_t;
typedef uint16_t u16,ca_uint16_t;
typedef unsigned long ulong;
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
static char variant[16],conf[16],bootcmd[32];
static u32 phy_id,address,control,regnum,datareg,seed;
static unsigned int elapsed,reset_at,released_at,enabled_at;
static unsigned int starts,clears,fail_phase,strap_reads,sequence_errors;
static uintptr_t locations[32],drop_write;static u32 values[32];static unsigned int count;
static unsigned int phases[8],registers[8],ready_delay,response_mode;
static int reset_level,enable_level;
static u32 raw(uintptr_t reg) {
 for(unsigned int i=0;i<count;i++)if(locations[i]==reg)return values[i];
 return seed;
}
static int pad(unsigned int pin) {
 uintptr_t bank=0xf43292c0+(pin/32)*0x24,mux=0xf4320100+(pin/32)*4;
 u32 bit=BIT(pin%32);
 if(!(raw(mux)&bit) || raw(bank)&bit)return -1;
 return !!(raw(bank+4)&bit);
}
static u32 readl(uintptr_t reg) {
 if(reg==0xf4329334UL){strap_reads++;return 0;}
 if(reg==PER_MDIO_CTRL)return starts==fail_phase?control:control|1;
 if(reg==PER_MDIO_RDDATA) {
  u32 id=phy_id;
  /* Actual pad ownership/direction and MDIO routing gate device response. */
  if(!(raw(0xf43200f4)&BIT(11)) || (raw(0xf4329118)&0xffff0001)!=0x001f0001 ||
     pad(128)!=1 || pad(14)!=1 || !released_at || !enabled_at ||
     elapsed<enabled_at+ready_delay)id=response_mode==3?0:0xffffffff;
  else if(response_mode==1 && starts>4)id=0xffffffff;
  else if(response_mode==2)id^=((starts-1)/4)&1;
  if(regnum!=2 && regnum!=3)sequence_errors++;
  if((address&0x1f)!=7 || ((address>>8)&31)!=1)sequence_errors++;
  return regnum==2?id>>16:id&0xffff;
 }
 return raw(reg);
}
static void writel(u32 value,uintptr_t reg) {
 if(reg==drop_write)return;
 unsigned int i;
 for(i=0;i<count;i++)if(locations[i]==reg)break;
 if(i==count){if(count==32){sequence_errors++;return;}locations[count++]=reg;}
 values[i]=value;
 if(reg==PER_MDIO_ADDR)address=value;
 if(reg==PER_MDIO_WRDATA)datareg=value;
 if(reg==PER_MDIO_CTRL) {
  if(value==1){control&=~1U;clears++;}
  if(value==128){
   if(control&1)sequence_errors++;
   if(starts<8){phases[starts]=address;registers[starts]=datareg;}
   starts++;if(!(address&(3U<<18)))regnum=datareg;
  }
 }
 int reset_now=pad(128),enable_now=pad(14);
 if(reset_now!=reset_level) {
  if(reset_now==0)reset_at=elapsed;
  if(reset_now==1 && reset_level==0){released_at=elapsed;if(elapsed-reset_at<30000)sequence_errors++;}
  reset_level=reset_now;
 }
 if(enable_now==1 && enable_level!=1) {
  enabled_at=elapsed;if(elapsed-released_at<300000)sequence_errors++;
 }
 enable_level=enable_now;
}
static void setbits_le32(uintptr_t reg,u32 mask){writel(readl(reg)|mask,reg);}
static void clrbits_le32(uintptr_t reg,u32 mask){writel(readl(reg)&~mask,reg);}
static void clrsetbits_le32(uintptr_t reg,u32 mask,u32 value){writel((readl(reg)&~mask)|value,reg);}
static void udelay(unsigned int us){elapsed+=us;}
static void mdelay(unsigned int ms){elapsed+=1000*ms;}
static ulong get_timer(ulong start){return elapsed/1000-start;}
static void tyfza1_recovery_leds(int state){(void)state;}
static int env_set(const char *name,const char *value) {
 char *target=!strcmp(name,"board_variant")?variant:!strcmp(name,"b_conf")?conf:!strcmp(name,"bootcmd")?bootcmd:NULL;
 if(target)strcpy(target,value?value:"");
 return 0;
}
"""
        tail = r"""
void setup(unsigned int delay,unsigned int mode,uintptr_t dropped) {
 ready_delay=delay;response_mode=mode;drop_write=dropped;
}
int run(uint32_t id,unsigned int fail,uint32_t previous,int stale) {
 phy_id=id;fail_phase=fail;seed=previous;control=1;count=starts=clears=0;
 elapsed=reset_at=released_at=enabled_at=strap_reads=sequence_errors=0;
 reset_level=pad(128);enable_level=pad(14);
 strcpy(variant,stale?"2p5g":"4ge");strcpy(conf,stale?"conf-0":"conf-1");strcpy(bootcmd,"stale");
 return board_late_init();
}
const char *setting(int key){return key==0?variant:key==1?conf:bootcmd;}
unsigned int metric(int key){switch(key){case 0:return elapsed;case 1:return starts;case 2:return clears;
 case 3:return strap_reads;case 4:return sequence_errors;default:return raw(0xf4329118);}}
unsigned int phase(int index){return phases[index];}
unsigned int reg_at(int index){return registers[index];}
"""
        path = Path(cls.work.name) / 'board.c'
        path.write_text(prelude + (BOARD / 'mdio.inc').read_text() + detector + late + tail)
        library = Path(cls.work.name) / 'board.so'
        subprocess.run(['cc', '-O2', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-function', str(path), '-o', str(library)], check=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.run.argtypes = [C.c_uint32, C.c_uint, C.c_uint32, C.c_int]
        cls.lib.setting.restype = C.c_char_p
        cls.lib.metric.restype = C.c_uint
        cls.lib.setup.argtypes = [C.c_uint, C.c_uint, C.c_size_t]

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def detect(self, phy_id, fail=0, seed=0, stale=0, delay=0, mode=0, dropped=0):
        self.lib.setup(delay, mode, dropped)
        self.assertEqual(self.lib.run(phy_id, fail, seed, stale), 0)
        self.assertEqual(self.lib.metric(3), 0, 'GPIO strap must not decide board identity')
        if not dropped:
            self.assertEqual(self.lib.metric(4), 0, 'PHY pad/reset/MDIO ordering violation')
            self.assertEqual(self.lib.metric(5), (seed & 0xfffe) | 0x001f0001)
        return tuple(self.lib.setting(i).decode() for i in range(3))

    def test_absent_phy_requires_a_full_discovery_window(self):
        for seed in (0, 0xa5a5a5a5, 0xffffffff):
            self.assertEqual(self.detect(0xffffffff, seed=seed, stale=1), ('4ge', 'conf-1', 'bootmenu 3'))
            self.assertEqual(self.lib.metric(0), 1630000)
            self.assertEqual(self.lib.metric(1), 400)

    def test_rtl8221b_revisions_need_two_matching_reads(self):
        for revision in range(16):
            self.assertEqual(self.detect(0x001cc840 | revision), ('2p5g', 'conf-0', 'bootmenu 3'))
            self.assertEqual(self.lib.metric(0), 640000)

    def test_real_pad_sequence_and_clause45_transactions(self):
        self.detect(0x001cc849)
        self.assertEqual([self.lib.metric(i) for i in (1, 2)], [8, 16])
        self.assertEqual([self.lib.phase(i) for i in range(8)], [0x10107, 0xd8107] * 4)
        self.assertEqual([self.lib.reg_at(i) for i in (0, 2, 4, 6)], [2, 3, 2, 3])

    def test_late_phy_with_initial_ones_or_zeros_is_recognized(self):
        for mode in (0, 3):
            for delay in (301000, 500000, 1250000):
                self.assertEqual(self.detect(0x001cc849, delay=delay, mode=mode), ('2p5g', 'conf-0', 'bootmenu 3'))

    def test_one_valid_reply_then_silence_or_changing_ids_is_not_four_ge(self):
        for mode in (1, 2):
            self.assertEqual(self.detect(0x001cc849, mode=mode), ('unknown', '', 'tyfrecovery'))
        self.assertEqual(self.detect(0x001cc849, delay=1290000), ('unknown', '', 'tyfrecovery'))

    def test_each_mdio_phase_timeout_is_an_error_not_an_absent_phy(self):
        for phase in range(1, 9):
            self.assertEqual(self.detect(0x001cc849, fail=phase), ('unknown', '', 'tyfrecovery'))
            self.assertEqual(self.lib.metric(1), phase)

    def test_failed_pinmux_direction_latch_or_mdc_write_is_detected(self):
        for address, seed in ((0xf43200f4, 0), (0xf4329118, 0),
                              (0xf4320110, 0), (0xf4329350, 0xffffffff),
                              (0xf4329354, 0), (0xf4320100, 0),
                              (0xf43292c0, 0xffffffff), (0xf43292c4, 0)):
            with self.subTest(address=hex(address)):
                self.assertEqual(self.detect(0x001cc849, seed=seed, dropped=address), ('unknown', '', 'tyfrecovery'))
                self.assertEqual(self.lib.metric(1), 0)

    def test_zero_partial_or_unexpected_ids_are_not_valid_board_identifiers(self):
        for phy in (0, 0xffff, 0xffff0000, 0x001ccac4, 0x001dc849):
            self.assertEqual(self.detect(phy), ('unknown', '', 'tyfrecovery'))


if __name__ == '__main__':
    unittest.main()
