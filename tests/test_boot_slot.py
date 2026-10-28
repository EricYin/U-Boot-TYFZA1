#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute normal boot against bounded UBI data with the pinned reader's bounds."""
import ctypes as C
from pathlib import Path
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
class BootSlotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text=(ROOT/'overlay/board/realtek/tyfza1/tyfza1.c').read_text()
        body=text[text.index('static int tyfza1_boot('):text.index('U_BOOT_CMD(tyfboot')]
        pre=r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include <stdarg.h>
#include <errno.h>
#include <libfdt.h>
#define CMD_RET_FAILURE 1
#define FIT_FDT_PROP "fdt"
typedef unsigned long ulong;
struct cmd_tbl {int unused;};
static unsigned char image[0x600000],ram[0x600000];
static size_t used,requested;
static int read_error,checked,sourced,env_error,fit_error;
static char committed[16],conf[16],selected_volume[16],b_conf[16];
static const char *env_get(const char *key){if(!strcmp(key,"sw_commit"))return committed[0]?committed:NULL;return NULL;}
static const char *tyfza1_boot_config(void){return conf[0]?conf:NULL;}
static int env_set(const char *key,const char *val){if(env_error)return -ENOMEM;if(!strcmp(key,"b_conf"))strcpy(b_conf,val);return 0;}
static int env_set_hex(const char *key,ulong val){(void)key;(void)val;return env_error?-ENOMEM:0;}
static int ubi_part(const char *p,const char *v){(void)p;(void)v;return 0;}
static int ubi_volume_get_size(const char *v,size_t *n,size_t *capacity){strcpy(selected_volume,v);if(n)*n=used;if(capacity)*capacity=sizeof(ram);return 0;}
static void *map_sysmem(ulong a,size_t n){(void)a;(void)n;return ram;}
static void unmap_sysmem(const void *p){(void)p;}
static int ubi_volume_read_quiet(char *v,char *buf,long off,size_t n){
 strcpy(selected_volume,v);requested=n;
 if(read_error)return EIO;
 if(off<0 || (size_t)off>used || n>used-off)return EINVAL;
 memcpy(buf,image+off,n);return 0;
}
static int tyfza1_check_fit(ulong addr,size_t n){(void)addr;checked++;return fit_error || n!=fdt_totalsize(image)?-EINVAL:0;}
static int run_command(const char *cmd,int flags){(void)cmd;(void)flags;sourced++;return 0;}
static int run_commandf(const char *fmt,...){
 va_list ap;va_start(ap,fmt);char cmd[160];vsnprintf(cmd,sizeof(cmd),fmt,ap);va_end(ap);
 char name[16];unsigned long addr,n;
 if(sscanf(cmd,"ubi read %lx %15s %lx",&addr,name,&n)==3)return ubi_volume_read_quiet(name,(char*)ram,0,n);
 sourced++;return 0;
}
'''
        tail=r'''
int boot(const char *slot,size_t volume_size,size_t fit_size,int err,int bad_magic,int env_fail){
 used=volume_size;requested=0;read_error=err;checked=sourced=0;env_error=env_fail;
 strcpy(committed,slot);strcpy(conf,"conf-1");selected_volume[0]=b_conf[0]=0;
 memset(image,0,sizeof(image));struct fdt_header *h=(void*)image;h->magic=cpu_to_fdt32(bad_magic?0:FDT_MAGIC);h->totalsize=cpu_to_fdt32(fit_size);
 return tyfza1_boot(NULL,0,0,NULL);
}
void fail_fit(int v){fit_error=v;}
size_t metric(int k){return k==0?requested:k==1?(size_t)checked:k==2?(size_t)sourced:!strcmp(selected_volume,"ubi_k1");}
'''
        work=ROOT/'build/boot-slot-test';work.mkdir(parents=True,exist_ok=True)
        (work/'test.c').write_text(pre+body+tail)
        subprocess.run(['cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-parameter','-I'+str(ROOT/'sources/uboot-an758x/scripts/dtc/libfdt'),str(work/'test.c'),'-o',str(work/'test.so')],check=True)
        cls.lib=C.CDLL(str(work/'test.so'));cls.lib.boot.argtypes=[C.c_char_p,C.c_size_t,C.c_size_t,C.c_int,C.c_int,C.c_int];cls.lib.metric.restype=C.c_size_t
    def test_short_static_kernel_volume_boots_exact_fit_length(self):
        self.assertEqual(self.lib.boot(b'1',0x180000,0x180000,0,0,0),0)
        self.assertEqual(self.lib.metric(0),0x180000);self.assertEqual(self.lib.metric(1),1);self.assertEqual(self.lib.metric(2),1)
        self.assertEqual(self.lib.metric(3),1)
    def test_dynamic_volume_does_not_require_reading_reserved_padding(self):
        self.assertEqual(self.lib.boot(b'0',0x60e000,0x190000,0,0,0),0)
        self.assertEqual(self.lib.metric(0),0x190000);self.assertEqual(self.lib.metric(1),1)
    def test_corrupt_header_and_truncated_data_never_execute(self):
        for used,size,bad in [(0x1000,0x2000,0),(0x60e000,0x700000,0),(0x1000,8,0),(0x60e000,0x180000,1)]:
            self.assertNotEqual(self.lib.boot(b'0',used,size,0,bad,0),0)
            self.assertEqual(self.lib.metric(2),0)
    def test_fit_verification_failure_never_executes_script(self):
        self.lib.fail_fit(1)
        try:
            self.assertNotEqual(self.lib.boot(b'0',0x60e000,0x180000,0,0,0),0)
            self.assertEqual(self.lib.metric(2),0)
        finally:self.lib.fail_fit(0)

    def test_read_error_and_invalid_slot_never_execute(self):
        for slot,err in [(b'0',1),(b'2',0)]:
            self.assertNotEqual(self.lib.boot(slot,0x60e000,0x180000,err,0,0),0)
            self.assertEqual(self.lib.metric(2),0)
    def test_environment_failure_never_executes(self):
        self.assertNotEqual(self.lib.boot(b'1',0x60e000,0x180000,0,0,1),0)
        self.assertEqual(self.lib.metric(2),0)
if __name__=='__main__':unittest.main()
