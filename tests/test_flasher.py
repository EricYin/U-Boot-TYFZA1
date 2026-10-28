#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise Linux flasher production writes against an emulated MTD boundary."""
import ctypes as C
from pathlib import Path
import subprocess
import struct
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
BLOCK, BOOT = 0x20000, 0x200000
FIPS = list(range(0x100000, 0x1c0000, BLOCK)) + list(range(0x40000, 0x100000, BLOCK))

class FlasherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        work = ROOT / 'build/flasher-test'
        work.mkdir(parents=True, exist_ok=True)
        source = work / 'flasher.c'
        source.write_text(r'''#include <stdarg.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include <mtd/mtd-user.h>
#include <errno.h>
static int fault, erases;
static unsigned int offsets[16];
static int mock_ioctl(int fd, unsigned long request, ...) {
 va_list args; void *p; va_start(args, request); p = va_arg(args, void *); va_end(args);
 if (request == MEMGETBADBLOCK) return fault == 1 && *(off_t *)p == 0x40000;
 if (request == MEMERASE) {
  struct erase_info_user *e = p;
  if (fault == 2 && e->start == 0x120000) { errno = EIO; return -1; }
  offsets[erases++] = e->start; return 0;
 }
 (void)fd; return -1;
}
static ssize_t mock_pread(int fd, void *data, size_t size, off_t offset) {
 ssize_t n = pread(fd, data, size, offset);
 if (fault == 3 && offset == 0x100000 && n > 0) ((char *)data)[0] ^= 1;
 return n;
}
#define main flasher_program_main
#define ioctl mock_ioctl
#define pread mock_pread
#include "tools/flash_uboot.c"
#undef main
int test_write(int fd, const unsigned char *data, int mode) {
 fault = mode; erases = 0; return write_fips(fd, data);
}
int test_erases(void) { return erases; }
unsigned int test_offset(int i) { return offsets[i]; }
int test_select(const unsigned char *bundle, const unsigned char *current) {
 struct tyf_payload selected;
 const char *variant = select_boot_profile(bundle, current, &selected);
 return variant ? strcmp(variant, "4ge") != 0 : -1;
}
int test_install(int fd, const unsigned char *bundle, const unsigned char *current) {
 struct tyf_payload selected;
 fault = erases = 0;
 if (!select_boot_profile(bundle, current, &selected)) return -1;
 return write_fips(fd, selected.data);
}
''')
        board = ROOT / 'overlay/board/realtek/tyfza1'
        library = work / 'flasher.so'
        subprocess.run(['cc', '-O2', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        '-I'+str(ROOT), '-I'+str(board), str(source), str(board/'formats.c'),
                        str(board/'certificates.c'), str(ROOT/'tests/certificate_openssl.c'),
                        '-lcrypto', '-o', str(library)], check=True)
        cls.lib = C.CDLL(str(library)); cls.lib.test_write.argtypes = [C.c_int, C.c_void_p, C.c_int]
        cls.lib.test_select.argtypes = [C.c_void_p, C.c_void_p]
        cls.lib.test_install.argtypes = [C.c_int, C.c_void_p, C.c_void_p]
        cls.image = bytes((i//BLOCK + 1) % 256 for i in range(BOOT))
        cls.buffer = C.create_string_buffer(cls.image)

    def run_write(self, fault):
        with tempfile.TemporaryFile() as flash:
            original = bytes([0xa5])*BOOT
            flash.write(original); flash.flush()
            result = self.lib.test_write(flash.fileno(), self.buffer, fault)
            flash.seek(0); after = flash.read()
        offsets = [self.lib.test_offset(i) for i in range(self.lib.test_erases())]
        return result, offsets, original, after

    def stock_with_reported_lengths(self, variant):
        current = bytearray((ROOT / f'evidence/stock-boot/{variant}-boot.bin').read_bytes())
        for header, entries in ((0x200, 0x400), (0x1ffe00, 0x1fbe00)):
            for index, last in enumerate((0x79e, 0xd9e)):
                struct.pack_into('<Q', current, entries + index * 128 + 0x28, last)
            struct.pack_into('<I', current, header + 88, zlib.crc32(current[entries:entries + 0x4000]))
            struct.pack_into('<I', current, header + 16, 0)
            struct.pack_into('<I', current, header + 16, zlib.crc32(current[header:header + 92]))
        return bytes(current)

    def test_board_selection_with_reported_oem_fip_lengths(self):
        bundle = (ROOT / 'output/release/tyfza1-uboot-universal.bin').read_bytes()
        for variant, expected in (('4ge', 0), ('2p5g', 1)):
            current = self.stock_with_reported_lengths(variant)
            with self.subTest(variant=variant):
                self.assertEqual(self.lib.test_select(C.create_string_buffer(bundle),
                                 C.create_string_buffer(current)), expected)

    def test_install_with_oem_lengths_preserves_gpt_and_remains_updatable(self):
        bundle = (ROOT / 'output/release/tyfza1-uboot-universal.bin').read_bytes()
        for variant, index in (('4ge', 0), ('2p5g', 1)):
            before = self.stock_with_reported_lengths(variant)
            image = bundle[16 + index * BOOT:16 + (index + 1) * BOOT]
            with self.subTest(variant=variant), tempfile.TemporaryFile() as flash:
                flash.write(before); flash.flush()
                self.assertEqual(self.lib.test_install(flash.fileno(), C.create_string_buffer(bundle),
                                 C.create_string_buffer(before)), 0)
                offsets = [self.lib.test_offset(i) for i in range(self.lib.test_erases())]
                self.assertEqual(offsets, FIPS)
                flash.seek(0); after = flash.read()
                expected = bytearray(before)
                for off in FIPS: expected[off:off+BLOCK] = image[off:off+BLOCK]
                self.assertEqual(after, expected)
                self.assertEqual(self.lib.test_select(C.create_string_buffer(bundle),
                                 C.create_string_buffer(after)), index)

    def test_bad_package_signature_stops_before_any_erase(self):
        original = (ROOT / 'output/release/tyfza1-uboot-universal.bin').read_bytes()
        before = self.stock_with_reported_lengths('4ge')
        for index in (0, 1):
            damaged = bytearray(original)
            for off in (0x40000, 0x100000):
                base = 16 + index * BOOT + off
                # Damage a certificate while keeping both copies' boot payloads intact.
                _, offset, length, _ = struct.unpack_from('<16sQQQ', damaged, base + 16 + 8 * 40)
                damaged[base + offset + length - 1] ^= 1
            with self.subTest(index=index), tempfile.TemporaryFile() as flash:
                flash.write(before); flash.flush()
                self.assertNotEqual(self.lib.test_install(flash.fileno(), C.create_string_buffer(bytes(damaged)),
                                    C.create_string_buffer(before)), 0)
                self.assertEqual(self.lib.test_erases(), 0)
                flash.seek(0); self.assertEqual(flash.read(), before)

    def test_secondary_first_and_only_fip_ranges_changed(self):
        result, offsets, before, after = self.run_write(0)
        self.assertEqual(result, 0); self.assertEqual(offsets, FIPS)
        expected = bytearray(before)
        for off in FIPS: expected[off:off+BLOCK] = self.image[off:off+BLOCK]
        self.assertEqual(after, expected)

    def test_all_bad_blocks_checked_before_first_erase(self):
        result, offsets, before, after = self.run_write(1)
        self.assertNotEqual(result, 0); self.assertEqual(offsets, []); self.assertEqual(after, before)

    def test_secondary_failure_keeps_primary_intact(self):
        result, offsets, before, after = self.run_write(2)
        self.assertNotEqual(result, 0); self.assertEqual(offsets, [0x100000])
        self.assertEqual(after[:0x100000], before[:0x100000])

    def test_readback_corruption_stops_before_next_erase(self):
        result, offsets, before, after = self.run_write(3)
        self.assertNotEqual(result, 0); self.assertEqual(offsets, [0x100000])
        self.assertEqual(after[:0x100000], before[:0x100000])

if __name__ == '__main__': unittest.main()
