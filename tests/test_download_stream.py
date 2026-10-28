#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read physical/UBI download bytes using the production streaming function."""
import ctypes as C
from pathlib import Path
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
class DownloadStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text=(ROOT/'build/u-boot/net/lwip/httpd.c').read_text();a=text.index('int fs_read_custom(');code=text[a:text.index('\n}',a)+2]
        pre=r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint64_t u64;
#define min(a,b) ((a)<(b)?(a):(b))
#define min_t(t,a,b) min((t)(a),(t)(b))
#define round_down(x,y) ((x)/(y)*(y))
#define CONFIG_IS_ENABLED(x) 1
#define FS_READ_EOF (-1)
struct mtd_info {size_t erasesize;};
struct fs_file {int index,len;void *pextension;};
struct http_file {bool download;struct mtd_info *mtd;char header[64];size_t header_len,download_offset,download_size,cache_size,cache_offset;void *cache;};
static struct {u64 offset;char target[32];} backup_request;
static int job_result,calls,fault,bad_block;
static char output_buf[64];
static struct fs_file file;
static struct http_file owner;
static struct mtd_info nand={0x20000};
static unsigned char cache[32768];
static size_t strlcpy(char *d,const char *s,size_t n){if(n)snprintf(d,n,"%s",s);return strlen(s);}
static unsigned char byte_at(size_t i){return i%251;}
static int mtd_block_isbad(struct mtd_info *m,u64 off){(void)m;return off/0x20000==(u64)bad_block;}
static int mtd_read(struct mtd_info *m,u64 off,size_t n,size_t *done,void *buf){
 (void)m;calls++;if(fault==2)return -EIO;*done=fault==3?n-1:n;
 for(size_t i=0;i<*done;i++)((unsigned char*)buf)[i]=byte_at(off+i);
 return fault==1?-EUCLEAN:0;
}
static int ubi_volume_read_quiet(char *v,void *buf,size_t off,size_t n){
 (void)v;calls++;if(fault)return -EIO;
 for(size_t i=0;i<n;i++)((unsigned char*)buf)[i]=byte_at(off+i);return 0;
}
'''
        tail=r'''
void setup(int raw,size_t base,size_t offset,size_t size,int bad,int err){
 owner=(struct http_file){.download=true,.mtd=raw?&nand:NULL,.header="HEADER",.header_len=6,.download_offset=offset,.download_size=size,.cache=cache};
 file=(struct fs_file){0,(int)size+6,&owner};backup_request.offset=base;calls=job_result=0;fault=err;bad_block=bad;
}
int read_data(void *out,int n){return fs_read_custom(&file,out,n);}
int metric(int n){return n==0?calls:n==1?file.index:job_result;}
'''
        w=ROOT/'build/download-stream-test';w.mkdir(exist_ok=True,parents=True);(w/'test.c').write_text(pre+code+tail)
        subprocess.run(['cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror','-Wno-sign-compare','-Wno-misleading-indentation',str(w/'test.c'),'-o',str(w/'test.so')],check=True)
        cls.lib=C.CDLL(str(w/'test.so'));cls.lib.setup.argtypes=[C.c_int,C.c_size_t,C.c_size_t,C.c_size_t,C.c_int,C.c_int];cls.lib.read_data.argtypes=[C.c_void_p,C.c_int]
    def collect(self):
        result=bytearray();buf=C.create_string_buffer(5000)
        while (n:=self.lib.read_data(buf,len(buf)))>=0:
            self.assertGreater(n,0);result.extend(buf.raw[:n])
        return bytes(result)
    def test_mtd_bad_block_preserves_physical_offsets_across_boundaries(self):
        size=0x43000;base=0x800;offset=0x1f000
        self.lib.setup(1,base,offset,size,2,0)
        data=self.collect();start=base+offset
        expected=bytes(255 if (start+i)//0x20000==2 else (start+i)%251 for i in range(size))
        self.assertEqual(data,b'HEADER'+expected);self.assertEqual(self.lib.metric(2),0)
    def test_ubi_cache_crossing_and_nonzero_download_segment_offset(self):
        size=100001;offset=0x400000
        self.lib.setup(0,0,offset,size,-1,0)
        self.assertEqual(self.collect(),b'HEADER'+bytes((offset+i)%251 for i in range(size)))
        self.assertEqual(self.lib.metric(0),4)
    def test_corrected_ecc_is_readable_but_short_or_failed_reads_never_advance(self):
        self.lib.setup(1,0,0,100,-1,1)
        self.assertEqual(len(self.collect()),106)
        for raw,err in ((1,2),(1,3),(0,2)):
            self.lib.setup(raw,0,0,100,-1,err)
            self.assertEqual(self.collect(),b'HEADER')
            self.assertEqual(self.lib.metric(1),6);self.assertEqual(self.lib.metric(2),-5)
if __name__=='__main__':unittest.main()
