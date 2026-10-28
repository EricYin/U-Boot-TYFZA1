#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run lwIP error callback plus actual upload completion/busy functions."""
import ctypes as C
from pathlib import Path
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
class HttpAbortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        core=(ROOT/'build/u-boot/lib/lwip/lwip/src/apps/http/httpd.c').read_text()
        app=(ROOT/'build/u-boot/net/lwip/httpd.c').read_text()
        def body(text,start):
            at=text.index(start);return text[at:text.index('\n}',at)+2]
        pre=r'''
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
typedef unsigned short u16_t;
typedef int err_t;
typedef unsigned long ulong;
#define LWIP_UNUSED_ARG(x) (void)(x)
#define LWIP_DEBUGF(...) ((void)0)
#define LWIP_HTTPD_SUPPORT_POST 1
#define LWIP_HTTPD_POST_MANUAL_WND 0
#define LWIP_HTTPD_URI_BUF_LEN 64
struct http_state {unsigned int post_content_len_left;};
static char http_uri_buf[64] __attribute__((unused));
enum {HTTP_POST_NONE,HTTP_POST_UPLOAD,HTTP_POST_FLASH_ALL_UPLOAD,HTTP_POST_TASK};
enum {HTTP_JOB_IDLE,HTTP_JOB_QUEUED,HTTP_JOB_RUNNING};
static struct {void *connection;int kind;ulong load_addr;size_t expected,received;bool failed;} post_state;
static int job_result,job_state,parsed,freed;
static size_t output_len,buffer_size;
static char output_buf[64],storage_buf[64];
static ulong buffer_addr;
static unsigned int upload_id,task_id,downloads;
static bool backup_ready,flash_all_upload_ready;
static const char *phase;
static void http_state_free(struct http_state *hs){(void)hs;freed++;}
static void release_flash_all_upload(void){buffer_size=0;}
static void env_set_hex(const char *k,ulong v){(void)k;(void)v;}
static size_t strlcpy(char *dst,const char *src,size_t n){size_t len=strlen(src);if(n)snprintf(dst,n,"%s",src);return len;}
static int parse_task(void){parsed++;return 0;}
'''
        tail=r'''
int simulate(int kind,int owner){
 struct http_state hs={16},other={16};
 memset(&post_state,0,sizeof(post_state));post_state.connection=&hs;post_state.kind=kind;post_state.expected=32;post_state.received=16;
 job_state=HTTP_JOB_IDLE;parsed=freed=0;buffer_size=0;upload_id=3;phase="upload";
 http_err(owner?&hs:&other,-14);
 return http_busy();
}
int metric(int n){return n==0?parsed:n==1?(int)upload_id:n==2?freed:(int)buffer_size;}
'''
        work=ROOT/'build/http-abort-test';work.mkdir(parents=True,exist_ok=True)
        (work/'test.c').write_text(pre+body(app,'void httpd_post_finished(')+'\n'+body(app,'static bool http_busy(')+'\n'+body(core,'static void\nhttp_err(')+tail)
        subprocess.run(['cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',str(work/'test.c'),'-o',str(work/'test.so')],check=True)
        cls.lib=C.CDLL(str(work/'test.so'))
    def test_reset_mid_upload_or_task_releases_owner_without_queuing_partial_data(self):
        for kind in (1,3):
            self.assertEqual(self.lib.simulate(kind,1),0)
            self.assertEqual(self.lib.metric(0),0);self.assertEqual(self.lib.metric(1),3)
            self.assertEqual(self.lib.metric(2),1);self.assertEqual(self.lib.metric(3),0)
    def test_unrelated_connection_reset_keeps_current_upload_busy(self):
        self.assertEqual(self.lib.simulate(1,0),1)
        self.assertEqual(self.lib.metric(0),0)
if __name__=='__main__':unittest.main()
