#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run explicit boot configuration and late init; no hardware identity is inferred."""
import ctypes as C
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

class BootConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        board = ROOT / 'overlay/board/realtek/tyfza1'
        config = '\n'.join(x for x in (board/'boot-config.c').read_text().splitlines() if not x.startswith('#include'))
        src = (board/'tyfza1.c').read_text()
        late = src[src.index('int board_late_init('):src.index('static int tyfza1_boot(')]
        prelude = r'''
#include <stdbool.h>
#include <string.h>
#include <errno.h>
#include <stddef.h>
#define PER_WDT_CTRL 0
#define GLOBAL_SCRATCH 1
#define DMA_SEC_SSP_FRAME_CTRL0 2
#define CONFIG_MTDIDS_DEFAULT "ids"
#define CONFIG_MTDPARTS_DEFAULT "parts"
#define TYFZA1_LEDS_HELD 1
static bool reset_requested;
static char chosen[32], inferred[32], variant[32], command[64];
static int failure, saved, writes;
static const char *env_get(const char *key) {
 if(!strcmp(key,"tyf_bootconf"))return chosen[0]?chosen:NULL;
 if(!strcmp(key,"b_conf"))return inferred[0]?inferred:NULL;
 if(!strcmp(key,"board_variant"))return variant[0]?variant:NULL;
 return NULL;
}
static int env_set(const char *key,const char *value) {
 char *dst=!strcmp(key,"tyf_bootconf")?chosen:!strcmp(key,"b_conf")?inferred:
 !strcmp(key,"board_variant")?variant:!strcmp(key,"bootcmd")?command:NULL;
 if(dst)strcpy(dst,value?value:"");return 0;
}
static int env_save(void){saved++;return failure?-EIO:0;}
static void writel(unsigned int x,unsigned long a){(void)x;(void)a;writes++;}
static void tyfza1_recovery_leds(int state){(void)state;}
'''
        tail = r'''
void reset(const char *conf,int fail) {
 strcpy(chosen,conf);strcpy(inferred,"conf-0");strcpy(variant,"2p5g");failure=fail;saved=writes=0;
}
int metric(int n){return n==0?saved:n==1?(!inferred[0]&&!variant[0]):n==2?writes:!strcmp(command,"bootmenu 3");}
'''
        work=ROOT/'build/boot-config-test';work.mkdir(exist_ok=True,parents=True)
        (work/'test.c').write_text(prelude+config+late+tail)
        subprocess.run(['cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',str(work/'test.c'),'-o',str(work/'test.so')],check=True)
        cls.lib=C.CDLL(str(work/'test.so'));cls.lib.reset.argtypes=[C.c_char_p,C.c_int]
        cls.lib.tyfza1_boot_config.restype=C.c_char_p
        cls.lib.tyfza1_save_boot_config.argtypes=[C.c_char_p]

    def test_old_auto_values_never_supply_configuration(self):
        self.lib.reset(b'',0);self.lib.board_late_init()
        self.assertIsNone(self.lib.tyfza1_boot_config())
        self.assertEqual(self.lib.metric(1),1)
        self.assertEqual(self.lib.metric(3),1)

    def test_each_explicit_configuration_survives_late_init(self):
        for conf in (b'conf-0',b'conf-1'):
            self.lib.reset(b'',0)
            self.assertEqual(self.lib.tyfza1_save_boot_config(conf),0)
            self.lib.board_late_init()
            self.assertEqual(self.lib.tyfza1_boot_config(),conf)
            self.assertEqual(self.lib.metric(0),1)
            self.assertEqual(self.lib.metric(2),4)

    def test_invalid_values_do_not_save(self):
        for conf in (b'',b'4ge',b'conf-2',b'conf-0;reset'):
            self.lib.reset(b'conf-1',0)
            self.assertEqual(self.lib.tyfza1_save_boot_config(conf),-22)
            self.assertEqual(self.lib.tyfza1_boot_config(),b'conf-1')
            self.assertEqual(self.lib.metric(0),0)

    def test_save_persists_a_selection_already_present_only_in_ram(self):
        self.lib.reset(b'conf-1',0)  # e.g. setenv from the console, without saveenv
        self.assertEqual(self.lib.tyfza1_save_boot_config(b'conf-1'),0)
        self.assertEqual(self.lib.metric(0),1)

    def test_same_value_save_still_reports_nand_failure(self):
        self.lib.reset(b'conf-1',1)
        self.assertEqual(self.lib.tyfza1_save_boot_config(b'conf-1'),-5)
        self.assertEqual(self.lib.tyfza1_boot_config(),b'conf-1')

    def test_save_failure_restores_previous_selection(self):
        for old in (b'',b'conf-1'):
            self.lib.reset(old,1)
            self.assertEqual(self.lib.tyfza1_save_boot_config(b'conf-0'),-5)
            self.assertEqual(self.lib.tyfza1_boot_config(),old or None)

if __name__=='__main__':unittest.main()
