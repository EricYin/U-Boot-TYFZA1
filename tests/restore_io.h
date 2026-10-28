/* SPDX-License-Identifier: GPL-2.0-only */
/* Host-side MTD boundary for the unmodified production restore/loader C bodies. */
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
#include <sys/mman.h>
#include "formats.h"
typedef unsigned long ulong;
typedef uint32_t u32;
struct tyfza1_restore_status { bool active; u32 id; size_t next, total; };
struct mtd_info { size_t size, erasesize, writesize; };
struct erase_info { struct mtd_info *mtd; size_t addr, len; };
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define IS_ERR(pointer) ((uintptr_t)(pointer) >= (uintptr_t)-4095)
#define PTR_ERR(pointer) ((long)(pointer))

static struct mtd_info device = { 0x10000000, 0x20000, 0x800 };
static struct mtd_info boot = { 0x200000, 0x20000, 0x800 };
static unsigned char *flash;
static size_t allocation_live, allocation_peak, allocation_max;
static size_t erased[4096], erased_count;
static size_t bad_offsets[8], bad_count;
static long fail_write = -1, corrupt_read = -1;
static int detach_error, corrected_reads, references;

static void *tracked_alloc(size_t size)
{
	size_t *p = malloc(size + sizeof(size_t));
	if (!p) return NULL;
	*p = size;
	allocation_live += size;
	if (allocation_live > allocation_peak) allocation_peak = allocation_live;
	if (size > allocation_max) allocation_max = size;
	return p + 1;
}

static void tracked_free(void *address)
{
	size_t *p = address;
	if (!p) return;
	allocation_live -= p[-1];
	free(p - 1);
}
#define free tracked_free
#define malloc_cache_aligned tracked_alloc

static int mtd_probe_devices(void) { return 0; }
static struct mtd_info *get_mtd_device_nm(const char *name)
{
	if (!strcmp(name, "boot")) { references++; return &boot; }
	if (!strcmp(name, "nand0")) { references++; return &device; }
	return (void *)(uintptr_t)-ENODEV;
}
static void put_mtd_device(struct mtd_info *mtd) { (void)mtd; references--; }
static void *map_sysmem(ulong address, size_t size) { (void)size; return (void *)address; }
static ulong map_to_sysmem(const void *address) { return (ulong)address; }
static void unmap_sysmem(const void *address) { (void)address; }
static int ubi_detach(void) { return detach_error; }
static int mtd_block_isbad(struct mtd_info *mtd, size_t offset)
{
	size_t i;
	if (offset >= mtd->size) return -EINVAL;
	for (i = 0; i < bad_count; i++) if (bad_offsets[i] == offset) return 1;
	return 0;
}
static int mtd_read(struct mtd_info *mtd, size_t offset, size_t size, size_t *done, void *out)
{
	*done = 0;
	if (offset > mtd->size || size > mtd->size - offset) return -EINVAL;
	memcpy(out, flash + offset, size);
	if ((long)offset == corrupt_read && size) ((unsigned char *)out)[0] ^= 1;
	*done = size;
	return corrected_reads ? -EUCLEAN : 0;
}
static int mtd_write(struct mtd_info *mtd, size_t offset, size_t size, size_t *done, const void *in)
{
	*done = 0;
	if (offset > mtd->size || size > mtd->size - offset || (long)offset == fail_write) return -EIO;
	if (mtd_block_isbad(mtd, offset)) return -EIO;
	memcpy(flash + offset, in, size);
	*done = size;
	return 0;
}
static int mtd_erase(struct mtd_info *mtd, struct erase_info *erase)
{
	if (erase->addr > mtd->size || erase->len > mtd->size - erase->addr ||
	    mtd_block_isbad(mtd, erase->addr) || erased_count >= 4096) return -EIO;
	erased[erased_count++] = erase->addr;
	memset(flash + erase->addr, 0xff, erase->len);
	return 0;
}

int tyfza1_validate_loader(ulong address, size_t size);
int tyfza1_loader_certificates(const void *loader, size_t size);
int tyfza1_install_loader(ulong address, size_t size, bool bl2, void (*poll)(void));
