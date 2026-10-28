#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run the actual restore and loader-update C against a 256 MiB simulated MTD."""
import ctypes as C
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "overlay/board/realtek/tyfza1"
WORK = ROOT / "build/restore-test"
TOTAL, BOOT, CHUNK, BLOCK = 0x10000000, 0x200000, 0x400000, 0x20000


class Status(C.Structure):
    _fields_ = [("active", C.c_bool), ("id", C.c_uint32), ("next", C.c_size_t), ("total", C.c_size_t)]


class RestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        WORK.mkdir(parents=True, exist_ok=True)
        # Only replace includes at the hardware boundary. Production function bodies
        # and their actual formats.c dependency are compiled without rewriting them.
        recovery = (BOARD / "recovery.c").read_text()
        update = recovery[recovery.index("static int read_mtd("):recovery.index("int tyfza1_rebuild_ubi(")]
        restore = "\n".join(line for line in (BOARD / "restore.c").read_text().splitlines() if not line.startswith("#include"))
        tail = r'''
static void no_poll(void) {}
int test_loader(const void *data,size_t size){return tyfza1_install_loader((ulong)data,size,false,no_poll);}
int test_reset(const void *image, size_t size) {
 restore_release();
 if (flash) munmap(flash, 0x10000000);
 flash = mmap(NULL, 0x10000000, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS, -1, 0);
 if (flash == MAP_FAILED || size != 0x200000) return -1;
 memset(flash, 0xff, 0x10000000); memcpy(flash, image, size);
 allocation_live=allocation_peak=allocation_max=erased_count=bad_count=0;
 fail_write=corrupt_read=-1; detach_error=corrected_reads=references=0;
 return 0;
}
int test_job(const char *op, const void *image, size_t size, size_t total, size_t offset, u32 id) {
 return tyfza1_restore_job(op, (ulong)image, size, total, offset, id, no_poll);
}
size_t test_metric(int key) {
 switch(key) { case 0:return allocation_live; case 1:return allocation_peak;
 case 2:return allocation_max; case 3:return erased_count; case 4:return references; }
 return 0;
}
size_t test_erase_at(size_t i) { return i<erased_count ? erased[i] : (size_t)-1; }
void test_fault(int key, long value) {
 switch(key) { case 0:fail_write=value;break; case 1:corrupt_read=value;break;
 case 2:detach_error=value;break; case 3:corrected_reads=value;break;
 case 4:if(bad_count<8)bad_offsets[bad_count++]=value;break; }
}
int test_range(size_t offset, size_t size, unsigned char value) {
 size_t i; for(i=0;i<size;i++)if(flash[offset+i]!=value)return -1; return 0;
}
'''
        source = WORK / "restore.c"
        source.write_text('#include "restore_io.h"\n' + update + restore + tail)
        library = WORK / "restore.so"
        subprocess.run(["cc", "-O2", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
                        "-I" + str(ROOT / "tests"), "-I" + str(BOARD), str(source), str(BOARD / "formats.c"),
                        str(BOARD / "certificates.c"), str(ROOT / "tests/certificate_openssl.c"),
                        "-lcrypto", "-o", str(library)], check=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.test_loader.argtypes = [C.c_void_p, C.c_size_t]
        cls.lib.test_reset.argtypes = [C.c_void_p, C.c_size_t]
        cls.lib.test_job.argtypes = [C.c_char_p, C.c_void_p, C.c_size_t, C.c_size_t, C.c_size_t, C.c_uint32]
        cls.lib.test_metric.argtypes = [C.c_int]; cls.lib.test_metric.restype = C.c_size_t
        cls.lib.test_erase_at.argtypes = [C.c_size_t]; cls.lib.test_erase_at.restype = C.c_size_t
        cls.lib.test_fault.argtypes = [C.c_int, C.c_long]
        cls.lib.test_range.argtypes = [C.c_size_t, C.c_size_t, C.c_ubyte]
        cls.lib.tyfza1_restore_status.restype = C.POINTER(Status)
        cls.loader = C.create_string_buffer((ROOT / "output/candidate-4ge/taurus_spi_nand_loader.img").read_bytes())
        cls.chunk = C.create_string_buffer(b"\xa5" * CHUNK)
        cls.metrics = []

    def test_universal_update_matches_both_original_profiles(self):
        bundle = (ROOT / 'output/release/tyfza1-uboot-universal.bin').read_bytes()
        for profile in ('4ge', '2p5g'):
            original = (ROOT / f'inputs/{profile}-boot.bin').read_bytes()
            self.assertEqual(self.lib.test_reset(original, BOOT), 0)
            self.assertEqual(self.lib.test_loader(bundle, len(bundle)), 0)
            self.assertEqual(self.lib.test_erase_at(0), 0x100000)
            self.assertEqual(self.lib.test_erase_at(6), 0x40000)

    def test_universal_update_rejects_ambiguous_or_damaged_profile_before_erase(self):
        bundle = (ROOT / 'output/release/tyfza1-uboot-universal.bin').read_bytes()
        header = len(bundle) - 2 * BOOT
        ambiguous = bundle[:header+BOOT] + bundle[header:header+BOOT]
        self.assertNotEqual(self.lib.test_loader(ambiguous, len(ambiguous)), 0)
        self.assertEqual(self.lib.test_metric(3), 0)
        damaged = bytearray(bundle); damaged[header+BOOT+0x40000] ^= 1
        self.assertNotEqual(self.lib.test_loader(bytes(damaged), len(damaged)), 0)
        self.assertEqual(self.lib.test_metric(3), 0)

    def setUp(self):
        self.assertEqual(self.lib.test_reset(self.loader, BOOT), 0)

    def tearDown(self):
        state = self.state()
        if state.active: self.job("restore-cancel", id=state.id)
        self.assertEqual(self.lib.test_metric(0), 0, "Leaked restore allocation")
        self.assertEqual(self.lib.test_metric(4), 0, "Leaked MTD reference")

    @classmethod
    def tearDownClass(cls):
        (ROOT / "evidence/restore-mtd.json").write_text(json.dumps({
            "scope": "Actual production restore.c, loader read/write function bodies and formats.c; simulated MTD I/O, no physical NAND tested",
            "flash_bytes": TOTAL, "upload_chunk_bytes": CHUNK, "runs": cls.metrics}, indent=2) + "\n")

    def state(self):
        return Status.from_buffer_copy(self.lib.tyfza1_restore_status().contents)

    def job(self, op, data=None, size=0, total=0, offset=0, id=0):
        return self.lib.test_job(op.encode(), data, size, total, offset, id)

    def begin(self):
        self.assertEqual(self.job("restore-start", self.loader, BOOT, TOTAL), 0)
        state = self.state(); self.assertTrue(state.active); self.assertEqual(state.next, BOOT)
        return state.id

    def write_all(self, id):
        for offset in range(BOOT, TOTAL, CHUNK):
            self.assertEqual(self.job("restore-chunk", self.chunk, min(CHUNK, TOTAL-offset), offset=offset, id=id), 0)

    def test_full_256m_restore_with_bounded_ram_and_boot_last(self):
        id = self.begin()
        self.write_all(id)
        self.assertEqual(self.state().next, TOTAL)
        before = self.lib.test_metric(3)
        self.assertTrue(all(self.lib.test_erase_at(i) >= BOOT for i in range(before)))
        self.assertEqual(self.lib.test_range(BOOT, TOTAL-BOOT, 0xa5), 0)
        self.assertEqual(self.job("restore-finish", id=id), 0)
        self.assertFalse(self.state().active)
        writes = [self.lib.test_erase_at(i) for i in range(before, self.lib.test_metric(3))]
        self.assertEqual(writes, list(range(0x100000, 0x1c0000, BLOCK)) + list(range(0x40000, 0x100000, BLOCK)))
        self.assertLessEqual(self.lib.test_metric(1), 5 * 1024 * 1024)
        self.assertLessEqual(self.lib.test_metric(2), BOOT)
        self.metrics.append({"case": "full-256m-restore", "engine_peak_allocated_bytes": self.lib.test_metric(1),
                             "largest_engine_allocation": self.lib.test_metric(2), "data_erases_before_boot": before,
                             "boot_erase_order": writes})

    def test_reject_bad_start_before_any_erase(self):
        for size, total in [(BOOT-1, TOTAL), (BOOT, TOTAL-1)]:
            self.assertNotEqual(self.job("restore-start", self.loader, size, total), 0)
        bad = C.create_string_buffer(bytes(BOOT))
        self.assertNotEqual(self.job("restore-start", bad, BOOT, TOTAL), 0)
        self.assertEqual(self.lib.test_metric(3), 0)

    def test_wrong_session_order_alignment_and_premature_finish(self):
        id = self.begin()
        for offset, size, request_id in [(BOOT+CHUNK, CHUNK, id), (BOOT, CHUNK, id+1),
                                         (BOOT, BLOCK-1, id), (BOOT, CHUNK+BLOCK, id)]:
            self.assertNotEqual(self.job("restore-chunk", self.chunk, size, offset=offset, id=request_id), 0)
        self.assertNotEqual(self.job("restore-finish", id=id), 0)
        self.assertEqual(self.lib.test_metric(3), 0)

    def test_write_failure_keeps_offset_and_can_retry(self):
        id = self.begin()
        self.lib.test_fault(0, BOOT+BLOCK)
        self.assertNotEqual(self.job("restore-chunk", self.chunk, CHUNK, offset=BOOT, id=id), 0)
        self.assertEqual(self.state().next, BOOT)
        self.lib.test_fault(0, -1)
        self.assertEqual(self.job("restore-chunk", self.chunk, CHUNK, offset=BOOT, id=id), 0)
        self.assertEqual(self.state().next, BOOT+CHUNK)

    def test_readback_corruption_is_not_committed(self):
        id = self.begin(); self.lib.test_fault(1, BOOT)
        self.assertNotEqual(self.job("restore-chunk", self.chunk, CHUNK, offset=BOOT, id=id), 0)
        self.assertEqual(self.state().next, BOOT)

    def test_bad_blocks_keep_their_physical_offsets(self):
        id = self.begin(); self.lib.test_fault(4, BOOT+BLOCK)
        self.assertEqual(self.job("restore-chunk", self.chunk, CHUNK, offset=BOOT, id=id), 0)
        self.assertEqual(self.lib.test_range(BOOT, BLOCK, 0xa5), 0)
        self.assertEqual(self.lib.test_range(BOOT+BLOCK, BLOCK, 0xff), 0)
        self.assertEqual(self.lib.test_range(BOOT+2*BLOCK, BLOCK, 0xa5), 0)

    def test_corrected_ecc_is_accepted(self):
        id = self.begin(); self.lib.test_fault(3, 1)
        self.assertEqual(self.job("restore-chunk", self.chunk, CHUNK, offset=BOOT, id=id), 0)

    def test_ubi_detach_failure_releases_state(self):
        self.lib.test_fault(2, -5)
        self.assertNotEqual(self.job("restore-start", self.loader, BOOT, TOTAL), 0)
        self.assertFalse(self.state().active); self.assertEqual(self.lib.test_metric(3), 0)

    def test_cancel_invalidates_old_session(self):
        old = self.begin(); self.assertEqual(self.job("restore-cancel", id=old), 0)
        new = self.begin(); self.assertNotEqual(old, new)
        self.assertNotEqual(self.job("restore-chunk", self.chunk, CHUNK, offset=BOOT, id=old), 0)
        self.assertEqual(self.lib.test_metric(3), 0)

    def test_interrupted_boot_update_can_finish_again(self):
        id = self.begin(); self.write_all(id)
        self.lib.test_fault(0, 0x120000)
        self.assertNotEqual(self.job("restore-finish", id=id), 0)
        self.assertTrue(self.state().active)
        self.lib.test_fault(0, -1)
        self.assertEqual(self.job("restore-finish", id=id), 0)
        self.assertFalse(self.state().active)


if __name__ == "__main__":
    unittest.main()
