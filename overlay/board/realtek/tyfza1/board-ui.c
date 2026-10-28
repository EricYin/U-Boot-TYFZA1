// SPDX-License-Identifier: GPL-2.0-only
#include <config.h>
#include <time.h>
#include <asm/io.h>
#include <linux/delay.h>
#include <linux/kernel.h>
#include <string.h>
#include <tyfza1_recovery.h>

#define GPIO_MUX 0xf4320100UL
#define GPIO_DIR 0xf43292c0UL
#define GPIO_OUT 0xf43292c4UL
#define GPIO_IN  0xf43292c8UL

int tyfza1_reset_held(void)
{
	u32 pin = 1U << 8;
	unsigned int i;
	setbits_le32(GPIO_MUX, pin);
	setbits_le32(GPIO_DIR, pin);
	/* Latch Reset before the boot menu. */
	for (i = 0; i < 3; i++) {
		if (readl(GPIO_IN) & pin) return 0;
		udelay(1000);
	}
	return 1;
}

/* PON/LOS are GPIO9/10, active low, on both original device trees. */
static const unsigned int lamp_pins[] = { 9, 10 };
static const u32 lamp_mask = (1U << 9) | (1U << 10);
static const u32 lamp_low = (1U << 9) | (1U << 10);
static u32 lamp_mux, lamp_dir, lamp_out;
static enum tyfza1_leds lamp_state;
static ulong lamp_since;
static size_t lamp_done, lamp_total;
static u32 lamp_lit;

static void lamp_claim(void)
{
	lamp_mux = readl(GPIO_MUX);
	lamp_dir = readl(GPIO_DIR);
	lamp_out = readl(GPIO_OUT);
	clrsetbits_le32(GPIO_OUT, lamp_mask, lamp_low);
	setbits_le32(GPIO_MUX, lamp_mask);
	clrbits_le32(GPIO_DIR, lamp_mask);
	lamp_lit = 0;
}

/* Return the pins to their previous LED/hardware ownership. */
static void lamp_release(void)
{
	clrsetbits_le32(GPIO_OUT, lamp_mask, lamp_out & lamp_mask);
	clrsetbits_le32(GPIO_DIR, lamp_mask, lamp_dir & lamp_mask);
	clrsetbits_le32(GPIO_MUX, lamp_mask, lamp_mux & lamp_mask);
}

/* Polled on every NAND page, so touch GPIO only when the pattern changes. */
static void lamp_show(u32 lit)
{
	if (lit == lamp_lit) return;
	lamp_lit = lit;
	clrsetbits_le32(GPIO_OUT, lamp_mask, lamp_low ^ lit);
}

void tyfza1_boot_leds(void)
{
	unsigned int i;
	if (lamp_state != TYFZA1_LEDS_OFF) return;
	lamp_claim();
	for (i = 0; i < 2; i++) {
		lamp_show(1U << lamp_pins[i]);
		mdelay(150);
		lamp_show(0);
	}
	lamp_release();
}

static u32 lamp_heartbeat(ulong t)
{
	t %= 2000;
	return t < 100 || (t >= 250 && t < 350) ? lamp_mask : 0;
}

/* Also called from NAND page loops, so a stalled write freezes the pattern. */
void tyfza1_recovery_leds_poll(void)
{
	ulong t;
	u32 lit = 0;
	unsigned int i, step;
	if (lamp_state == TYFZA1_LEDS_OFF) return;
	t = get_timer(lamp_since);
	switch (lamp_state) {
	case TYFZA1_LEDS_HELD:
		lit = lamp_mask;
		break;
	case TYFZA1_LEDS_IDLE:
		lit = lamp_heartbeat(t);
		break;
	case TYFZA1_LEDS_UPLOAD:
		if (t / 50 % 2 == 0) lit = 1U << lamp_pins[0];
		break;
	case TYFZA1_LEDS_BUSY:
		step = lamp_total ? min_t(size_t, lamp_done * 2 / lamp_total, 1) : 0;
		for (i = 0; i < step; i++) lit |= 1U << lamp_pins[i];
		if (t / 300 % 2 == 0) lit |= 1U << lamp_pins[step];
		break;
	case TYFZA1_LEDS_DONE:
		lit = t < 2000 ? lamp_mask : lamp_heartbeat(t - 2000);
		break;
	case TYFZA1_LEDS_FAILED:
		i = t / 150 % 2;
		lit = 1U << lamp_pins[i];
		break;
	default:
		break;
	}
	lamp_show(lit);
}

void tyfza1_recovery_leds(enum tyfza1_leds state)
{
	if (state == TYFZA1_LEDS_OFF) {
		if (lamp_state != TYFZA1_LEDS_OFF) lamp_release();
		lamp_state = TYFZA1_LEDS_OFF;
		return;
	}
	if (lamp_state == TYFZA1_LEDS_OFF) {
		lamp_claim();
	} else if (state == lamp_state) {
		return;
	} else if (state == TYFZA1_LEDS_IDLE &&
		   (lamp_state == TYFZA1_LEDS_DONE || lamp_state == TYFZA1_LEDS_FAILED)) {
		/* Results stay until the next upload or write replaces them. */
		return;
	}
	lamp_state = state;
	lamp_since = get_timer(0);
	tyfza1_recovery_leds_poll();
}

void tyfza1_recovery_leds_busy(size_t done, size_t total)
{
	lamp_done = done;
	lamp_total = total;
	tyfza1_recovery_leds(TYFZA1_LEDS_BUSY);
}

void tyfza1_recovery_leds_progress(size_t bytes)
{
	if (lamp_state == TYFZA1_LEDS_BUSY) lamp_done += bytes;
}
