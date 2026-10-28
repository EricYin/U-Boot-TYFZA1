/* SPDX-License-Identifier: GPL-2.0-only */
/* UBI data boundary only; production boot, FIT checks, env and Hush stay real. */
#include <command.h>
#include <env.h>
#include <mapmem.h>
#include <stdio.h>
#include <string.h>
#include <vsprintf.h>
#include <linux/libfdt.h>
#include <tyfza1_recovery.h>
static ulong fixture_address;
static size_t fixture_size, fixture_used, fixture_read;
static int fixture_error;
static char fixture_volume[16];
static int ubi_part(const char *part, const char *vid)
{
	return strcmp(part, "ubi_device");
}
static int ubi_volume_get_size(const char *name, size_t *used, size_t *capacity)
{
	strlcpy(fixture_volume, name, sizeof(fixture_volume));
	if (used) *used = fixture_used;
	if (capacity) *capacity = 0x60e000;
	return 0;
}
static int ubi_volume_read_quiet(char *name, char *out, loff_t off, size_t size)
{
	const void *data;
	fixture_read = size;
	if (fixture_error || off < 0 || off > fixture_used || size > fixture_used - off ||
	    off > fixture_size || size > fixture_size - off) return 1;
	strlcpy(fixture_volume, name, sizeof(fixture_volume));
	data = map_sysmem(fixture_address + off, size);
	memcpy(out, data, size);
	unmap_sysmem(data);
	return 0;
}
