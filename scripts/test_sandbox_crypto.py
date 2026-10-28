#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run the real U-Boot DER, RSA, PSS and SHA implementation in U-Boot sandbox."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import struct
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_loader_crypto import replace_entries
from verify_loader import loader_entries
import prepare_ttl_recovery as ttl

source = ROOT / "build/u-boot"
testlib = source / "lib/tyfza1-cert-test"
testlib.mkdir(exist_ok=True)
for name in ("formats.h", "formats.c", "certificates.h", "certificates.c", "certificate-crypto.c"):
    shutil.copy2(ROOT / "overlay/board/realtek/tyfza1" / name, testlib / name)
shutil.copy2(ROOT / "tests/sandbox_cert_command.c", testlib / "test-command.c")
shutil.copy2(ROOT / "tests/sandbox_ttl_command.c", testlib / "ttl-command.c")
# Execute the production FIT/configuration checker with real U-Boot image APIs.
recovery = (ROOT / "overlay/board/realtek/tyfza1/recovery.c").read_text()
includes = recovery[:recovery.index("static int volume_verify")]
body = recovery[recovery.index("static int verify_fit"):recovery.index("int tyfza1_boot_upload")]
(testlib / "fit-check.c").write_text(includes.replace("#include <ubi_uboot.h>\n", "") + body)
shutil.copy2(ROOT / "overlay/board/realtek/tyfza1/boot-config.c", testlib / "boot-config.c")
shutil.copy2(ROOT / "tests/sandbox_fit_command.c", testlib / "fit-command.c")
boot = (ROOT / "overlay/board/realtek/tyfza1/tyfza1.c").read_text()
boot = boot[boot.index("static int tyfza1_boot("):boot.index("U_BOOT_CMD(tyfboot")]
(testlib / "boot-test.c").write_text((ROOT / "tests/sandbox_boot_io.h").read_text() +
                                    boot + (ROOT / "tests/sandbox_boot_command.c").read_text())
(testlib / "Makefile").write_text("obj-y += formats.o certificates.o certificate-crypto.o test-command.o ttl-command.o fit-check.o boot-config.o fit-command.o boot-test.o\n")
makefile = source / "lib/Makefile"
line = "obj-$(CONFIG_SANDBOX) += tyfza1-cert-test/\n"
if line not in makefile.read_text():
    with makefile.open("a") as out:
        out.write("\n" + line)
shutil.copy2(ROOT / "tests/sandbox_cert_defconfig", source / "configs/sandbox_tyfza1_cert_defconfig")
shutil.copy2(ROOT / "tests/sandbox-tyfza1-test.dts", source / "arch/sandbox/dts/sandbox-tyfza1-test.dts")
subprocess.run(["make", "-C", str(source), "O=../sandbox-cert", "sandbox_tyfza1_cert_defconfig"], check=True)
subprocess.run(["make", "-C", str(source), "O=../sandbox-cert", "-j6"], check=True)
binary = ROOT / "build/sandbox-cert/u-boot"
dtb = ROOT / "build/sandbox-cert/u-boot.dtb"
rows = []
inputs = []
for variant in ("4ge", "2p5g"):
    path = ROOT / f"output/candidate-{variant}/taurus_spi_nand_loader.img"
    inputs.append((variant, path, True))
image = inputs[0][1].read_bytes()
for name in ("bl33", "nt_cert"):
    damaged = bytearray(loader_entries(image)[name]); damaged[-1] ^= 1
    path = ROOT / f"build/sandbox-cert/bad-{name}.bin"
    path.write_bytes(replace_entries(image, {name: bytes(damaged)}))
    inputs.append(("corrupt-" + name, path, False))
for label, path, valid in inputs:
    command = f"host load hostfs - 1000000 {path}; tyfcert 1000000 200000"
    result = subprocess.run([str(binary), "-d", str(dtb), "-c", command],
                            text=True, capture_output=True, timeout=30)
    if ("TYF CERT OK (0)" if valid else "TYF CERT REJECT") not in result.stdout:
        raise RuntimeError(result.stdout + result.stderr)
    rows.append({"case": label, "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                 "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
report = {"scope": "Actual U-Boot sandbox executable uses production certificate parser, U-Boot RSA public-key parser/software exponentiation/PSS and SHA256; no Taurus NAND tested", "runs": rows}
(ROOT / "evidence/uboot-sandbox-crypto.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({"cases": len(rows), "result": "passed"}))

# Exercise the exact generated legacy image with real source/Hush/hash/memory
# commands. Only NAND I/O is replaced by the bounded host-side fixture.
bundle = (ROOT / "output/release/tyfza1-uboot-universal.bin").read_bytes()
with patch.object(ttl, 'BUNDLE_SHA256', hashlib.sha256(bundle).hexdigest()):
    rescue = ttl.prepare(bundle)
four = (ROOT / 'evidence/stock-boot/4ge-boot.bin').read_bytes()
two = (ROOT / 'evidence/stock-boot/2p5g-boot.bin').read_bytes()
cases = [
    ('check-only', four, rescue, 'check', 0, 'unchanged', 0, 'TTL CHECK OK'),
    ('install-4ge', four, rescue, 'write', 0, 'installed', 2, 'TTL WRITE OK'),
    ('install-2p5g', two, rescue, 'write', 0, 'installed', 2, 'TTL WRITE OK'),
]


def update_gpt_crcs(data, header, table):
    struct.pack_into('<I', data, header + 88, zlib.crc32(data[table:table + 0x4000]))
    struct.pack_into('<I', data, header + 16, 0)
    struct.pack_into('<I', data, header + 16, zlib.crc32(data[header:header + 92]))


identity = bytearray(four)
for h, e in ((0x200, 0x400), (0x1ffe00, 0x1fbe00)):
    identity[h + 56:h + 72] = bytes(range(16))
    identity[e + 16:e + 32] = b'\x42' * 16
    for i, last in enumerate((0x79e, 0xd9e)):
        struct.pack_into('<Q', identity, e + i * 128 + 40, last)
    update_gpt_crcs(identity, h, e)
cases.append(('per-device-gpt', bytes(identity), rescue, 'write', 0, 'installed', 2, 'TTL WRITE OK'))
for label, offset in (('bad-gpt-crc', 0x210), ('reserved-change', 0x1d0000)):
    damaged = bytearray(four); damaged[offset] ^= 1
    cases.append((label, bytes(damaged), rescue, 'write', 0, 'unchanged', 0, 'TTL STOP'))
foreign = bytearray(four)
for at in (0x40000, 0x100000): foreign[at + 0x1a0] ^= 1
cases.append(('foreign-early-firmware', bytes(foreign), rescue, 'write', 0, 'unchanged', 0, 'TTL STOP'))
bad_table = bytearray(four); bad_table[0x410] ^= 1
cases.append(('bad-table-crc', bytes(bad_table), rescue, 'write', 0, 'unchanged', 0, 'TTL STOP'))
capacity = bytearray(four)
for h, e in ((0x200, 0x400), (0x1ffe00, 0x1fbe00)):
    struct.pack_into('<Q', capacity, e + 40, 0x800)
    update_gpt_crcs(capacity, h, e)
cases.append(('bad-fip-capacity', bytes(capacity), rescue, 'write', 0, 'unchanged', 0, 'TTL STOP'))
split = bytearray(four)
struct.pack_into('<Q', split, 0x428, 0x79e)
update_gpt_crcs(split, 0x200, 0x400)
cases.append(('split-gpt-lengths', bytes(split), rescue, 'write', 0, 'unchanged', 0, 'TTL STOP'))
for fault, label, state, erased in ((1, 'bad-block', 'unchanged', 0),
                                    (2, 'erase-failure', 'unchanged', 0),
                                    (3, 'write-failure', 'primary', 1),
                                    (4, 'readback-failure', 'primary', 1)):
    cases.append((label, four, rescue, 'write', fault, state, erased, 'TTL STOP'))
corrupt = bytearray(rescue); corrupt[ttl.PAYLOAD + 512] ^= 1
cases.append(('bad-script-crc', four, bytes(corrupt), 'write', 0, 'unchanged', 0, 'Bad data crc'))
# Keep the outer CRCs valid to ensure the embedded SHA256 gate is exercised.
struct.pack_into('>I', corrupt, 24, zlib.crc32(corrupt[64:]))
struct.pack_into('>I', corrupt, 4, 0)
struct.pack_into('>I', corrupt, 4, zlib.crc32(corrupt[:64]))
cases.append(('wrong-embedded-package', four, bytes(corrupt), 'write', 0, 'unchanged', 0, 'TTL STOP'))
ttl_rows = []
for label, boot, script, action, fault, state, erased, message in cases:
    old_path = ROOT / f'build/sandbox-cert/ttl-{label}-boot.bin'
    script_path = ROOT / f'build/sandbox-cert/ttl-{label}.scr'
    old_path.write_bytes(boot); script_path.write_bytes(script)
    command = (f'host load hostfs - 10000000 {old_path}; ttlfixture 10000000 {fault:x}; '
               f'host load hostfs - 11000000 {script_path}; setenv verify yes; '
               f'setenv ttl_action {action}; source 11000000; ttlassert {state} {erased:x}')
    result = subprocess.run([str(binary), '-d', str(dtb), '-c', command],
                            text=True, capture_output=True, timeout=45)
    if message not in result.stdout or 'TTL ASSERT OK' not in result.stdout or 'TTL ASSERT FAILED' in result.stdout:
        raise RuntimeError(label + '\n' + result.stdout + result.stderr)
    ttl_rows.append({'case': label, 'result': 'passed', 'expected_erases': erased})
(ROOT / 'evidence/ttl-recovery-sandbox.json').write_text(json.dumps({
    'scope': 'Generated recovery image executed by real U-Boot source/Hush/hash/memory commands; NAND calls modeled, no physical Flash writes',
    'cases': ttl_rows,
}, indent=2) + '\n')
print(json.dumps({'ttl_recovery_cases': len(ttl_rows), 'result': 'passed'}))

# FIT selection must depend on the explicit Linux setting, not stale board vars.
import lzma
fit_work = ROOT / "build/sandbox-fit"
fit_work.mkdir(exist_ok=True)
(fit_work / "script").write_text("setenv fixture_executed ${b_conf}\n")
(fit_work / "kernel").write_bytes(b"TYFZA1 audit payload" * 64)
for name, compatible in (("four", '"tianyi,tyfza1", "realtek,rtl9617c"'),
                         ("two", '"tianyi,tyfza1-2p5g", "tianyi,tyfza1", "realtek,rtl9617c"'),
                         ("foreign", '"other,board"')):
    dts = fit_work / (name + ".dts")
    dts.write_text('/dts-v1/; / { compatible = ' + compatible + '; };\n')
    dt = fit_work / (name + ".dtb")
    subprocess.run(["dtc", "-I", "dts", "-O", "dtb", "-o", str(dt), str(dts)], check=True)
    dt.with_suffix('.lzma').write_bytes(lzma.compress(dt.read_bytes(), format=lzma.FORMAT_ALONE))


def make_fit(name, comp="none", foreign=False, omit=False, scripted=False):
    ext = "lzma" if comp == "lzma" else "dtb"
    second = "foreign" if foreign else "two"
    text = "/dts-v1/; / { description = \"TYFZA1 audit\"; #address-cells = <1>; images { "
    if scripted: text += 'script { data = /incbin/("script"); type = "script"; arch = "arm64"; compression = "none"; hash { algo = "sha256"; }; };'
    text += 'kernel { data = /incbin/("kernel"); type = "kernel"; arch = "arm64"; os = "linux"; compression = "none"; hash { algo = "sha256"; }; };'
    for node, file in (("four", "four"), ("two", second)):
        text += f'{node} {{ data = /incbin/("{file}.{ext}"); type = "flat_dt"; arch = "arm64"; compression = "{comp}"; hash {{ algo = "sha256"; }}; }};'
    text += '}; configurations { default = "conf-1"; conf-1 { kernel = "kernel"; fdt = "four"; };'
    if not omit: text += 'conf-0 { kernel = "kernel"; fdt = "two"; };'
    text += '}; };'
    (fit_work / (name + ".its")).write_text(text)
    subprocess.run([str(ROOT / "build/tyfza1/tools/mkimage"), "-f", name+".its", name+".itb"], cwd=fit_work, check=True, stdout=subprocess.DEVNULL)
    return fit_work / (name+".itb")

raw = make_fit("raw")
compressed = make_fit("compressed", "lzma")
foreign = make_fit("foreign", foreign=True)
missing = make_fit("missing", omit=True)
bad = bytearray(raw.read_bytes()); at=bad.index(b"TYFZA1 audit payload"); bad[at]^=1
corrupt = fit_work / "corrupt.itb"; corrupt.write_bytes(bad)
fit_cases=[]
for label,path,conf,ok in [("unaligned-four",raw,"conf-1",True),
        ("unaligned-two",raw,"conf-0",True), ("compressed-four",compressed,"conf-1",True),
        ("compressed-two",compressed,"conf-0",True), ("unset-ignores-old-auto",raw,"",False),
        ("invalid-setting",raw,"conf-2",False), ("missing-configuration",missing,"conf-0",False),
        ("foreign-selected-dt",foreign,"conf-0",False), ("corrupt-hash",corrupt,"conf-1",False)]:
    command = (f'host load hostfs - 1000000 {path}; setenv b_conf conf-0; setenv board_variant 2p5g; '
               f'setenv tyf_bootconf {conf}; tyffit 1000000 {path.stat().st_size:x}')
    result=subprocess.run([str(binary),'-d',str(dtb),'-c',command],text=True,capture_output=True,timeout=30)
    expected="TYF FIT OK (0)" if ok else "TYF FIT REJECT"
    if expected not in result.stdout: raise RuntimeError(label+"\n"+result.stdout+result.stderr)
    fit_cases.append({"case":label,"result":"passed","expected_accept":ok})
(ROOT / "build/sandbox-fit-results.json").write_text(json.dumps(fit_cases,indent=2)+"\n")
print(json.dumps({"fit_cases":len(fit_cases),"result":"passed"}))

boot_raw = make_fit("boot-raw", scripted=True)
boot_compressed = make_fit("boot-compressed", "lzma", scripted=True)
boot_bad = bytearray(boot_raw.read_bytes()); boot_bad[boot_bad.index(b"TYFZA1 audit payload")] ^= 1
boot_corrupt = fit_work / "boot-corrupt.itb"; boot_corrupt.write_bytes(boot_bad)
boot_cases=[]
for label,path,conf,slot,used,read_error,ok in [
        ("static-four",boot_raw,"conf-1","0",boot_raw.stat().st_size,0,True),
        ("static-two",boot_compressed,"conf-0","1",boot_compressed.stat().st_size,0,True),
        ("dynamic-padding",boot_raw,"conf-1","1",0x60e000,0,True),
        ("truncated-volume",boot_raw,"conf-1","0",boot_raw.stat().st_size-1,0,False),
        ("read-failure",boot_raw,"conf-1","0",boot_raw.stat().st_size,1,False),
        ("corrupt-data",boot_corrupt,"conf-1","0",boot_corrupt.stat().st_size,0,False),
        ("unconfigured",boot_raw,"","0",boot_raw.stat().st_size,0,False),
        ("invalid-slot",boot_raw,"conf-1","2",boot_raw.stat().st_size,0,False)]:
    size=path.stat().st_size
    command=(f'host load hostfs - 1000000 {path}; setenv tyf_bootconf {conf}; '
             f'setenv sw_commit {slot}; tyfbfixture 1000000 {size:x} {used:x} {read_error}')
    result=subprocess.run([str(binary),'-d',str(dtb),'-c',command],text=True,capture_output=True,timeout=30)
    expected=(f'TYF BOOT OK read={size:x} volume=ubi_k{slot} script={conf}' if ok else 'TYF BOOT REJECT')
    if expected not in result.stdout or (not ok and 'script=none' not in result.stdout):
        raise RuntimeError(label+"\n"+result.stdout+result.stderr)
    boot_cases.append({"case":label,"result":"passed","expected_boot":ok})
(ROOT / "build/sandbox-boot-results.json").write_text(json.dumps(boot_cases,indent=2)+"\n")
print(json.dumps({"boot_cases":len(boot_cases),"result":"passed"}))
