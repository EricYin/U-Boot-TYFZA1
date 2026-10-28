// SPDX-License-Identifier: GPL-2.0-only
#include <config.h>
#include <env.h>
#include <init.h>
#include <event.h>
#include <stdio.h>
#include <string.h>
#include <button.h>
#include <command.h>
#include <net/httpd.h>
#include <mapmem.h>
#include <linux/libfdt.h>
#include <ubi_uboot.h>
#include <tyfza1_recovery.h>
#include <asm/global_data.h>
#include <asm/io.h>
#include <asm/armv8/mmu.h>
#include <linux/arm-smccc.h>
#include <linux/psci.h>
#include <linux/errno.h>

DECLARE_GLOBAL_DATA_PTR;

static struct mm_region tyfza1_mem_map[] = {
	{ .virt = 0, .phys = 0, .size = 0x20000000,
	  .attrs = PTE_BLOCK_MEMTYPE(MT_NORMAL) | PTE_BLOCK_INNER_SHARE },
	{ .virt = 0x80000000UL, .phys = 0x80000000UL, .size = 0x580000000UL,
	  .attrs = PTE_BLOCK_MEMTYPE(MT_DEVICE_NGNRNE) | PTE_BLOCK_NON_SHARE |
		   PTE_BLOCK_PXN | PTE_BLOCK_UXN },
	{ 0 }
};
struct mm_region *mem_map = tyfza1_mem_map;
static u32 original_xram[0x2000 / sizeof(u32)];
static bool reset_requested;

int print_cpuinfo(void)
{
	puts("CPU:   Realtek RTL9617CVW (Taurus), Cortex-A55\n");
	return 0;
}

int dram_init(void)
{
	/* BL2 publishes the trained capacity in MiB. Both TYFZA1 boards have 512. */
	if (readl(0x0111100c) != 512)
		return -EINVAL;
	gd->ram_size = 0x20000000;
	return 0;
}

int dram_init_banksize(void)
{
	/* Keep the original secure mailbox and all of the BL31 region unavailable. */
	gd->bd->bi_dram[0].start = 0;
	gd->bd->bi_dram[0].size = 0x0eeff000;
	gd->bd->bi_dram[1].start = 0x10000000;
	gd->bd->bi_dram[1].size = 0x10000000;
	return 0;
}

int board_init(void)
{
	unsigned int i;
	extern void ca77xx_eth_change_default(void);
	/* Also covers entry from RAM without the compressed BL33 wrapper. */
	writel(0, PER_WDT_CTRL);
	writel(1, 0xf4321000);
	reset_requested = tyfza1_reset_held();
	for (i = 0; i < ARRAY_SIZE(original_xram); i++)
		original_xram[i] = readl(0xf4500000 + i * 4);
	ca77xx_eth_change_default();
	return 0;
}

void board_preboot_os(void)
{
	unsigned int i;
	tyfza1_recovery_leds(TYFZA1_LEDS_OFF);
	/* Match the stock handoff: stop all NI MACs and return XRAM to its entry state. */
	for (i = 0; i < 6; i++)
		clrbits_le32(0xf430a5c8 + i * 0x90, 1);
	for (i = 0; i < ARRAY_SIZE(original_xram); i++)
		writel(original_xram[i], 0xf4500000 + i * 4);
}

int board_late_init(void)
{
	/* Match the stock success handoff to BL2/BL31 and their watchdog state. */
	writel(0, PER_WDT_CTRL);
	writel(0, GLOBAL_SCRATCH);
	writel(0, 0x0111111c);
	writel(0x00200000, DMA_SEC_SSP_FRAME_CTRL0);
	env_set("mtdids", CONFIG_MTDIDS_DEFAULT);
	env_set("mtdparts", CONFIG_MTDPARTS_DEFAULT);

	/* Old automatically inferred values must not select a Linux device tree. */
	env_set("board_variant", NULL);
	env_set("b_conf", NULL);
	/* Existing OEM NAND environments must not replace the new recovery entry. */
	env_set("bootcmd", "bootmenu 3");
	env_set("bootmenu_0", "Start OpenWrt=tyfboot; tyfrecovery");
	env_set("bootmenu_1", "Web recovery=tyfrecovery");
	env_set("boot_production", "tyfboot");
	/* Reset was latched in board_init. Both boards share the status lamps. */
	if (reset_requested) tyfza1_recovery_leds(TYFZA1_LEDS_HELD);
	return 0;
}

static int tyfza1_boot(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	const char *committed = env_get("sw_commit");
	const char *conf = tyfza1_boot_config();
	int slot = committed && !strcmp(committed, "1");
	char volume[16];
	struct fdt_header header;
	size_t used, size;
	void *image;
	int ret;

	if (!conf) {
		puts("Select and save the OpenWrt boot configuration in web recovery first.\n");
		return CMD_RET_FAILURE;
	}
	if (committed && strcmp(committed, "0") && strcmp(committed, "1"))
		return CMD_RET_FAILURE;
	if (ubi_part("ubi_device", NULL))
		return CMD_RET_FAILURE;
	snprintf(volume, sizeof(volume), "ubi_k%d", slot);
	if (ubi_volume_get_size(volume, &used, NULL) || used < sizeof(header) ||
	    ubi_volume_read_quiet(volume, (char *)&header, 0, sizeof(header)) ||
	    fdt_magic(&header) != FDT_MAGIC)
		return CMD_RET_FAILURE;
	size = fdt_totalsize(&header);
	/* Static volumes expose only written data; dynamic volumes include padding. */
	if (size < sizeof(header) || size > used || size > 0x600000)
		return CMD_RET_FAILURE;
	image = map_sysmem(0x05000000, size);
	ret = ubi_volume_read_quiet(volume, image, 0, size);
	unmap_sysmem(image);
	if (ret || tyfza1_check_fit(0x05000000, size))
		return CMD_RET_FAILURE;
	/* The existing boot script uses root_mtd and b_conf for both boards. */
	if (env_set("b_conf", conf) ||
	    env_set("root_mtd", slot ? "31:12" : "31:9") ||
	    env_set("unzip_src", "0x05000000"))
		return CMD_RET_FAILURE;
	return run_command("source 0x05000000:script", 0);
}

U_BOOT_CMD(tyfboot, 1, 0, tyfza1_boot,
	   "boot the committed TYFZA1 UBI slot", "");

static int tyfza1_recovery(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	return uboot_httpd_start(env_get_yesno("httpd_dhcp") != 0);
}

U_BOOT_CMD(tyfrecovery, 1, 0, tyfza1_recovery,
	   "start recovery using saved httpd_dhcp/IP settings", "");

static int tyfza1_recovery_button(void)
{
	int ret;
	reset_requested |= tyfza1_reset_held();
	if (reset_requested) tyfza1_recovery_leds(TYFZA1_LEDS_HELD);
	tyfza1_boot_leds();
	if (!reset_requested) {
		puts("Reset released: normal boot\n");
		return 0;
	}
	/* On exit or a network error, stay at the prompt instead of booting Linux. */
	env_set("bootcmd", "");
	puts("Reset held: starting TYFZA1 HTTP recovery\n");
	ret = uboot_httpd_start(env_get_yesno("httpd_dhcp") != 0);
	tyfza1_recovery_leds(TYFZA1_LEDS_OFF);
	if (ret) printf("Recovery network failed (%d); use tyfrecovery to retry.\n", ret);
	return 0;
}
EVENT_SPY_SIMPLE(EVT_POST_PREBOOT, tyfza1_recovery_button);

void reset_cpu(void)
{
	struct arm_smccc_res res;
	arm_smccc_smc(PSCI_0_2_FN_SYSTEM_RESET, 0, 0, 0, 0, 0, 0, 0, &res);
}
