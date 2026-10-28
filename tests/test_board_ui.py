#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute GPIO sampling and common status lamp ordering against a register model."""
import ctypes as C
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BoardUiTests(unittest.TestCase):
    BOARDS=[(0,[9,10],0x600),(1,[9,10],0x600)]
    OFF,HELD,IDLE,UPLOAD,BUSY,DONE,FAILED=range(7)

    @classmethod
    def setUpClass(cls):
        work = ROOT/'build/board-ui-test'
        work.mkdir(parents=True, exist_ok=True)
        body = '\n'.join(line for line in (ROOT/'overlay/board/realtek/tyfza1/board-ui.c').read_text().splitlines()
                         if not line.startswith('#include'))
        prelude = r'''
#include <stdint.h>
#include <string.h>
#include <stddef.h>
typedef uint32_t u32;
typedef unsigned long ulong;
static u32 mux, dir, output, input, frames[4];
static unsigned int nframes, delay, writes;
static const char *variant;
static unsigned long now;
enum tyfza1_leds { TYFZA1_LEDS_OFF, TYFZA1_LEDS_HELD, TYFZA1_LEDS_IDLE, TYFZA1_LEDS_UPLOAD, TYFZA1_LEDS_BUSY, TYFZA1_LEDS_DONE, TYFZA1_LEDS_FAILED };
#define min_t(t,a,b) ((t)(a)<(t)(b)?(t)(a):(t)(b))
static unsigned long get_timer(unsigned long base) {return now-base;}
static u32 readl(uintptr_t addr) {
 if(addr==0xf4320100)return mux;
 if(addr==0xf43292c0)return dir;
 if(addr==0xf43292c4)return output;
 return input;
}
static void writel(u32 value,uintptr_t addr) {
 if(addr==0xf4320100)mux=value;
 if(addr==0xf43292c0)dir=value;
 if(addr==0xf43292c4){output=value;writes++;}
}
#define setbits_le32(a,b) writel(readl(a)|(b),a)
#define clrbits_le32(a,b) writel(readl(a)&~(b),a)
#define clrsetbits_le32(a,b,c) writel((readl(a)&~(b))|(c),a)
static void udelay(unsigned int us) {delay+=us;}
static void mdelay(unsigned int ms) {delay+=ms*1000;if(nframes<4)frames[nframes++]=output;}
'''
        tail = r'''
void reset(int two,u32 value,int pressed) {
 mux=dir=output=value;input=pressed?0:1U<<8;delay=nframes=0;
 variant=two==2?"unknown":two?"2p5g":"4ge";now=0;
 tyfza1_recovery_leds(TYFZA1_LEDS_OFF);mux=dir=output=value;
}
u32 at(unsigned long ms) {now=ms;tyfza1_recovery_leds_poll();return output;}
void leds(int state) {tyfza1_recovery_leds((enum tyfza1_leds)state);}
u32 metric(int key) {
 if(key==0)return mux;if(key==1)return dir;if(key==2)return output;
 if(key==3)return nframes;if(key==4)return delay;if(key==9)return writes;return frames[key-5];
}
'''
        path = work/'board.c'; path.write_text(prelude+body+tail)
        lib = work/'board.so'
        subprocess.run(['cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',
                        '-Wno-misleading-indentation',str(path),'-o',str(lib)],check=True)
        cls.lib=C.CDLL(str(lib));cls.lib.metric.restype=C.c_uint;cls.lib.at.restype=C.c_uint

    def test_common_lamps_light_in_order_and_original_registers_return(self):
        for two,pins,low in self.BOARDS:
            for seed in (0,0xa5a5a5a5,0xffffffff):
                self.lib.reset(two,seed,0);self.lib.tyfza1_boot_leds()
                mask=sum(1<<pin for pin in pins)
                self.assertEqual(self.lib.metric(3),2)
                self.assertEqual(self.lib.metric(4),300000)
                for i,pin in enumerate(pins):
                    frame=self.lib.metric(i+5)
                    self.assertEqual(frame & mask,low^(1<<pin))
                    self.assertEqual(frame & ~mask,seed & ~mask)
                for key in range(3):self.assertEqual(self.lib.metric(key),seed)

    def test_reset_active_low_sampling_changes_only_gpio8(self):
        for pressed in (0,1):
            self.lib.reset(1,0xa5a5a5a5,pressed)
            self.assertEqual(self.lib.tyfza1_reset_held(),pressed)
            self.assertEqual(self.lib.metric(0),0xa5a5a5a5|0x100)
            self.assertEqual(self.lib.metric(1),0xa5a5a5a5|0x100)
            self.assertEqual(self.lib.metric(2),0xa5a5a5a5)

    def lit(self,output,pins,low):
        return [i for i,pin in enumerate(pins) if (output^low)>>pin&1]

    def frames(self,pins,low,times):
        return [self.lit(self.lib.at(t),pins,low) for t in times]

    def test_held_heartbeat_upload_and_release(self):
        seed=0xa5a5a5a5
        for two,pins,low in self.BOARDS:
            mask=sum(1<<p for p in pins)
            self.lib.reset(two,seed,0)
            self.lib.leds(self.HELD)
            self.assertEqual(self.frames(pins,low,[0,5000]),[[0,1]]*2)
            self.assertEqual(self.lib.metric(1)&mask,0)
            self.lib.leds(self.IDLE)
            beat=self.frames(pins,low,[5000,5150,5300,5500,6900,7000])
            self.assertEqual(beat,[[0,1],[],[0,1],[],[],[0,1]])
            self.lib.leds(self.UPLOAD)
            self.assertEqual(self.frames(pins,low,[7000,7050,7100]),[[0],[],[0]])
            self.lib.leds(self.OFF)
            for key in range(3):self.assertEqual(self.lib.metric(key),seed)

    def test_two_stage_progress(self):
        self.lib.reset(0,0,0);pins,low=self.BOARDS[0][1:]
        self.lib.tyfza1_recovery_leds_busy(C.c_size_t(0),C.c_size_t(1000))
        self.assertEqual(self.frames(pins,low,[0,300]),[[0],[]])
        self.lib.tyfza1_recovery_leds_progress(C.c_size_t(600))
        self.assertEqual(self.frames(pins,low,[600,900]),[[0,1],[0]])
        self.lib.tyfza1_recovery_leds_progress(C.c_size_t(900))
        self.assertEqual(self.frames(pins,low,[1200,1500]),[[0,1],[0]])

    def test_results(self):
        for two,pins,low in self.BOARDS:
            self.lib.reset(two,0,0);self.lib.leds(self.IDLE);self.lib.leds(self.DONE)
            self.lib.leds(self.IDLE)  # does not cut the success lamp short
            self.assertEqual(self.frames(pins,low,[0,1999,2000,2150,2250]),[[0,1]]*3+[[],[0,1]])
            self.lib.leds(self.FAILED)
            self.assertEqual(self.frames(pins,low,[2250,2400,60150]),[[0],[1],[0]])
            self.lib.leds(self.IDLE)  # failure stays until the next upload or write
            self.assertEqual(self.frames(pins,low,[60300]),[[1]])
            self.lib.leds(self.UPLOAD)
            self.assertEqual(self.frames(pins,low,[60300]),[[0]])

    def test_unchanged_pattern_skips_gpio_writes(self):
        for state in (self.HELD,self.BUSY):
            self.lib.reset(0,0,0);self.lib.leds(state);before=self.lib.metric(9)
            for _ in range(50):self.lib.at(10)
            self.assertEqual(self.lib.metric(9),before)
        self.lib.reset(0,0,0);self.lib.leds(self.UPLOAD);before=self.lib.metric(9)
        self.lib.at(50);self.lib.at(100)
        self.assertEqual(self.lib.metric(9),before+2)

    def test_boot_sweep_skipped_while_recovery_owns_lamps(self):
        self.lib.reset(0,0,0);self.lib.leds(self.HELD);self.lib.tyfza1_boot_leds()
        self.assertEqual(self.lib.metric(3),0)

if __name__=='__main__':unittest.main()
