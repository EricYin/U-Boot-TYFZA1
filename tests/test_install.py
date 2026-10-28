#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run the system installer with a real sysupgrade parser and modeled UBI/env I/O."""
import ctypes as C
import io
from pathlib import Path
import subprocess
import struct
import tarfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
class InstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=(ROOT/'overlay/board/realtek/tyfza1/recovery.c').read_text()
        body=source[source.index('static int resize_root('):source.index('static int read_mtd(')]
        work=ROOT/'build/install-test';work.mkdir(parents=True,exist_ok=True)
        prelude=r'''#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
#include <libfdt.h>
#include "formats.h"
#define UBI_EXCLUSIVE 1
#define IS_ERR(p) 0
#define PTR_ERR(p) (-EINVAL)
#define DIV_ROUND_UP(a,b) (((a)+(b)-1)/(b))
struct ubi_device;
struct ubi_volume { struct ubi_device *ubi; int vol_id, reserved_pebs, usable_leb_size; char name[24]; };
struct ubi_device { int ubi_num, avail_pebs, leb_size, ro_mode, beb_rsvd_level, beb_rsvd_pebs; struct ubi_volume *volumes[128]; };
struct ubi_volume_desc { struct ubi_volume *vol; };
static struct ubi_device device, *ubi_devices[]={&device};
static struct ubi_volume vols[128];
static struct ubi_volume_desc desc;
static char commit[2], active[2], trying[2], installed[2];
static int save_fail, last_slot, writes;
static unsigned char old_fits[2][4096];
static int read_fail;
#define malloc_cache_aligned malloc
typedef unsigned long ulong;
static void *map_sysmem(ulong addr,size_t size) { (void)size;return (void *)addr; }
static void unmap_sysmem(const void *addr) { (void)addr; }
static const char *env_get(const char *name) {
 if(!strcmp(name,"sw_commit"))return commit;
 if(!strcmp(name,"sw_active"))return active;
 if(!strcmp(name,"sw_tryactive"))return trying;
 if(!strcmp(name,"tyfza1_slot"))return installed[0]?installed:NULL;
 return NULL;
}
static int env_set(const char *name,const char *value) {
 char *p=!strcmp(name,"sw_commit")?commit:!strcmp(name,"sw_active")?active:!strcmp(name,"sw_tryactive")?trying:installed;
 p[0]=value?value[0]:0;p[1]=0;return 0;
}
static int env_save(void) { return save_fail?-EIO:0; }
int tyfza1_check_sysupgrade(const void *p,size_t n,bool *v,void (*poll)(void)){(void)p;(void)n;*v=true;poll();return 0;}
static int verify_fit(const struct tyf_payload *p) { return p->size?0:-EINVAL; }
static int verify_system_fit(const struct tyf_payload *p) {return verify_fit(p);}
static int ubi_part(const char *p,const char *v) { (void)v;return strcmp(p,"ubi_device"); }
static struct ubi_volume *find(const char *name) {
 for(int i=0;i<128;i++)if(device.volumes[i]&&!strcmp(name,vols[i].name))return &vols[i];
 return NULL;
}
static int ubi_volume_get_size(const char *name,size_t *used,size_t *capacity) {
 struct ubi_volume *v=find(name);if(!v)return -ENOENT;
 if(used)*used=(size_t)v->reserved_pebs*v->usable_leb_size;
 if(capacity)*capacity=(size_t)v->reserved_pebs*v->usable_leb_size;
 return 0;
}
static int ubi_volume_read_quiet(const char *name,char *buffer,size_t off,size_t size) {
 int slot=!strcmp(name,"ubi_k1");
 if(read_fail || off+size>sizeof(old_fits[slot])) return -EIO;
 memcpy(buffer,old_fits[slot]+off,size);return 0;
}
static struct ubi_volume_desc *ubi_open_volume(int n,int id,int mode) { (void)n;(void)mode;desc.vol=&vols[id];return &desc; }
static int ubi_resize_volume(struct ubi_volume_desc *d,int lebs) {
 device.avail_pebs+=d->vol->reserved_pebs-lebs;d->vol->reserved_pebs=lebs;return 0;
}
static void ubi_close_volume(struct ubi_volume_desc *d) { (void)d; }
static int ubi_volume_remove(const char *name) {
 struct ubi_volume *v=find(name);if(!v)return -ENOENT;
 device.avail_pebs+=v->reserved_pebs;device.volumes[v->vol_id]=NULL;return 0;
}
static int run_command(const char *command,int flags) {
 (void)flags;if(strcmp(command,"ubi create rootfs_data 0 d b"))return -EINVAL;
 vols[11]=(struct ubi_volume){.ubi=&device,.vol_id=11,.reserved_pebs=device.avail_pebs,.usable_leb_size=126976};
 strcpy(vols[11].name,"rootfs_data");device.volumes[11]=&vols[11];device.avail_pebs=0;return 0;
}
static int ubi_volume_write(char *name,const void *data,size_t off,size_t length) {
 (void)data;(void)off;(void)length;
 if(!strcmp(name,"ubi_k0"))last_slot=0;
 if(!strcmp(name,"ubi_k1"))last_slot=1;
 writes++;return find(name)?0:-ENOENT;
}
static int volume_verify(char *name,const void *data,size_t length,void (*poll)(void)) {
 (void)data;(void)length;poll();return find(name)?0:-ENOENT;
}
'''
        tail=r'''
static void no_poll(void) {}
void test_reset(int committed,int previous,int fail) {
 memset(&device,0,sizeof(device));memset(vols,0,sizeof(vols));
 device.leb_size=126976;
 int ids[]={3,4,6,7,11},sizes[]={50,265,50,265,143};
 const char *names[]={"ubi_k0","ubi_r0","ubi_k1","ubi_r1","rootfs_data"};
 for(int i=0;i<5;i++) {
  struct ubi_volume *v=&vols[ids[i]];v->ubi=&device;v->vol_id=ids[i];v->reserved_pebs=sizes[i];v->usable_leb_size=126976;
  strcpy(v->name,names[i]);device.volumes[ids[i]]=v;
 }
 commit[0]=active[0]='0'+committed;trying[0]='2';installed[0]=previous<0?0:'0'+previous;
 commit[1]=active[1]=trying[1]=installed[1]=0;save_fail=fail;writes=0;last_slot=-1;
 memset(old_fits,0xff,sizeof(old_fits));read_fail=0;
}
void test_old_fit(int slot,int native) {
 fdt_create_empty_tree(old_fits[slot],sizeof(old_fits[slot]));
 fdt_setprop_string(old_fits[slot],0,"description",native?"TYFZA1 native SIGNED boot-contract candidate":"OEM Taurus");
 fdt_pack(old_fits[slot]);
}
void test_read_failure(void) { read_fail=1; }
int test_install(const void *data,size_t size) { return tyfza1_install_system((ulong)data,size,no_poll); }
int test_state(int key) {
 if(key==0)return last_slot;if(key==1)return installed[0]?installed[0]-'0':-1;
 if(key==2)return commit[0]-'0';if(key==3)return vols[4].reserved_pebs;
 if(key==4)return vols[7].reserved_pebs;if(key==5)return vols[11].reserved_pebs;
 return writes;
}
'''
        cfile=work/'install.c';cfile.write_text(prelude+body+tail)
        lib=work/'install.so';board=ROOT/'overlay/board/realtek/tyfza1'
        fdt=ROOT/'build/u-boot/scripts/dtc/libfdt'
        subprocess.run(['cc','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-I'+str(board),'-I'+str(fdt),str(cfile),str(board/'formats.c'),*[str(p) for p in fdt.glob('fdt*.c')],'-o',str(lib)],check=True)
        cls.lib=C.CDLL(str(lib));cls.lib.test_install.argtypes=[C.c_void_p,C.c_size_t]
        stream=io.BytesIO()
        root=bytearray(8*1024*1024);root[:4]=b'hsqs';struct.pack_into('<Q',root,40,len(root))
        with tarfile.open(fileobj=stream,mode='w',format=tarfile.USTAR_FORMAT) as archive:
            for name,data in [('CONTROL',b'BOARD=tianyi_tyfza1\n'),('kernel',b'\xd0\x0d\xfe\xed'+bytes(1000)),('root',root)]:
                info=tarfile.TarInfo('sysupgrade-tianyi_tyfza1/'+name);info.size=len(data);archive.addfile(info,io.BytesIO(data))
        cls.data=stream.getvalue();cls.buffer=C.create_string_buffer(cls.data)

    def install(self):return self.lib.test_install(self.buffer,len(self.data))
    def state(self,key):return self.lib.test_state(key)
    def test_first_install_selects_other_slot_and_records_it(self):
        for committed in [0,1]:
            self.lib.test_reset(committed,-1,0);self.assertEqual(self.install(),0)
            self.assertEqual(self.state(0),1-committed);self.assertEqual(self.state(1),1-committed)
    def test_reinstall_preserves_original_factory_slot(self):
        self.lib.test_reset(1,1,0);self.assertEqual(self.install(),0)
        self.assertEqual(self.state(0),1);self.assertEqual(self.state(3),265)
        self.assertLess(self.state(4),265);self.assertGreater(self.state(5),300)
        self.assertEqual(self.install(),0);self.assertEqual(self.state(0),1);self.assertEqual(self.state(3),265)
    def test_environment_failure_restores_slot_marker(self):
        self.lib.test_reset(0,-1,1);self.assertNotEqual(self.install(),0)
        self.assertEqual(self.state(1),-1);self.assertEqual(self.state(2),0)
    def test_invalid_slot_marker_prevents_writes(self):
        self.lib.test_reset(0,2,0);self.assertNotEqual(self.install(),0);self.assertEqual(self.state(6),0)
    def test_legacy_install_without_marker_preserves_oem_slot(self):
        for slot in (0,1):
            self.lib.test_reset(slot,-1,0)
            self.lib.test_old_fit(slot,1);self.lib.test_old_fit(1-slot,0)
            self.assertEqual(self.install(),0)
            self.assertEqual(self.state(0),slot);self.assertEqual(self.state(1),slot)
    def test_existing_openwrt_detected_even_if_oem_is_committed(self):
        self.lib.test_reset(0,-1,0);self.lib.test_old_fit(1,1)
        self.assertEqual(self.install(),0);self.assertEqual(self.state(0),1)
    def test_read_failure_stops_before_any_write(self):
        self.lib.test_reset(0,-1,0);self.lib.test_read_failure()
        self.assertNotEqual(self.install(),0);self.assertEqual(self.state(6),0)
if __name__=='__main__':unittest.main()
