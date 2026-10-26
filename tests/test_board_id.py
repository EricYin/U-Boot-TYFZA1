#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run board detection and late init against real boot images and GPIO levels."""
import ctypes as C
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / 'overlay/board/realtek/tyfza1'
FIPS = (0x40000, 0x100000)


class BoardIdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory()
        source = (BOARD / 'tyfza1.c').read_text()
        late_init = source[source.index('int board_late_init('):source.index('static int tyfza1_boot(')]
        identity = BOARD / 'board-id.c'
        detector = '\n'.join(line for line in identity.read_text().splitlines()
                             if not line.startswith('#include'))
        prelude = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <openssl/sha.h>
#include "formats.h"
typedef uint32_t u32;
#define PER_WDT_CTRL 0xf432901cUL
#define GLOBAL_SCRATCH 0xf4329000UL
#define DMA_SEC_SSP_FRAME_CTRL0 0xf4320000UL
#define CONFIG_MTDIDS_DEFAULT "nand0=nand0"
#define CONFIG_MTDPARTS_DEFAULT "mtdparts=nand0:2m(boot),-(data)"
#define CHUNKSZ_SHA256 65536
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define IS_ERR(p) ((intptr_t)(p) < 0)
#define malloc_cache_aligned malloc
enum {TYFZA1_LEDS_HELD};
struct mtd_info {size_t size;};
static struct mtd_info mtd;
static const unsigned char *flash;
static int faults, strap, reads[2], gpio_reads;
static bool reset_requested;
static char variant[16], conf[16], bootcmd[32];
void mtd_probe_devices(void) {}
struct mtd_info *get_mtd_device_nm(const char *name) {
 return strcmp(name,"boot") || (faults & 1) ? (void *)(intptr_t)-ENODEV : &mtd;
}
void put_mtd_device(struct mtd_info *device) {(void)device;}
int mtd_read(struct mtd_info *device, size_t offset, size_t size, size_t *done, void *out) {
 int copy = offset == TYF_FIP1_OFFSET;
 if (offset != TYF_FIP0_OFFSET && offset != TYF_FIP1_OFFSET) return -EINVAL;
 reads[copy]++;
 if (faults & (2 << copy)) return -EIO;
 if (offset > device->size || size > device->size - offset) return -EINVAL;
 *done = size - !!(faults & 8);
 memcpy(out,flash + offset,*done);
 return faults & 16 ? -EUCLEAN : 0;
}
void sha256_csum_wd(const unsigned char *data, unsigned int size, unsigned char *out, unsigned int chunk) {
 (void)chunk;SHA256(data,size,out);
}
void writel(u32 value, uintptr_t address) {(void)value;(void)address;}
void setbits_le32(uintptr_t address, u32 bits) {(void)address;(void)bits;}
u32 readl(uintptr_t address) {(void)address;gpio_reads++;return (u32)strap << 15;}
void tyfza1_recovery_leds(int state) {(void)state;}
int env_set(const char *name, const char *value) {
 char *target = !strcmp(name,"board_variant") ? variant :
                !strcmp(name,"b_conf") ? conf : !strcmp(name,"bootcmd") ? bootcmd : NULL;
 if(target)strcpy(target,value ? value : "");
 return 0;
}
'''
        tail = r'''
int run(const void *data, size_t size, int gpio, int errors) {
 flash=data;mtd.size=size;strap=gpio;faults=errors;gpio_reads=reads[0]=reads[1]=0;
 strcpy(variant,"stale");strcpy(conf,"stale");strcpy(bootcmd,"stale");
 return board_late_init();
}
const char *setting(int key) {return key==0 ? variant : key==1 ? conf : bootcmd;}
int metric(int key) {return key==2 ? gpio_reads : reads[key];}
'''
        path = Path(cls.work.name) / 'board.c'
        path.write_text(prelude + detector + late_init + tail)
        library = Path(cls.work.name) / 'board.so'
        subprocess.run(['cc', '-O2', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        '-I' + str(BOARD), str(path), str(BOARD / 'formats.c'),
                        '-lcrypto', '-o', str(library)], check=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.run.argtypes = [C.c_void_p, C.c_size_t, C.c_int, C.c_int]
        cls.lib.setting.restype = C.c_char_p

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def boot(self, variant):
        return bytearray((ROOT / f'evidence/stock-boot/{variant}-boot.bin').read_bytes())

    def detect(self, image, gpio=0, errors=0):
        data = C.create_string_buffer(bytes(image))
        self.assertEqual(self.lib.run(data, len(image), gpio, errors), 0)
        return tuple(self.lib.setting(i).decode() for i in range(3))

    def change_payload(self, image, name):
        uid = bytes.fromhex({'bl2': '5ff9ec0b4d223e4da544c39d81c73f0a',
                             'bl31': '47d4086d4cfe98469b952950cbbd5a00',
                             'bl33': 'd6d0eea7fcead54b97829934f234b6e4'}[name])
        for base in FIPS:
            entry = image.index(uid, base + 16, base + 16 + 32 * 40)
            offset, size = struct.unpack_from('<QQ', image, entry + 16)
            image[base + offset + size - 1] ^= 1

    def test_four_ge_with_zero_gpio_is_not_two_p5g(self):
        self.assertEqual(self.detect(self.boot('4ge')), ('4ge', 'conf-1', 'bootmenu 3'))

    def test_both_boards_override_all_gpio_values_and_stale_environment(self):
        for variant, conf in (('4ge', 'conf-1'), ('2p5g', 'conf-0')):
            for gpio in range(8):
                with self.subTest(variant=variant, gpio=gpio):
                    self.assertEqual(self.detect(self.boot(variant), gpio), (variant, conf, 'bootmenu 3'))

    def test_bl33_updates_do_not_change_board_identity(self):
        for variant in ('4ge', '2p5g'):
            image = self.boot(variant)
            self.change_payload(image, 'bl33')
            self.assertEqual(self.detect(image)[0], variant)

    def test_backup_fip_used_after_bad_toc_or_read_error(self):
        for variant in ('4ge', '2p5g'):
            image = self.boot(variant)
            image[FIPS[0]] ^= 1
            self.assertEqual(self.detect(image)[0], variant)
            self.assertEqual([self.lib.metric(i) for i in (0, 1)], [1, 1])
            self.assertEqual(self.detect(self.boot(variant), errors=2)[0], variant)

    def test_corrected_ecc_data_is_accepted(self):
        self.assertEqual(self.detect(self.boot('4ge'), errors=16)[0], '4ge')

    def test_both_early_payloads_must_match(self):
        for name in ('bl2', 'bl31'):
            image = self.boot('4ge')
            self.change_payload(image, name)
            self.assertEqual(self.detect(image, gpio=0)[0], '2p5g')

    def test_unavailable_or_short_flash_reads_fall_back_to_gpio(self):
        image = self.boot('4ge')
        for errors in (1, 6, 8):
            self.assertEqual(self.detect(image, gpio=0, errors=errors)[0], '2p5g')
            self.assertEqual(self.detect(image, gpio=1, errors=errors)[0], '4ge')
        self.assertEqual(self.detect(image[:512], gpio=1)[0], '4ge')

    def test_unknown_firmware_and_gpio_keep_recovery_only(self):
        for gpio in range(2, 8):
            self.assertEqual(self.detect(bytes(0x200000), gpio), ('unknown', '', 'tyfrecovery'))


if __name__ == '__main__':
    unittest.main()
