// SPDX-License-Identifier: GPL-2.0-only
#include <env.h>
#include <linux/errno.h>
#include <string.h>
#include <tyfza1_recovery.h>

const char *tyfza1_boot_config(void)
{
	const char *conf = env_get("tyf_bootconf");
	return conf && (!strcmp(conf, "conf-0") || !strcmp(conf, "conf-1")) ? conf : NULL;
}

int tyfza1_save_boot_config(const char *conf)
{
	const char *previous = tyfza1_boot_config();
	char old[7];
	int ret;
	if (!conf || (strcmp(conf, "conf-0") && strcmp(conf, "conf-1"))) return -EINVAL;
	if (previous && !strcmp(previous, conf)) return 0;
	if (previous) strcpy(old, previous);
	ret = env_set("tyf_bootconf", conf);
	if (!ret) ret = env_save();
	if (ret) env_set("tyf_bootconf", previous ? old : NULL);
	return ret;
}
