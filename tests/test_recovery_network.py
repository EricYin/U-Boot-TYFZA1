#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run the prepared HTTP environment-save case with modeled env/DHCP calls."""
import ctypes as C
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]


class RecoveryNetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        http=(ROOT/'build/u-boot/net/lwip/httpd.c').read_text()
        begin=http.index('case HTTP_JOB_ENV:')
        case=http[begin:http.index('case HTTP_JOB_COMMAND:',begin)]
        work=ROOT/'build/network-policy-test';work.mkdir(parents=True,exist_ok=True)
        header=r'''
#include <string.h>
static char ip[64],mask[64],policy[64],env_key[64],env_value[64];
static int saved,stopped;
static int tyfza1_save_boot_config(const char *s){(void)s;return -22;}
static int env_set(const char *key,const char *value) {
 char *dst=!strcmp(key,"httpd_ipaddr")?ip:!strcmp(key,"httpd_netmask")?mask:!strcmp(key,"httpd_dhcp")?policy:0;
 if(dst){strncpy(dst,value?value:"",63);dst[63]=0;}return 0;
}
static int env_get_yesno(const char *key) {(void)key;return !strcmp(policy,"0")?0:1;}
static int env_save(void) {saved++;return 0;}
static void uboot_httpd_dhcp_stop(void) {stopped++;}
#define HTTP_JOB_ENV 1
int run(const char *key,const char *value) {
 int ret=0;saved=stopped=0;strcpy(env_key,key);strcpy(env_value,value);
 switch(1) {
'''
        tail='''default:break; } return ret; }
const char *setting(int key) {return key==0?ip:key==1?mask:policy;}
int metric(int key) {return key?saved:stopped;}
'''
        path=work/'network.c';path.write_text(header+case+tail);lib=work/'network.so'
        subprocess.run(['cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',str(path),'-o',str(lib)],check=True)
        cls.lib=C.CDLL(str(lib));cls.lib.run.argtypes=[C.c_char_p,C.c_char_p]
        cls.lib.setting.restype=C.c_char_p
        cls.http=http

    def test_static_ip_and_mask_persist_as_recovery_settings(self):
        for key,value,index in [(b'ipaddr',b'192.168.9.1',0),(b'netmask',b'255.255.255.0',1)]:
            self.assertEqual(self.lib.run(key,value),0)
            self.assertEqual(self.lib.setting(index),value)
            self.assertEqual(self.lib.metric(1),1)

    def test_disable_dhcp_takes_effect_immediately_and_is_saved(self):
        self.assertEqual(self.lib.run(b'httpd_dhcp',b'0'),0)
        self.assertEqual(self.lib.metric(0),1)
        self.assertEqual(self.lib.metric(1),1)
        self.assertEqual(self.lib.setting(2),b'0')

    def test_explicit_httpd_dhcp_also_honors_saved_disabled_setting(self):
        self.assertIn('if (env_get_yesno("httpd_dhcp") == 0) with_dhcp = false;',self.http)


if __name__=='__main__':unittest.main()
