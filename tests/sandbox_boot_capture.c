// SPDX-License-Identifier: GPL-2.0-only
#include <command.h>
#include <env.h>
#include <stdio.h>
static int do_tyfcapture(struct cmd_tbl *cmd,int flag,int argc,char *const argv[])
{
 if(argc!=2)return CMD_RET_USAGE;
 printf("TYF HANDOFF image=%s root=%s block=%s slot=%s args=%s\n",argv[1],env_get("tyfza1_root")?:"",env_get("tyfza1_block")?:"",env_get("tyfza1_slot")?:"",env_get("bootargs")?:"");
 return 0;
}
U_BOOT_CMD(tyfcapture,2,0,do_tyfcapture,"capture the Linux handoff instead of booting","");
