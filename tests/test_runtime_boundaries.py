#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute upload range and Ethernet startup error propagation boundaries."""
import ctypes as C
from pathlib import Path
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
def function(text,sig):
    a=text.index(sig);return text[a:text.index('\n}',a)+2]
class RuntimeBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        http=(ROOT/'build/u-boot/net/lwip/httpd.c').read_text()
        eth=(ROOT/'build/u-boot/net/eth-uclass.c').read_text()
        header=r'''
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <errno.h>
#include <string.h>
typedef unsigned long ulong;
typedef uint64_t phys_addr_t;
#define CONFIG_STACK_SIZE 0x1000000
#define CONFIG_TARGET_TYFZA1 1
#define min_t(t,a,b) ((t)(a)<(t)(b)?(t)(a):(t)(b))
#define debug(...) ((void)0)
#define log_err(...) ((void)0)
static struct {phys_addr_t ram_base,ram_size,start_addr_sp;} memory;
#define gd (&memory)
static bool tyf_http_upload_safe(ulong a,size_t n){(void)a;(void)n;return true;}
struct udevice {const char *name;};
static struct udevice dev={"NI"};
static bool in_init_halt;
static int eth_errno,start_error;
static char *env_get(const char *k){(void)k;return NULL;}
static struct udevice *eth_get_dev(void){return &dev;}
static struct udevice *eth_get_dev_by_name(const char *name){(void)name;return &dev;}
static int eth_start_udev(struct udevice *p){(void)p;return start_error;}
static void eth_try_another(int n){(void)n;}
'''
        lwip=(ROOT/'build/u-boot/net/lwip/net-lwip.c').read_text()
        wrappers=function(lwip,'int net_lwip_eth_start(')+function(lwip,'void net_lwip_eth_stop(')
        wrapper_stubs='''
static int net_lwip_eth_started,halts;
static void net_init(void){}
static void eth_halt(void){halts++;}
static void eth_set_current(void){}
'''
        tail=r'''
int range(ulong addr,size_t len,ulong stack){memory.ram_base=0;memory.ram_size=0x20000000;memory.start_addr_sp=stack;return upload_region_valid(addr,len);}
int start(int err,int old){start_error=err;eth_errno=old;in_init_halt=false;return eth_init();}
int recovery_start(int err){start_error=err;eth_errno=0;in_init_halt=false;return net_lwip_eth_start();}
void recovery_stop(void){net_lwip_eth_stop();}
int references(void){return net_lwip_eth_started;}
'''
        w=ROOT/'build/runtime-boundary-test';w.mkdir(parents=True,exist_ok=True)
        (w/'test.c').write_text(header+function(http,'static bool upload_region_valid(ulong addr, size_t len)\n{')+function(eth,'int eth_init(')+wrapper_stubs+wrappers+tail)
        subprocess.run(['cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',str(w/'test.c'),'-o',str(w/'test.so')],check=True)
        cls.lib=C.CDLL(str(w/'test.so'));cls.lib.range.argtypes=[C.c_ulong,C.c_size_t,C.c_ulong]
    def test_upload_cannot_overwrite_reserved_stack(self):
        stack=0x1d000000;limit=stack-0x1000000
        self.assertEqual(self.lib.range(0x10000000,limit-0x10000000,stack),1)
        self.assertEqual(self.lib.range(0x10000000,limit-0x10000000+1,stack),0)
        self.assertEqual(self.lib.range(stack-16,16,stack),0)
    def test_regular_firmware_and_restore_chunks_fit_without_reducing_default_limit(self):
        for size in (0x200000,0x400000,0x4000000):
            self.assertEqual(self.lib.range(0x10000000,size,0x1d000000),1)
    def test_invalid_and_overflowing_ranges_are_rejected(self):
        for addr,size,stack in [(0x10000000,0,0x1d000000),(0xfffffffffffffff0,32,0x1d000000),(0,1,0x1000)]:
            self.assertEqual(self.lib.range(addr,size,stack),0)
    def test_failed_driver_start_preserves_actual_error_not_probe_status(self):
        for err in (-5,-19,-110):
            for old in (0,-2):self.assertEqual(self.lib.start(err,old),err)
    def test_repeated_failed_recovery_then_success_has_no_reference_leak(self):
        for _ in range(100):
            self.assertEqual(self.lib.recovery_start(-5),-5)
            self.assertEqual(self.lib.references(),0)
        self.assertEqual(self.lib.recovery_start(0),0)
        self.assertEqual(self.lib.references(),1)
        self.lib.recovery_stop();self.assertEqual(self.lib.references(),0)
    def test_successful_start_remains_successful(self):
        self.assertEqual(self.lib.start(0,-19),0)
if __name__=='__main__':unittest.main()
