// SPDX-License-Identifier: GPL-2.0-only
#include <command.h>
#include <stdio.h>
#include <vsprintf.h>
int tyfza1_check_fit(ulong address, size_t size);
static int do_tyffit(struct cmd_tbl *cmd, int flag, int argc, char *const argv[])
{
	int ret;
	if (argc != 3) return CMD_RET_USAGE;
	ret = tyfza1_check_fit(hextoul(argv[1], NULL), hextoul(argv[2], NULL));
	printf("TYF FIT %s (%d)\n", ret ? "REJECT" : "OK", ret);
	return ret ? CMD_RET_FAILURE : CMD_RET_SUCCESS;
}
U_BOOT_CMD(tyffit, 3, 0, do_tyffit, "exercise production FIT configuration validation", "");
