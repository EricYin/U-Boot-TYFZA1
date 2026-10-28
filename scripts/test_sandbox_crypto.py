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
(testlib / "fit-check.c").write_text(includes.replace("#include <ubi_uboot.h>\n", "") + body + "\nint fixture_verify_system(const struct tyf_payload *p){return verify_system_fit(p); }\n")
shutil.copy2(ROOT / "overlay/board/realtek/tyfza1/boot-config.c", testlib / "boot-config.c")
shutil.copy2(ROOT / "tests/sandbox_fit_command.c", testlib / "fit-command.c")
shutil.copy2(ROOT / "tests/sandbox_boot_capture.c", testlib / "boot-capture.c")
boot = (ROOT / "overlay/board/realtek/tyfza1/tyfza1.c").read_text()
boot = boot[boot.index("static int tyfza1_boot("):boot.index("U_BOOT_CMD(tyfboot")]
(testlib / "boot-test.c").write_text((ROOT / "tests/sandbox_boot_io.h").read_text() +
                                    boot + (ROOT / "tests/sandbox_boot_command.c").read_text())
installer = recovery[recovery.index("static int volume_verify"):recovery.index("static int verify_fit")]
installer += recovery[recovery.index("static int resize_root"):recovery.index("static int read_mtd")]
(testlib / "install-test.c").write_text((ROOT / "tests/sandbox_install_io.h").read_text() + installer + (ROOT / "tests/sandbox_install_command.c").read_text())
shutil.copy2(ROOT / "overlay/board/realtek/tyfza1/sysupgrade.c", testlib / "sysupgrade.c")
(testlib / "Makefile").write_text("obj-y += formats.o certificates.o certificate-crypto.o test-command.o ttl-command.o fit-check.o boot-config.o fit-command.o boot-test.o install-test.o sysupgrade.o boot-capture.o\n")
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
    text = "/dts-v1/; / { description = \"TYFZA1 native audit\"; #address-cells = <1>; images { "
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
swapped = make_fit("swapped")
subprocess.run(["fdtput", "-t", "s", str(swapped), "/configurations/conf-0", "fdt", "four"], check=True)
subprocess.run(["fdtput", "-t", "s", str(swapped), "/configurations/conf-1", "fdt", "two"], check=True)
no_kernel = make_fit("no-kernel")
subprocess.run(["fdtput", "-d", str(no_kernel), "/configurations/conf-0", "kernel"], check=True)
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
        ("foreign-selected-dt",foreign,"conf-0",False), ("corrupt-hash",corrupt,"conf-1",False), ("swapped-four",swapped,"conf-1",False), ("swapped-two",swapped,"conf-0",False), ("missing-kernel",no_kernel,"conf-0",False)]:
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

# Complete sysupgrade install matrix. Optional real user firmware uses the same code.
import io
import os
import tarfile

def add_metadata(data, factory=True):
    metadata = {"supported_devices":["tianyi,tyfza1","tianyi,tyfza1-2p5g"]}
    if factory: metadata["tyfza1_storage"]="factory-v1"
    info=bytes(8)+json.dumps(metadata).encode()
    full=data+info
    return full+struct.pack(">IIB3xI",0x46577830,(~zlib.crc32(full))&0xffffffff,1,len(info)+16)

stream=io.BytesIO()
rootfs=bytearray(2*1024*1024);rootfs[:4]=b"hsqs";struct.pack_into("<Q",rootfs,40,len(rootfs))
with tarfile.open(fileobj=stream,mode="w",format=tarfile.USTAR_FORMAT) as tar:
    for name,data in [("kernel",boot_raw.read_bytes()),("root",rootfs)]:
        entry=tarfile.TarInfo("sysupgrade-tianyi_tyfza1/"+name);entry.size=len(data);tar.addfile(entry,io.BytesIO(data))
install_inputs=[("fixture",add_metadata(stream.getvalue()))]
if os.environ.get("TYFZA1_SYSUPGRADE"):
    install_inputs.append(("user",Path(os.environ["TYFZA1_SYSUPGRADE"]).read_bytes()))
install_rows=[]
for label,data in install_inputs:
    package=fit_work/(label+"-sysupgrade.bin");package.write_bytes(data)
    cases=[]
    for conf in ("conf-0","conf-1"):
        for old in (0,1):
            for previous,layout in [(-1,"oem"),(old,"migrated"),(old,"legacy")]:
                cases.append(("normal",conf,old,previous,0,layout,True,data))
        for fault in (1,2,3,4,5,6,7,8,10,11,12,13):
            cases.append(("fault-"+str(fault),conf,0,1,fault,"migrated",False,data))
        for layout in ("readonly","low-space","wrong-id"):
            cases.append((layout,conf,0,1,0,layout,False,data))
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        root_entry=next(m for m in tar.getmembers() if m.name.endswith("/root"))
    damaged=bytearray(data);damaged[root_entry.offset_data+100]^=1
    cases += [("root-corrupt","conf-0",0,1,0,"migrated",False,bytes(damaged)),
              ("unset-conf","",0,1,0,"migrated",False,data),
              ("truncated","conf-1",0,1,0,"migrated",False,data[:-1]),
              ("missing-metadata","conf-1",0,1,0,"migrated",False,data[:-struct.unpack(">I",data[-4:])[0]])]
    # Repack with valid metadata CRC, so image-structure checks (not CRC) reject it.
    for bad_case in ("missing-script","wrong-kernel-type"):
        broken_kernel=fit_work/"broken-kernel.itb"
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            contents=[(m.name,tar.extractfile(m).read()) for m in tar.getmembers() if m.isfile()]
        broken_kernel.write_bytes(next(b for n,b in contents if n.endswith("/kernel")))
        if bad_case=="missing-script":subprocess.run(["fdtput","-r",str(broken_kernel),"/images/script"],check=True)
        else:subprocess.run(["fdtput","-t","s",str(broken_kernel),"/images/kernel","type","firmware"],check=True)
        repacked=io.BytesIO()
        with tarfile.open(fileobj=repacked,mode="w",format=tarfile.USTAR_FORMAT) as tar:
            for name,content in contents:
                if name.endswith("/kernel"):content=broken_kernel.read_bytes()
                member=tarfile.TarInfo(name);member.size=len(content);tar.addfile(member,io.BytesIO(content))
        cases.append((bad_case,"conf-1",0,1,0,"migrated",False,add_metadata(repacked.getvalue())))
    unmarked=add_metadata(data[:-struct.unpack(">I",data[-4:])[0]],False)
    cases.append(("legacy-metadata-migrated","conf-1",0,1,0,"migrated",False,unmarked))
    for case,conf,old,previous,fault,layout,ok,payload in cases:
        package.write_bytes(payload)
        cmd=(f'host load hostfs - 10000000 {package}; setenv tyf_bootconf {conf}; '
             f'tyfinstall 10000000 {len(payload):x} {old} {previous} {fault} {layout}')
        result=subprocess.run([str(binary),'-d',str(dtb),'-c',cmd],text=True,capture_output=True,timeout=45)
        line=next((x for x in result.stdout.splitlines() if x.startswith("TYF INSTALL ")),"")
        fields=dict(x.split("=",1) for x in line.split()[2:] if "=" in x)
        if not fields or (fields.get("ret")=="0")!=ok or fields.get("isolated")!="1":
            raise RuntimeError(label+" "+case+" "+conf+f" old={old} prev={previous} layout={layout} fault={fault}\n"+result.stdout+result.stderr)
        target=previous if previous>=0 else 1-old
        if ok and (fields.get("bytes")!="1" or fields.get("saves")!="1" or fields.get("commit")!=str(target) or fields.get("active")!=str(target) or fields.get("trying")!="2" or fields.get("slot")!=str(target) or fields.get("conf")!=conf):raise RuntimeError(line)
        if not ok and (fields.get("commit")!=str(old) or fields.get("active")!=str(old) or fields.get("trying")!="2" or fields.get("slot")!=(str(previous) if previous>=0 else "none")):raise RuntimeError(line)
        if not ok and fault!=7 and fields.get("saves")!="0":raise RuntimeError(line)
        if case in ("readonly","low-space","wrong-id","root-corrupt","unset-conf","truncated","missing-metadata","legacy-metadata-migrated","missing-script","wrong-kernel-type") and fields.get("changed")!="0":raise RuntimeError(line)
        install_rows.append({"input":label,"case":case,"conf":conf,"old":old,"previous":previous,"fault":fault,"layout":layout,"result":"passed","receipt":fields})
    package.write_bytes(data)
report={"inputs":[{"name":label,"sha256":hashlib.sha256(data).hexdigest(),"bytes":len(data)} for label,data in install_inputs],"cases":install_rows,"scope":"Production sysupgrade/FIT/CRC/install with RAM-backed UBI and simulated env persistence; no device write or Linux boot"}
(ROOT/"build/sandbox-install-results.json").write_text(json.dumps(report,indent=2)+"\n")
print(json.dumps({"install_cases":len(install_rows),"result":"passed"}))

if os.environ.get("TYFZA1_SYSUPGRADE"):
    data=Path(os.environ["TYFZA1_SYSUPGRADE"]).read_bytes()
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        entry=next(m for m in tar.getmembers() if m.name.endswith("/kernel"))
        kernel=tar.extractfile(entry).read()
    kernel_path=fit_work/"user-kernel.itb";kernel_path.write_bytes(kernel)
    script_bytes=bytes(int(x,16) for x in subprocess.check_output(["fdtget","-t","bx",str(kernel_path),"/images/script","data"],text=True).split())
    # Keep every variable and branch; replace only the final Linux handoff command.
    text=script_bytes.decode().replace("    bootm ","    tyfcapture ")
    if text==script_bytes.decode():raise RuntimeError("No expected bootm handoff")
    (fit_work/"user-boot.cmd").write_text(text)
    subprocess.run([str(ROOT/"build/tyfza1/tools/mkimage"),"-A","arm64","-T","script","-C","none","-d",str(fit_work/"user-boot.cmd"),str(fit_work/"user-boot.scr")],check=True,stdout=subprocess.DEVNULL)
    handoffs=[]
    for conf in ("conf-0","conf-1"):
        for slot in (0,1):
            root="31:12" if slot else "31:9";block="7" if slot else "4"
            cmd=f'host load hostfs - 1000000 {fit_work}/user-boot.scr; setenv root_mtd {root}; setenv b_conf {conf}; setenv unzip_src 0x05000000; source 1000000'
            result=subprocess.run([str(binary),'-d',str(dtb),'-c',cmd],text=True,capture_output=True,timeout=30)
            line=next((l for l in result.stdout.splitlines() if l.startswith("TYF HANDOFF ")),"")
            expected=f'image=0x05000000#{conf} root=ubi_r{slot} block=/dev/ubiblock0_{block} slot={slot}'
            if expected not in line or f'ubi.block=0,ubi_r{slot}' not in line or f'tyfza1.slot={slot}' not in line:raise RuntimeError(result.stdout+result.stderr)
            handoffs.append({"conf":conf,"slot":slot,"receipt":line})
    (ROOT/"build/user-handoff-results.json").write_text(json.dumps({"script_sha256":hashlib.sha256(script_bytes).hexdigest(),"cases":handoffs,"scope":"Actual user FIT script in U-Boot Hush; only bootm replaced by an argument capture command"},indent=2)+"\n")
    print(json.dumps({"user_script_handoffs":len(handoffs),"result":"passed"}))
