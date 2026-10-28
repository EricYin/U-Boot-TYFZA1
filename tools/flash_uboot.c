// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include <mtd/mtd-user.h>
#include <openssl/sha.h>
#include "formats.h"

int tyfza1_loader_certificates(const void *data, size_t size);

static int transfer(int fd, void *data, size_t size, off_t offset, int write_data)
{
	unsigned char *p = data;
	while (size) {
		ssize_t n = write_data ? pwrite(fd, p, size, offset) : pread(fd, p, size, offset);
		if (n < 0 && errno == EINTR) continue;
		if (n <= 0) return -1;
		p += n; size -= n; offset += n;
	}
	return 0;
}

static unsigned char *read_file(const char *name, size_t size)
{
	struct stat st;
	unsigned char *data = NULL;
	int fd = open(name, O_RDONLY);
	if (fd < 0 || fstat(fd, &st) || st.st_size != (off_t)size) goto out;
	data = malloc(size);
	if (data && transfer(fd, data, size, 0, 0)) { free(data); data = NULL; }
out:
	if (fd >= 0) close(fd);
	return data;
}

static const char *select_boot_profile(const unsigned char *bundle, const unsigned char *current,
			       struct tyf_payload *selected)
{
	static const char *names[] = { "4ge", "2p5g" };
	const char *match = NULL;
	struct tyf_payload image;
	unsigned int i;
	for (i = 0; i < 2; i++) {
		if (tyf_select_loader(bundle, TYF_BUNDLE_HEADER + 2 * TYF_BOOT_SIZE, names[i], &image) ||
		    tyfza1_loader_certificates(image.data, image.size)) return NULL;
		if (!tyf_loader_preserves_device(image.data, image.size, current, TYF_BOOT_SIZE)) {
			if (match) return NULL;
			match = names[i]; *selected = image;
		}
	}
	return match;
}

static int boot_device(char name[64])
{
	char line[256], label[128];
	unsigned int number, size, erase;
	FILE *file = fopen("/proc/mtd", "r");
	int found = 0;
	if (!file) return -1;
	while (fgets(line, sizeof(line), file)) {
		if (sscanf(line, "mtd%u: %x %x \"%127[^\"]\"", &number, &size, &erase, label) == 4 &&
		    !strcmp(label, "boot")) {
			if (found || size != TYF_BOOT_SIZE || erase != 0x20000) { found = 0; break; }
			snprintf(name, 64, "/dev/mtd%u", number); found = 1;
		}
	}
	fclose(file);
	return found ? 0 : -1;
}

static int write_fips(int fd, const unsigned char *image)
{
	unsigned char check[0x20000];
	const off_t starts[] = { TYF_FIP1_OFFSET, TYF_FIP0_OFFSET };
	struct erase_info_user erase;
	unsigned int copy;
	off_t offset;
	/* Complete bad-block checks before the first erase. Preserve physical offsets. */
	for (offset = TYF_FIP0_OFFSET; offset < TYF_FIP1_OFFSET + TYF_FIP_SIZE; offset += sizeof(check))
		if (ioctl(fd, MEMGETBADBLOCK, &offset)) return -1;
	for (copy = 0; copy < 2; copy++) {
		for (offset = starts[copy]; offset < starts[copy] + TYF_FIP_SIZE; offset += sizeof(check)) {
			erase = (struct erase_info_user) { .start = offset, .length = sizeof(check) };
			if (ioctl(fd, MEMERASE, &erase) ||
			    transfer(fd, (void *)(image + offset), sizeof(check), offset, 1) ||
			    transfer(fd, check, sizeof(check), offset, 0) ||
			    memcmp(check, image + offset, sizeof(check))) return -1;
		}
		sync();
		printf("FIP%u written and read back.\n", 1 - copy);
	}
	return 0;
}

int main(int argc, char **argv)
{
	int checking = argc >= 2 && !strcmp(argv[1], "--check");
	const char *input, *variant;
	char device[64], backup[96];
	unsigned char *bundle = NULL, *current = NULL, digest[SHA256_DIGEST_LENGTH];
	struct tyf_payload selected;
	struct mtd_info_user info;
	int fd = -1, saved = -1, result = 1;
	unsigned int i;
	if ((!checking && argc != 2) || (checking && argc != 3 && argc != 4)) {
		fprintf(stderr, "Usage: %s [--check] universal.bin [boot-backup.bin for offline check]\n", argv[0]);
		return 1;
	}
	input = argv[checking ? 2 : 1];
	bundle = read_file(input, TYF_BUNDLE_HEADER + 2 * TYF_BOOT_SIZE);
	if (!bundle) { fprintf(stderr, "Expected a complete TYFZA1 universal package\n"); goto out; }
	if (checking && argc == 4) {
		current = read_file(argv[3], TYF_BOOT_SIZE);
	} else {
		if (boot_device(device)) { fprintf(stderr, "Cannot identify the 2 MiB boot MTD partition\n"); goto out; }
		fd = open(device, checking ? O_RDONLY : O_RDWR);
		if (fd < 0 || flock(fd, LOCK_EX | LOCK_NB) || ioctl(fd, MEMGETINFO, &info) ||
		    !mtd_type_is_nand_user(&info) || info.size != TYF_BOOT_SIZE ||
		    info.erasesize != 0x20000 || info.writesize != 0x800) {
			perror("Cannot open matching boot NAND"); goto out;
		}
		if (!checking && !(info.flags & MTD_WRITEABLE)) {
			fprintf(stderr, "The boot partition is read-only; use firmware with U-Boot update support\n"); goto out;
		}
		current = malloc(TYF_BOOT_SIZE);
		if (current && transfer(fd, current, TYF_BOOT_SIZE, 0, 0)) { free(current); current = NULL; }
	}
	if (!current) { fprintf(stderr, "Cannot read the complete existing boot image\n"); goto out; }
	variant = select_boot_profile(bundle, current, &selected);
	if (!variant) { fprintf(stderr, "Package signatures or local BL2/BL31/GPT profile do not match\n"); goto out; }
	SHA256(selected.data, selected.size, digest);
	printf("Matching boot profile %s; 2 MiB loader SHA256: ", variant);
	for (i = 0; i < sizeof(digest); i++) printf("%02x", digest[i]);
	putchar('\n');
	if (checking) { puts("Package and boot compatibility checks passed; Flash unchanged."); result = 0; goto out; }
	snprintf(backup, sizeof(backup), "tyfza1-boot-backup-%ld-%ld.bin", (long)time(NULL), (long)getpid());
	saved = open(backup, O_WRONLY | O_CREAT | O_EXCL, 0600);
	if (saved < 0 || transfer(saved, current, TYF_BOOT_SIZE, 0, 1) || fsync(saved)) {
		perror("Cannot save boot backup"); goto out;
	}
	close(saved); saved = -1;
	printf("Boot backup: %s\n", backup); fflush(stdout);
	if (write_fips(fd, selected.data)) { perror("NAND write/readback failed"); goto out; }
	puts("U-Boot installed. Reboot to start it."); result = 0;
out:
	if (saved >= 0) close(saved);
	if (fd >= 0) close(fd);
	free(current); free(bundle);
	return result;
}
