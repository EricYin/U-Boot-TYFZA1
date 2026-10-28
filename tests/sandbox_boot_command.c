// SPDX-License-Identifier: GPL-2.0-only
/* Appended after the production tyfza1_boot body in the same translation unit. */
static int do_tyfbfixture(struct cmd_tbl *cmd, int flag, int argc, char *const argv[])
{
	int ret;
	if (argc != 5) return CMD_RET_USAGE;
	fixture_address = hextoul(argv[1], NULL);
	fixture_size = hextoul(argv[2], NULL);
	fixture_used = hextoul(argv[3], NULL);
	fixture_error = hextoul(argv[4], NULL);
	fixture_read = 0;
	fixture_volume[0] = 0;
	env_set("fixture_executed", NULL);
	ret = tyfza1_boot(cmd, flag, 0, NULL);
	printf("TYF BOOT %s read=%zx volume=%s script=%s\n", ret ? "REJECT" : "OK",
	       fixture_read, fixture_volume, env_get("fixture_executed") ?: "none");
	return ret ? CMD_RET_FAILURE : CMD_RET_SUCCESS;
}
U_BOOT_CMD(tyfbfixture, 5, 0, do_tyfbfixture, "exercise normal boot with modeled UBI", "");
