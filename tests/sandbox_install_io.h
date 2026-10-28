/* SPDX-License-Identifier: GPL-2.0-only */
/* Replace only UBI/env persistence I/O; run actual parser, FIT and install code. */
#include <command.h>
#include <env.h>
#include <image.h>
#include <malloc.h>
#include <mapmem.h>
#include <stdio.h>
#include <string.h>
#include <vsprintf.h>
#include <linux/libfdt.h>
#include <linux/err.h>
#include <tyfza1_recovery.h>
#include "formats.h"
#define UBI_EXCLUSIVE 1
#define malloc_cache_aligned malloc
struct ubi_device;
struct ubi_volume {struct ubi_device *ubi;int vol_id,reserved_pebs,usable_leb_size;char name[32];};
struct ubi_device {int ubi_num,avail_pebs,leb_size,ro_mode,beb_rsvd_level,beb_rsvd_pebs;struct ubi_volume *volumes[128];};
struct ubi_volume_desc {struct ubi_volume *vol;};
static struct ubi_device dev,*ubi_devices[]={&dev};
static struct ubi_volume vols[14];
static struct ubi_volume_desc desc;
static unsigned char *stored[14];
static size_t lengths[14];
static unsigned int changed,writes,save_calls,env_calls;
static int fault,selected_slot;
static struct tyf_firmware expected;
static struct ubi_volume *find_volume(const char *name){int i;for(i=0;i<14;i++)if(dev.volumes[i]&&!strcmp(name,vols[i].name))return &vols[i];return NULL;}
static int ubi_part(char *name,const char *vid){return strcmp(name,"ubi_device");}
static int ubi_volume_get_size(const char *name,size_t *used,size_t *capacity){struct ubi_volume *v=find_volume(name);if(!v)return -ENOENT;if(used)*used=lengths[v->vol_id];if(capacity)*capacity=(size_t)v->reserved_pebs*v->usable_leb_size;return 0;}
static int ubi_volume_read_quiet(char *name,char *out,loff_t off,size_t n){
 struct ubi_volume *v=find_volume(name);int id=v?v->vol_id:-1;
 if(id<0 || off<0 || off>lengths[id] || n>lengths[id]-off)return -EIO;
 if(writes && ((fault==2 && (id==4||id==7))||(fault==4 && (id==3||id==6))))return -EIO;
 memcpy(out,stored[id]+off,n);if(writes && fault==8 && n && (id==3||id==6))out[0]^=1;return 0;
}
static int ubi_volume_write(char *name,void *in,loff_t off,size_t n){
 struct ubi_volume *v=find_volume(name);int id=v?v->vol_id:-1;
 if(id<0 || off || n>(size_t)v->reserved_pebs*v->usable_leb_size)return -EINVAL;
 if((fault==1 && (id==4||id==7))||(fault==3 && (id==3||id==6)))return -EIO;
 free(stored[id]);stored[id]=malloc(n);if(!stored[id])return -ENOMEM;
 memcpy(stored[id],in,n);lengths[id]=n;changed|=1U<<id;writes++;return 0;
}
static struct ubi_volume_desc *ubi_open_volume(int num,int id,int mode){desc.vol=&vols[id];return &desc;}
static void ubi_close_volume(struct ubi_volume_desc *d){}
static int ubi_resize_volume(struct ubi_volume_desc *d,int count){int delta=count-d->vol->reserved_pebs;if(delta>dev.avail_pebs)return -ENOSPC;if(fault==6)return -EIO;dev.avail_pebs-=delta;d->vol->reserved_pebs=count;return 0;}
static int ubi_volume_remove(const char *name){struct ubi_volume *v=find_volume(name);if(!v)return -ENOENT;changed|=1U<<v->vol_id;dev.avail_pebs+=v->reserved_pebs;dev.volumes[v->vol_id]=NULL;return 0;}
static int fixture_command(const char *cmd,int flag){
 if(strcmp(cmd,"ubi create rootfs_data 0 d b"))return -EINVAL;
 if(fault==5)return -EIO;
 dev.volumes[11]=&vols[11];vols[11].reserved_pebs=dev.avail_pebs;dev.avail_pebs=0;changed|=1U<<11;return 0;
}
static int fixture_env_set(const char *key,const char *value){env_calls++;if(fault>=10 && fault<=13 && env_calls==(unsigned int)fault-9)return -ENOMEM;return env_set(key,value);}
static int fixture_env_save(void){save_calls++;return fault==7?-EIO:0;}
static int verify_fit(const struct tyf_payload *image){return tyfza1_check_fit(map_to_sysmem(image->data),image->size);}
int fixture_verify_system(const struct tyf_payload *p);
static int verify_system_fit(const struct tyf_payload *p){return fixture_verify_system(p);}
static void no_poll(void){}
#define env_set fixture_env_set
#define env_save fixture_env_save
#define run_command fixture_command
