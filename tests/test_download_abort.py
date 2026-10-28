#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run real lwIP RST callback and application's download resource release."""
import ctypes as C
from pathlib import Path
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
def body(text,sig):
    a=text.index(sig);return text[a:text.index('\n}',a)+2]
class DownloadAbortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app=(ROOT/'build/u-boot/net/lwip/httpd.c').read_text()
        core=(ROOT/'build/u-boot/lib/lwip/lwip/src/apps/http/httpd.c').read_text()
        p=r'''
#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
typedef int err_t;
typedef unsigned char u8_t;
#define LWIP_UNUSED_ARG(x) (void)(x)
#define LWIP_DEBUGF(...) ((void)0)
#define LWIP_HTTPD_SUPPORT_POST 1
#define LWIP_HTTPD_CUSTOM_FILES 1
#define LWIP_HTTPD_URI_BUF_LEN 64
#define FS_FILE_FLAGS_CUSTOM 2
struct fs_file {int index,len,flags;void *pextension;};
struct http_state {unsigned int post_content_len_left;struct fs_file *handle;unsigned int left;};
struct http_file {bool download,reply;void *mtd,*allocation,*cache;size_t download_offset,download_size;};
static struct {size_t size;} backup_request;
static unsigned int downloads,replies;
static bool backup_ready;
static unsigned long backup_at;
static const char *phase;
static char http_uri_buf[64];
struct altcp_pcb {unsigned int queued;};
#define ERR_OK 0
#define HTTPD_POLL_INTERVAL 4
static unsigned int altcp_sndqueuelen(struct altcp_pcb *p){return p->queued;}
#define altcp_arg(p,fn) ((void)(p),(void)(fn))
#define altcp_recv(p,fn) ((void)(p),(void)(fn))
#define altcp_err(p,fn) ((void)(p),(void)(fn))
#define altcp_poll(p,fn,n) ((void)(p),(void)(n))
#define altcp_sent(p,fn) ((void)(p),(void)(fn))
static void altcp_abort(struct altcp_pcb *p){(void)p;}
static int altcp_close(struct altcp_pcb *p){(void)p;return 0;}
static int refs,posts;
static void put_mtd_device(void *p){(void)p;refs--;}
static unsigned long get_timer(unsigned long n){return 100-n;}
static void httpd_post_finished(void *hs,char *uri,int n){(void)hs;(void)uri;(void)n;posts++;}
'''
        mid=r'''
static void http_state_free(struct http_state *hs){fs_close_custom(hs->handle);}
'''
        tail=r'''
int run(int abort,int final,int prefetched){
 struct http_file *owner=calloc(1,sizeof(*owner));
 owner->download=true;owner->mtd=owner;owner->cache=malloc(32);owner->download_size=4096;
 owner->download_offset=final?4096:0;
 struct fs_file file={prefetched?4200:100,4200,FS_FILE_FLAGS_CUSTOM,owner};
 struct http_state hs={.handle=&file};
 struct altcp_pcb pcb={abort>=2?1:0};
 downloads=refs=1;posts=0;backup_ready=true;backup_request.size=8192;phase="download";
 if(abort==1)http_err(&hs,-14);
 else http_close_or_abort_conn(&pcb,&hs,abort==3);
 return backup_ready;
}
int metric(int n){return n==0?(int)downloads:n==1?refs:n==2?posts:!strcmp(phase,"error");}
'''
        w=ROOT/'build/download-abort-test';w.mkdir(exist_ok=True,parents=True)
        (w/'test.c').write_text(p+body(app,'void fs_close_custom(')+mid+body(core,'static void\nhttp_err(')+body(core,'static err_t\nhttp_close_or_abort_conn(')+tail)
        subprocess.run(['cc','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror',str(w/'test.c'),'-o',str(w/'test.so')],check=True)
        cls.lib=C.CDLL(str(w/'test.so'))
    def test_rst_after_prefetch_releases_session_and_reports_error(self):
        for last in (0,1):
            self.assertEqual(self.lib.run(1,last,1),0)
            self.assertEqual(self.lib.metric(3),1)
            self.assertEqual(self.lib.metric(0),0);self.assertEqual(self.lib.metric(1),0)
    def test_timeout_and_service_shutdown_do_not_report_prefetched_data_as_complete(self):
        for reason in (2,3):
            self.assertEqual(self.lib.run(reason,0,1),0)
            self.assertEqual(self.lib.metric(3),1)
            self.assertEqual(self.lib.metric(0),0);self.assertEqual(self.lib.metric(1),0)

    def test_acknowledged_intermediate_segment_keeps_backup_ready(self):
        self.assertEqual(self.lib.run(0,0,1),1)
    def test_acknowledged_last_segment_finishes_backup(self):
        self.assertEqual(self.lib.run(0,1,1),0)
        self.assertEqual(self.lib.metric(3),0)
if __name__=='__main__':unittest.main()
