// SPDX-License-Identifier: GPL-2.0-only
#undef env_set
#undef env_save
#undef run_command
static int do_tyfinstall(struct cmd_tbl *cmd,int flag,int argc,char *const argv[])
{
 static const char *names[]={"ubi_Config","ubi_fpga","ubi_DTB0","ubi_k0","ubi_r0","ubi_DTB1","ubi_k1","ubi_r1","ubi_framework1","ubi_framework2","ubi_apps","rootfs_data","tyfza1_factory","tyfza1_factory_backup"};
 ulong addr;size_t size;const void *input;int i,old,previous,ret,bytes_ok=0;
 unsigned int allowed;
 if(argc!=7)return CMD_RET_USAGE;
 addr=hextoul(argv[1],NULL);size=hextoul(argv[2],NULL);old=dectoul(argv[3],NULL);previous=simple_strtol(argv[4],NULL,10);fault=dectoul(argv[5],NULL);
 input=map_sysmem(addr,size);memset(&expected,0,sizeof(expected));tyf_parse_sysupgrade(input,size,&expected);
 memset(&dev,0,sizeof(dev));memset(vols,0,sizeof(vols));dev.leb_size=126976;
 changed=writes=save_calls=env_calls=0;selected_slot=previous>=0?previous:1-old;
 for(i=0;i<14;i++){
  free(stored[i]);stored[i]=NULL;lengths[i]=0;
  vols[i]=(struct ubi_volume){.ubi=&dev,.vol_id=i,.reserved_pebs=(i==4||i==7)?265:i==11?143:50,.usable_leb_size=126976};
  strlcpy(vols[i].name,names[i],sizeof(vols[i].name));dev.volumes[i]=&vols[i];
 }
 env_set("sw_commit",old?"1":"0");env_set("sw_active",old?"1":"0");env_set("sw_tryactive","2");env_set("tyfza1_slot",previous<0?NULL:previous?"1":"0");
 if(previous>=0 && expected.kernel.size){int id=previous?6:3;stored[id]=malloc(expected.kernel.size);if(!stored[id])return 1;memcpy(stored[id],expected.kernel.data,expected.kernel.size);lengths[id]=expected.kernel.size;}
 if(!strcmp(argv[6],"legacy"))env_set("tyfza1_slot",NULL);
 if(!strcmp(argv[6],"oem")){dev.volumes[12]=dev.volumes[13]=NULL;}
 if(!strcmp(argv[6],"wrong-id"))strcpy(vols[selected_slot?6:3].name,"other");
 if(!strcmp(argv[6],"readonly"))dev.ro_mode=1;
 if(!strcmp(argv[6],"low-space")){vols[11].reserved_pebs=0;vols[4].reserved_pebs=vols[7].reserved_pebs=1;}
 ret=tyfza1_install_system(addr,size,no_poll);
 if(!ret){int k=selected_slot?6:3,r=selected_slot?7:4;bytes_ok=lengths[k]==expected.kernel.size&&lengths[r]==expected.root.size&&!memcmp(stored[k],expected.kernel.data,lengths[k])&&!memcmp(stored[r],expected.root.data,lengths[r]);}
 allowed=(1U<<(selected_slot?6:3))|(1U<<(selected_slot?7:4))|(1U<<11);
 printf("TYF INSTALL ret=%d bytes=%d changed=%x isolated=%d saves=%u commit=%s active=%s trying=%s slot=%s conf=%s\n",ret,bytes_ok,changed,!(changed&~allowed),save_calls,env_get("sw_commit"),env_get("sw_active"),env_get("sw_tryactive"),env_get("tyfza1_slot")?:"none",tyfza1_boot_config()?:"none");
 unmap_sysmem(input);for(i=0;i<14;i++){free(stored[i]);stored[i]=NULL;}
 return 0;
}
U_BOOT_CMD(tyfinstall,7,0,do_tyfinstall,"test sysupgrade installation with RAM-backed UBI","");
