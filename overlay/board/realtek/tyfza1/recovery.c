// SPDX-License-Identifier: GPL-2.0-only
#include <config.h>
#include <command.h>
#include <env.h>
#include <image.h>
#include <malloc.h>
#include <memalign.h>
#include <mapmem.h>
#include <mtd.h>
#include <stdio.h>
#include <ubi_uboot.h>
#include <tyfza1_recovery.h>
#include <lzma/LzmaTools.h>
#include <linux/libfdt.h>
#include "formats.h"

static int volume_verify(char *name, const void *data, size_t length,
			 void (*poll)(void))
{
	unsigned char *check = malloc_cache_aligned(0x10000);
	const unsigned char *input = data;
	size_t off, chunk;
	int ret = -ENOMEM;
	if (!check) return ret;
	for (off = 0; off < length; off += chunk) {
		chunk = min_t(size_t, 0x10000, length - off);
		ret = ubi_volume_read_quiet(name, (char *)check, off, chunk);
		if (ret || memcmp(check, input + off, chunk)) {
			ret = ret ? ret : -EIO;
			break;
		}
		poll();
	}
	free(check);
	return ret;
}

static int verify_fit(const struct tyf_payload *image)
{
	const void *data;
	const char *conf = tyfza1_boot_config();
	void *dtb = NULL;
	size_t size;
	u8 comp;
	int node, fdt, images, child, ret = -EINVAL;
	if (!conf ||
	    fit_check_format(image->data, image->size)) return -EINVAL;
	images = fdt_path_offset(image->data, FIT_IMAGES_PATH);
	if (images < 0) return -EINVAL;
	fdt_for_each_subnode(child, image->data, images) {
		uintptr_t start = (uintptr_t)image->data, at;
		if (fit_image_get_data(image->data, child, &data, &size)) return -EINVAL;
		at = (uintptr_t)data;
		if (at < start || size > image->size || at - start > image->size - size)
			return -EINVAL;
	}
	if (!fit_all_image_verify(image->data)) return -EINVAL;
	node = fit_conf_get_node(image->data, conf);
	if (node < 0) return node;
	fdt = fit_conf_get_prop_node(image->data, node, FIT_FDT_PROP, IH_PHASE_NONE);
	if (fdt < 0 || fit_image_get_data(image->data, fdt, &data, &size) ||
	    (const unsigned char *)data < image->data || size > image->size ||
	    (const unsigned char *)data - image->data > image->size - size ||
	    fit_image_get_comp(image->data, fdt, &comp)) return -EINVAL;
	if (comp == IH_COMP_LZMA) {
		SizeT output_size = 0x20000;
		dtb = malloc(output_size);
		if (!dtb) return -ENOMEM;
		if (lzmaBuffToBuffDecompress(dtb, &output_size, (unsigned char *)data, size))
			goto out;
		data = dtb;
		size = output_size;
	} else if (comp != IH_COMP_NONE) {
		goto out;
	} else if ((uintptr_t)data & 7) {
		/* FIT properties are 4-byte aligned; libfdt requires an 8-byte DT. */
		dtb = malloc(size);
		if (!dtb) return -ENOMEM;
		memcpy(dtb, data, size);
		data = dtb;
	}
	if (fdt_check_full(data, size)) goto out;
	ret = fdt_node_check_compatible(data, 0, "tianyi,tyfza1");
	if (ret) ret = -EINVAL;
out:
	free(dtb);
	return ret;
}

int tyfza1_check_fit(ulong address, size_t size)
{
	struct tyf_payload image = { map_sysmem(address, size), size };
	int ret = verify_fit(&image);
	unmap_sysmem(image.data);
	return ret;
}

int tyfza1_boot_upload(ulong address, size_t size)
{
	const char *slot = env_get("tyfza1_slot");
	int ret = tyfza1_check_fit(address, size);
	if (ret) return ret;
	ret = env_set("b_conf", tyfza1_boot_config());
	if (ret) return ret;
	if (!slot) slot = env_get("sw_commit");
	/* Signed system scripts select their root volume through root_mtd. */
	env_set("root_mtd", slot && !strcmp(slot, "1") ? "31:12" : "31:9");
	/* Source the validated board script when present; otherwise select the board FIT explicitly. */
	env_set_hex("unzip_src", address);
	if (fdt_path_offset((void *)address, "/images/script") >= 0)
		return run_commandf("source %lx:script", address);
	return run_commandf("bootm %lx#%s", address, env_get("b_conf"));
}

static int resize_root(struct ubi_volume *root, int lebs)
{
	struct ubi_volume_desc *desc;
	int ret;
	desc = ubi_open_volume(root->ubi->ubi_num, root->vol_id, UBI_EXCLUSIVE);
	if (IS_ERR(desc)) return PTR_ERR(desc);
	ret = ubi_resize_volume(desc, lebs);
	ubi_close_volume(desc);
	return ret;
}

static int installed_openwrt_slot(int committed)
{
	struct fdt_header header;
	struct tyf_payload image;
	char name[16];
	const char *description;
	unsigned char *buffer;
	unsigned int found = 0;
	int slot, ret, length;
	size_t used;
	for (slot = 0; slot < 2; slot++) {
		snprintf(name, sizeof(name), "ubi_k%d", slot);
		ret = ubi_volume_get_size(name, &used, NULL);
		if (ret) return -EINVAL;
		if (used < sizeof(header)) continue;
		ret = ubi_volume_read_quiet(name, (char *)&header, 0, sizeof(header));
		if (ret) return -EIO;
		if (fdt_magic(&header) != FDT_MAGIC) continue;
		image.size = fdt_totalsize(&header);
		if (image.size < sizeof(header) || image.size > used || image.size > 0x600000)
			return -EINVAL;
		buffer = malloc_cache_aligned(image.size);
		if (!buffer) return -ENOMEM;
		image.data = buffer;
		ret = ubi_volume_read_quiet(name, (char *)buffer, 0, image.size);
		if (!ret) ret = fdt_check_full(buffer, image.size);
		if (!ret) {
			description = fdt_getprop(buffer, 0, "description", &length);
			/* All released PonWRT FITs carry this prefix; OEM FITs do not. */
			if (description && length > 14 && !memcmp(description, "TYFZA1 native ", 14)) {
				ret = verify_fit(&image);
				if (!ret) found |= 1U << slot;
			}
		}
		free(buffer);
		if (ret) return -EINVAL;
	}
	if (found == 3) return committed;
	if (found) return found == 2;
	return 1 - committed;
}

int tyfza1_install_system(ulong address, size_t size, void (*poll)(void))
{
	struct tyf_firmware fw;
	const void *input = map_sysmem(address, size);
	const char *committed = env_get("sw_commit"), *installed = env_get("tyfza1_slot");
	char kernel[16], root[16];
	char old_commit[2] = "0", old_active[2] = "0", old_try[2] = "2", old_slot[2] = "";
	struct ubi_device *ubi;
	struct ubi_volume *rootvol, *data;
	size_t capacity;
	int slot, root_lebs, available, ret = -EINVAL;

	if (committed && strcmp(committed, "0") && strcmp(committed, "1")) goto out;
	if (committed) old_commit[0] = committed[0];
	if (installed) {
		if (strcmp(installed, "0") && strcmp(installed, "1")) goto out;
		old_slot[0] = installed[0];
	}
	if (env_get("sw_active")) old_active[0] = env_get("sw_active")[0];
	if (env_get("sw_tryactive")) old_try[0] = env_get("sw_tryactive")[0];
	if (tyf_parse_sysupgrade(input, size, &fw) || verify_fit(&fw.kernel)) {
		puts("Expected a TYFZA1 sysupgrade archive with a matching, hash-verified FIT and SquashFS.\n");
		goto out;
	}
	ret = ubi_part("ubi_device", NULL);
	if (ret) goto out;
	/* Older Linux installers never persisted tyfza1_slot: inspect their FITs. */
	slot = installed ? old_slot[0] - '0' : installed_openwrt_slot(old_commit[0] - '0');
	if (slot < 0) { ret = slot; goto out; }
	snprintf(kernel, sizeof(kernel), "ubi_k%d", slot);
	snprintf(root, sizeof(root), "ubi_r%d", slot);
	ret = ubi_volume_get_size(kernel, NULL, &capacity);
	if (ret || fw.kernel.size > capacity) { ret = -EFBIG; goto out; }
	ubi = ubi_devices[0];
	rootvol = ubi->volumes[slot ? 7 : 4];
	data = ubi->volumes[11];
	if (!rootvol || strcmp(rootvol->name, root) ||
	    (data && strcmp(data->name, "rootfs_data")) ||
	    fw.root.size > 33648640) { ret = -EINVAL; goto out; }
	root_lebs = DIV_ROUND_UP(fw.root.size, rootvol->usable_leb_size);
	available = ubi->avail_pebs + rootvol->reserved_pebs + (data ? data->reserved_pebs : 0);
	if (available - root_lebs < DIV_ROUND_UP(16777216, ubi->leb_size)) {
		ret = -ENOSPC; goto out;
	}
	if (root_lebs > rootvol->reserved_pebs) {
		if (root_lebs - rootvol->reserved_pebs > ubi->avail_pebs && data) {
			ret = ubi_volume_remove("rootfs_data");
			if (ret) goto out;
			data = NULL;
		}
		ret = resize_root(rootvol, root_lebs);
		if (ret) goto out;
	}
	printf("Installing OpenWrt in slot %d; factory volumes are retained.\n", slot);
	ret = ubi_volume_write(root, (void *)fw.root.data, 0, fw.root.size);
	if (!ret) ret = volume_verify(root, fw.root.data, fw.root.size, poll);
	if (ret) goto out;
	ret = ubi_volume_write(kernel, (void *)fw.kernel.data, 0, fw.kernel.size);
	if (!ret) ret = volume_verify(kernel, fw.kernel.data, fw.kernel.size, poll);
	if (ret) goto out;
	ret = resize_root(rootvol, root_lebs);
	if (ret) goto out;
	if (data && (ret = ubi_volume_remove("rootfs_data"))) goto out;
	ret = run_command("ubi create rootfs_data 0 d b", 0);
	if (ret) goto out;
	/* Commit only after both new volumes have passed independent readback. */
	env_set("sw_commit", slot ? "1" : "0");
	env_set("sw_active", slot ? "1" : "0");
	env_set("sw_tryactive", "2");
	env_set("tyfza1_slot", slot ? "1" : "0");
	ret = env_save();
	if (ret) {
		env_set("sw_commit", old_commit);
		env_set("sw_active", old_active);
		env_set("sw_tryactive", old_try);
		env_set("tyfza1_slot", old_slot[0] ? old_slot : NULL);
	} else {
		printf("Slot %d written, read back and committed.\n", slot);
	}
out:
	unmap_sysmem(input);
	return ret;
}

static int read_mtd(struct mtd_info *mtd, size_t offset, size_t length, void *out)
{
	size_t done;
	int ret = mtd_read(mtd, offset, length, &done, out);
	if (ret == -EUCLEAN && done == length) ret = 0;
	return ret ? ret : done == length ? 0 : -EIO;
}

int tyfza1_validate_loader(ulong address, size_t size)
{
	struct tyf_fip next;
	const unsigned char *input = map_sysmem(address, size);
	unsigned char *current = NULL;
	struct mtd_info *mtd = NULL;
	int ret = -EINVAL;

	if (tyf_parse_loader(input, size, &next) || tyfza1_loader_certificates(input, size)) goto out;
	mtd_probe_devices();
	mtd = get_mtd_device_nm("boot");
	if (IS_ERR(mtd)) { ret = PTR_ERR(mtd); mtd = NULL; goto out; }
	if (mtd->size != TYF_BOOT_SIZE || mtd->erasesize != 0x20000 ||
	    mtd->writesize != 0x800) goto out;
	current = malloc_cache_aligned(TYF_BOOT_SIZE);
	if (!current) { ret = -ENOMEM; goto out; }
	ret = read_mtd(mtd, 0, TYF_BOOT_SIZE, current);
	if (ret) goto out;
	ret = tyf_loader_preserves_device(input, size, current, TYF_BOOT_SIZE) ? -EINVAL : 0;
	if (ret)
		puts("Loader must preserve this device's GPT, BL2, BL31 and reserved bytes.\n");
out:
	free(current);
	if (mtd) put_mtd_device(mtd);
	unmap_sysmem(input);
	return ret;
}

size_t tyfza1_loader_write_size(void)
{
	return 2 * TYF_FIP_SIZE;
}

int tyfza1_install_loader(ulong address, size_t size, bool bl2, void (*poll)(void))
{
	const unsigned char *input;
	const void *bundle;
	struct tyf_payload selected;
	unsigned char *check = NULL;
	struct mtd_info *mtd;
	size_t base, offset, done;
	int copy, ret;
	/* Taurus has no separate AN758x preloader partition. */
	if (bl2) return -EINVAL;
	bundle = map_sysmem(address, size);
	/* Select the early-firmware profile by immutable boot contents, never by
	 * the user's Linux configuration or an automatically inferred model. */
	{
		static const char *profiles[] = { "4ge", "2p5g" };
		struct tyf_payload match = {0};
		unsigned int i, matches = 0;
		for (i = 0; i < ARRAY_SIZE(profiles); i++) {
			ret = tyf_select_loader(bundle, size, profiles[i], &selected);
			if (ret || tyfza1_loader_certificates(selected.data, selected.size)) {
				matches = 0; ret = -EINVAL; break;
			}
			ret = tyfza1_validate_loader(map_to_sysmem(selected.data), selected.size);
			if (!ret) { match = selected; matches++; }
			else if (ret != -EINVAL) break;
			if (size == TYF_BOOT_SIZE) break;
		}
		if (matches != 1 || (ret && ret != -EINVAL)) {
			unmap_sysmem(bundle);
			return ret ? ret : -EINVAL;
		}
		address = map_to_sysmem(match.data);
		size = match.size;
	}
	unmap_sysmem(bundle);
	input = map_sysmem(address, size);
	mtd = get_mtd_device_nm("boot");
	if (IS_ERR(mtd)) { unmap_sysmem(input); return PTR_ERR(mtd); }
	check = malloc_cache_aligned(mtd->erasesize);
	if (!check) { ret = -ENOMEM; goto out; }
	for (offset = TYF_FIP0_OFFSET; offset < 0x1c0000; offset += mtd->erasesize) {
		ret = mtd_block_isbad(mtd, offset);
		if (ret) { ret = ret < 0 ? ret : -EIO; goto out; }
	}
	/* Finish and verify FIP1 before touching FIP0. No offset shifting in boot. */
	for (copy = 1; copy >= 0; copy--) {
		base = copy ? TYF_FIP1_OFFSET : TYF_FIP0_OFFSET;
		for (offset = base; offset < base + TYF_FIP_SIZE; offset += mtd->erasesize) {
			struct erase_info erase = { .mtd = mtd, .addr = offset, .len = mtd->erasesize };
			ret = mtd_erase(mtd, &erase);
			if (ret) goto out;
			ret = mtd_write(mtd, offset, mtd->erasesize, &done, input + offset);
			if (ret || done != mtd->erasesize) { ret = ret ? ret : -EIO; goto out; }
			ret = read_mtd(mtd, offset, mtd->erasesize, check);
			if (ret || memcmp(check, input + offset, mtd->erasesize)) {
				ret = ret ? ret : -EIO;
				goto out;
			}
			poll();
		}
		printf("FIP%d written and read back.\n", copy);
	}
out:
	free(check);
	put_mtd_device(mtd);
	unmap_sysmem(input);
	return ret;
}

int tyfza1_rebuild_ubi(void (*poll)(void))
{
	static const struct { const char *name; unsigned int size; } layout[] = {
		{ "ubi_Config", 0x60e000 }, { "ubi_fpga", 0x41e000 },
		{ "ubi_DTB0", 0x5d000 }, { "ubi_k0", 0x60e000 }, { "ubi_r0", 0x2017000 },
		{ "ubi_DTB1", 0x5d000 }, { "ubi_k1", 0x60e000 }, { "ubi_r1", 0x2017000 },
		{ "ubi_framework1", 0x101b000 }, { "ubi_framework2", 0x101b000 },
		{ "ubi_apps", 0x6007000 }, { "rootfs_data", 0x1000000 },
	};
	const unsigned int keep = (1U << 0) | (1U << 1) | (1U << 2) | (1U << 5);
	struct ubi_device *ubi;
	struct ubi_volume *vol;
	int available, needed = 0;
	unsigned int i;
	int ret = ubi_part("ubi_device", NULL);
	if (ret) return ret;
	ubi = ubi_devices[0];
	if (!ubi || ubi->ro_mode) return -EROFS;
	available = ubi->avail_pebs;
	if (ubi->beb_rsvd_level > ubi->beb_rsvd_pebs)
		available -= ubi->beb_rsvd_level - ubi->beb_rsvd_pebs;
	/* Keep calibration volumes in Flash throughout; never erase the whole MTD. */
	for (i = 0; i < ubi->vtbl_slots; i++) {
		vol = ubi->volumes[i];
		if (!vol) continue;
		if (i >= ARRAY_SIZE(layout) || strcmp(vol->name, layout[i].name)) {
			puts("Unknown UBI volume layout; rebuild refused before removal.\n");
			return -EINVAL;
		}
		if (!(keep & (1U << i))) available += vol->reserved_pebs;
	}
	for (i = 0; i < ARRAY_SIZE(layout); i++) {
		if (keep & (1U << i)) {
			vol = ubi->volumes[i];
			if (!vol || vol->upd_marker || vol->corrupted) return -EINVAL;
		} else {
			needed += DIV_ROUND_UP(layout[i].size, ubi->leb_size);
		}
	}
	if (needed > available) return -ENOSPC;
	ret = env_set("tyfza1_slot", NULL);
	if (!ret) ret = env_save();
	if (ret) return ret;
	for (i = 0; i < ARRAY_SIZE(layout); i++) {
		if ((keep & (1U << i)) || !ubi->volumes[i]) continue;
		ret = ubi_volume_remove((char *)layout[i].name);
		if (ret) return ret;
		poll();
	}
	for (i = 0; i < ARRAY_SIZE(layout); i++) {
		if (keep & (1U << i)) continue;
		ret = run_commandf("ubi create %s %x d %x", layout[i].name,
				   i == 11 ? 0 : layout[i].size, i);
		if (ret) return ret;
		poll();
	}
	puts("UBI system volumes rebuilt; factory, FPGA and board trees stayed in Flash. Install a system before booting.\n");
	return 0;
}
