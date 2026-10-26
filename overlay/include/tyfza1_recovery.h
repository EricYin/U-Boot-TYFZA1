/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef TYFZA1_RECOVERY_H
#define TYFZA1_RECOVERY_H
#include <linux/types.h>
int tyfza1_board_id(void);
int tyfza1_reset_held(void);
void tyfza1_boot_leds(void);
enum tyfza1_leds {
	TYFZA1_LEDS_OFF,	/* pins returned to their previous owner */
	TYFZA1_LEDS_HELD,	/* Reset recognised: all on, safe to release */
	TYFZA1_LEDS_IDLE,	/* recovery waiting: heartbeat double flash */
	TYFZA1_LEDS_UPLOAD,	/* receiving into RAM: LAN1 flickers */
	TYFZA1_LEDS_BUSY,	/* writing Flash: quarter progress bar */
	TYFZA1_LEDS_DONE,	/* write succeeded: all on for two seconds */
	TYFZA1_LEDS_FAILED,	/* write failed: LAN1/3 and LAN2/4 alternate */
};
void tyfza1_recovery_leds(enum tyfza1_leds state);
void tyfza1_recovery_leds_busy(size_t done, size_t total);
void tyfza1_recovery_leds_progress(size_t bytes);
void tyfza1_recovery_leds_poll(void);
int tyfza1_install_system(ulong address, size_t size, void (*poll)(void));
int tyfza1_check_fit(ulong address, size_t size);
int tyfza1_boot_upload(ulong address, size_t size);
int tyfza1_validate_loader(ulong address, size_t size);
int tyfza1_loader_certificates(const void *loader, size_t size);
int tyfza1_install_loader(ulong address, size_t size, bool bl2, void (*poll)(void));
size_t tyfza1_loader_write_size(void);
int tyfza1_rebuild_ubi(void (*poll)(void));
struct tyfza1_restore_status {
	bool active;
	u32 id;
	size_t next, total;
};
const struct tyfza1_restore_status *tyfza1_restore_status(void);
int tyfza1_restore_job(const char *operation, ulong address, size_t size,
		       size_t total, size_t offset, u32 id, void (*poll)(void));
#endif
