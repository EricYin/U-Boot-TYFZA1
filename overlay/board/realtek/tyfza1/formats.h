/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef TYFZA1_FORMATS_H
#define TYFZA1_FORMATS_H
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

#define TYF_BOOT_SIZE 0x200000U
#define TYF_FIP_SIZE 0xc0000U
#define TYF_FIP0_OFFSET 0x40000U
#define TYF_FIP1_OFFSET 0x100000U
#define TYF_BUNDLE_MAGIC "TYFZA1-UBOOT-V1"
#define TYF_BUNDLE_HEADER 16U

struct tyf_payload {
	const unsigned char *data;
	size_t size;
};

struct tyf_fip {
	struct tyf_payload bl2, bl31, bl33;
};

struct tyf_firmware {
	struct tyf_payload kernel, root;
};

int tyf_parse_fip(const void *data, size_t size, struct tyf_fip *out);
int tyf_parse_loader(const void *data, size_t size, struct tyf_fip *out);
int tyf_select_loader(const void *data, size_t size, const char *variant,
		      struct tyf_payload *out);
int tyf_loader_preserves_device(const void *next, size_t next_size,
			       const void *current, size_t current_size);
int tyfza1_check_sysupgrade(const void *data, size_t size, bool *factory_v1, void (*poll)(void));
int tyf_parse_sysupgrade(const void *data, size_t size, struct tyf_firmware *out);
#endif
