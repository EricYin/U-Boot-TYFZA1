#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prepare pinned U-Boot sources without modifying either upstream checkout."""
import json
import re
from pathlib import Path
import shutil
import subprocess
import gzip
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def replace(path, old, new):
    text = path.read_text()
    if old not in text:
        raise RuntimeError(f"Source contract changed: {path}: {old!r}")
    path.write_text(text.replace(old, new))


def build_identity(root):
    version = (root / "VERSION").read_text().strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+", version):
        raise ValueError("VERSION must have two components, for example 1.1")
    git = ["git", "-C", str(root)]
    top = subprocess.run([*git, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if top.returncode or Path(top.stdout.strip()).resolve() != root.resolve():
        return version, ""
    commit = subprocess.check_output([*git, "rev-parse", "--short=7", "HEAD"], text=True).strip()
    if subprocess.check_output([*git, "status", "--porcelain", "--untracked-files=normal"], text=True):
        commit += "-dirty"
    return version, commit


def main():
    lock = json.loads((ROOT / "source-lock.json").read_text())
    for source in lock.values():
        path = ROOT / "sources" / source["directory"]
        actual = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
        if actual != source["commit"]:
            raise RuntimeError(f"Wrong source revision: {path}: {actual}")
    dest = ROOT / "build/u-boot"
    fresh = not dest.exists()
    if not fresh:
        if json.loads((dest / ".tyfza1-sources.json").read_text()) != lock:
            raise RuntimeError("Prepared source revision differs from source-lock.json")
    else:
        dest.mkdir(parents=True)
        reference = ROOT / "sources" / lock["reference"]["directory"]
        proc = subprocess.Popen(["git", "-C", str(reference), "archive", lock["reference"]["commit"]], stdout=subprocess.PIPE)
        with tarfile.open(fileobj=proc.stdout, mode="r|") as archive:
            archive.extractall(dest, filter="data")
        if proc.wait():
            raise RuntimeError("git archive failed")
    vendor = ROOT / "sources" / lock["realtek"]["directory"] / lock["realtek"]["subdirectory"]
    common = vendor / "board/realtek_10G_PON/common"
    board = dest / "board/realtek/tyfza1"
    (board / "vendor/eth_ni_taurus.c").unlink(missing_ok=True)
    for name in ["eth_ni.c", "eth_ni.h"]:
        out = board / "vendor" / name
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(common / name, out)
    shutil.copy2(vendor / "drivers/gpio/cortina_gpio.c", board / "vendor/gpio.c")
    for name in ["cortina_spi_nand.c", "cortina_spi_nand.h", "cortina_spi_nand_base.c", "spi-nand-core.c"]:
        out = board / "vendor/spi_nand" / name
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(common / "spi_nand" / name, out)
    regs = dest / "arch/arm/include/asm/arch-taurus/registers.h"
    regs.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(vendor / "arch/arm/include/asm/arch-taurus/registers.h", regs)
    # U-Boot removed common.h; include the actual interfaces in imported code.
    compat = "#include <config.h>\n#include <dm.h>\n#include <env.h>\n#include <init.h>\n#include <stdio.h>\n#include <vsprintf.h>\n#include <linux/types.h>\n#include <linux/kernel.h>\n#include <asm/arch/registers.h>"
    for path in (board / "vendor").rglob("*.c"):
        replace(path, "#include <common.h>", compat)
        text = path.read_text()
        if text.count("#include <dm.h>") > 1:
            path.write_text(text.replace("#include <dm.h>", "", 1))
    replace(board / "vendor/eth_ni.c", "static struct phy_driver ni_internal =", "U_BOOT_PHY_DRIVER(tyfza1_internal) =")
    replace(board / "vendor/eth_ni.c", "\tphy_register(&ni_internal);", "")
    replace(board / "vendor/eth_ni.c", "cmdtp->help", "cmdtp->usage")
    ni = board / "vendor/eth_ni.c"
    text = ni.read_text()
    begin = text.index("static ca_status_t __ca_mdio_c45_write")
    end = text.index("static struct phy_device *__get_curr_phydev", begin)
    text = text[:begin] + (ROOT / "overlay/board/realtek/tyfza1/ni-mdio.inc").read_text() + "\n" + text[end:]
    begin = text.index("static ca_status_t __ca_mdio_c45_write")
    end = text.index("static int cortina_ni_start", begin)
    text = text[:begin] + text[end:]
    begin = text.index("static int do_phy_c45")
    end = text.index("static const struct eth_ops", begin)
    text = text[:begin] + text[end:]
    begin = text.index("\tint i, ret;", text.index("static int cortina_of_to_plat"))
    end = text.index('\tpriv->rxmode =', begin)
    text = text[:begin] + "\tinit_port_map(priv);\n\n" + text[end:]
    begin = text.index("\tif (priv->is_qxsgmii)")
    end = text.index("\n}", begin)
    text = text[:begin] + text[end:]
    begin = text.index("\t/* bulk reset gpios */")
    end = text.index("\tpriv->rx_xram_base_adr", begin)
    text = text[:begin] + text[end:]
    begin = text.index("\t/* hardware settings for RGMII port */")
    end = text.index("#endif", begin)
    text = text[:begin] + text[end:]
    begin = text.index("static int cortina_ni_probe")
    text = text[:begin] + text[begin:].replace("int i, ret;", "int ret;", 1)
    # Recovery always follows a live internal jack, including old OEM envs.
    begin = text.index("static void set_active_port")
    end = text.index("int __weak aal_mode_sync", begin)
    text = text[:begin] + text[end:]
    begin = text.index("\tset_active_port(priv, 0);")
    end = text.index("\n#if", begin)
    text = text[:begin] + "\tpriv->active_port = 0;\n\tpriv->active_scan = 1;\n" + text[end:]
    text = text.replace("\tchar\t\t\t*buf;\n\tint portid, active_scan;\n", "")
    ni.write_text(text)
    replace(ni, "static int cortina_ni_start(struct udevice *dev)", "static void init_port_map(struct cortina_ni_priv *priv);\n\nstatic int cortina_ni_start(struct udevice *dev)")
    replace(ni, "\tif (!priv->is_phyinited) {\n\t\tint i, val;", "\tif (!priv->is_phyinited) {\n\t\tint i, val;\n\t\t/* Retry from the physical map, not last attempt's disabled ports. */\n\t\tinit_port_map(priv);")
    replace(board / "vendor/eth_ni.c", "static int cortina_ni_start(struct udevice *dev)", '#include "../ni-board.inc"\n\nstatic int cortina_ni_start(struct udevice *dev)')
    replace(board / "vendor/eth_ni.c", "static void ni_auto_scan_active_port", "static int tyf_ni_phy_status(struct phy_device *phy);\n\nstatic void ni_auto_scan_active_port")
    replace(board / "vendor/eth_ni.c", "\t\tphy_startup(phydev);", "\t\ttyf_ni_phy_status(phydev);")
    replace(board / "vendor/eth_ni.c", "\t\tphy_startup(p);", "\t\ttyf_ni_phy_status(p);")
    replace(board / "vendor/eth_ni.c", "\t\tint i, val;", "\t\tint i, val, usable = 0;")
    replace(board / "vendor/eth_ni.c", "\tif (priv->active_port < 0)\n\t\treturn NULL;",
            "\tif (!is_valid_port(priv, priv->active_port))\n\t\treturn NULL;")
    replace(board / "vendor/eth_ni.c", "\t\t\tif (phydev) {\n\t\t\t\tprintf", "\t\t\tif (!phydev) {\n\t\t\t\tprintf(\"Recovery PHY missing: port %d, MDIO %d; disabling this port\\n\", i, m->phy_id);\n\t\t\t\tm->phy_id = -1;\n\t\t\t\tcontinue;\n\t\t\t}\n\t\t\tif (phydev) {\n\t\t\t\tprintf")
    replace(board / "vendor/eth_ni.c", '\tprintf("CA NI version 0.9(DM_ETH)\\n");', '\tret = tyf_ni_board_prepare(priv);\n\tif (ret) return ret;\n\tprintf("CA NI version 0.9(DM_ETH)\\n");')
    replace(board / "vendor/eth_ni.c", "\t\t\t\tphy_config(phydev);\n\n\t\t\t\tval = phy_read", "\t\t\t\tval = phy_config(phydev);\n\t\t\t\tif (val) {\n\t\t\t\t\tprintf(\"Recovery PHY port %d initialization failed (%d); disabling this port\\n\", i, val);\n\t\t\t\t\tphydev->link = 0;\n\t\t\t\t\tm->phy_id = -1;\n\t\t\t\t\tcontinue;\n\t\t\t\t}\n\n\t\t\t\tval = phy_read")
    replace(board / "vendor/eth_ni.c", '''\t\t\t\tval &= ~BMCR_PDOWN;
\t\t\t\tphy_write(phydev, MDIO_DEVAD_NONE, MII_BMCR, val);''', '''\t\t\t\tif (val >= 0)
\t\t\t\t\tval = phy_write(phydev, MDIO_DEVAD_NONE, MII_BMCR, val & ~BMCR_PDOWN);
\t\t\t\tif (val < 0) {
\t\t\t\t\tprintf("Recovery PHY port %d resume failed (%d); disabling this port\\n", i, val);
\t\t\t\t\tphydev->link = 0;
\t\t\t\t\tm->phy_id = -1;
\t\t\t\t\tcontinue;
\t\t\t\t}
\t\t\t\tusable++;''')
    replace(board / "vendor/eth_ni.c", "\t\tni_auto_scan_active_port(priv);\n\t\tpriv->is_phyinited = 1;", '''\t\tif (!usable) return -ENODEV;
\t\t/* A failed manually selected port must not hide healthy recovery ports. */
\t\tif (!is_valid_port(priv, priv->active_port)) priv->active_scan = 1;
\t\tni_auto_scan_active_port(priv);
\t\tpriv->is_phyinited = 1;''')
    replace(board / "vendor/eth_ni.c", '\t} else\n\t\tprintf("No PHY available\\n");', '\t} else\n\t\tputs("Recovery will wait for a LAN link.\\n");')
    replace(board / "vendor/eth_ni.c", "\t\tpriv->aal_mode_sync(priv->active_port, priv->maps[priv->active_port].sds_mode,\n\t\t\t\t    p);", "\t\tif (priv->aal_mode_sync(priv->active_port, priv->maps[priv->active_port].sds_mode, p))\n\t\t\treturn -EIO;")
    replace(ni, '\t\tif (p->link)\n\t\t\tprintf', '\t\tif (!p->link) { priv->phydev = NULL; goto wait_link; }\n\t\tif (p->link)\n\t\t\tprintf')
    replace(ni, '\t} else\n\t\tputs("Recovery will wait for a LAN link.\\n");', '\t}\nwait_link:\n\tif (!priv->phydev) puts("Recovery will wait for a LAN link.\\n");')
    replace(ni, "\tni_enable_tx_rx(priv->active_port, 1);", "\tif (priv->phydev && priv->phydev->link) ni_enable_tx_rx(priv->active_port, 1);")
    replace(board / "vendor/eth_ni.c", "\t/* get the hw write pointer */", "\tif (tyf_ni_refresh_link(priv)) return -EIO;\n\n\t/* get the hw write pointer */")
    replace(board / "vendor/eth_ni.c", "\tstatic unsigned char   pkt_buf[2048];", "\tstatic unsigned char   pkt_buf[2048];\n\tif (!priv->phydev || !priv->phydev->link) return -ENETDOWN;\n\tif (length < 0 || length > 1518) return -EMSGSIZE;")
    replace(board / "vendor/eth_ni.c", '''\tif (hw_tx_rd_ptr != sw_tx_wr_ptr) {
\t\tprintf("%s: Tx FIFO is not available!\\n", __func__);
\t\treturn 1;
\t}''', '''\t/* lwIP may send consecutive TCP ACKs before the previous frame drains. */
\tfor (loop = 0; hw_tx_rd_ptr != sw_tx_wr_ptr && loop < 10000; loop++) {
\t\tudelay(1);
\t\thw_tx_rd_ptr = CORTINA_CA_REG_READ(NI_HV_XRAM_CPUXRAM_CPU_STAT_TX_0);
\t}
\tif (hw_tx_rd_ptr != sw_tx_wr_ptr) {
\t\tprintf("%s: TX timeout (read=%x write=%x)\\n", __func__, hw_tx_rd_ptr, sw_tx_wr_ptr);
\t\treturn -ETIMEDOUT;
\t}''')
    # XRAM rounds its storage slots; bytes_valid carries the exact wire length.
    # Padding a 1514-byte Ethernet frame to an 8-byte boundary exceeds the MTU.
    replace(board / "vendor/eth_ni.c",
            "\t/* a workaround on 2015/10/01 the packet size+CRC should be 8-byte alignment */\n\tif (((length + 4) % 8) != 0)\n\t\tlength += (8 - ((length + 4) % 8));",
            "\t/* Keep Ethernet length unchanged; XRAM bytes_valid handles its last word. */")
    # RTL9617C TX valid-byte bits are 14:12; the imported bitfield uses 13:10.
    replace(board / "vendor/eth_ni.c", "hdr_xt.bf.bytes_valid = valid_bytes;",
            "hdr_xt.wrd |= (u32)valid_bytes << 12;")
    replace(board / "vendor/eth_ni.c", "if (packet_status.bf.packet_size > 1518) {", "if (packet_status.bf.packet_size > 1518 || packet_status.bf.packet_size < 18) {")
    replace(board / "vendor/eth_ni.h", "\tuint8_t is_qxsgmii;", "\tuint8_t is_qxsgmii;\n\tunsigned long link_polled;")
    replace(board / "vendor/eth_ni.c", "//ni_enable_tx_rx(priv->active_port, 0);", "if (is_valid_port(priv, priv->active_port))\n\t\tni_enable_tx_rx(priv->active_port, 0);")
    replace(board / "vendor/spi_nand/cortina_spi_nand_base.c", "#include <watchdog.h>", "#include <u-boot/schedule.h>")
    # Recovery lamps: redraw in NAND loops and count written bytes for the progress bar.
    replace(board / "vendor/spi_nand/cortina_spi_nand_base.c", "#include <u-boot/schedule.h>", "#include <u-boot/schedule.h>\n#include <tyfza1_recovery.h>")
    replace(board / "vendor/spi_nand/cortina_spi_nand_base.c", "WATCHDOG_RESET();", "schedule();\n\t\ttyfza1_recovery_leds_poll();")
    replace(board / "vendor/spi_nand/cortina_spi_nand_base.c", "            ops->retlen += size_d;\n", "            ops->retlen += size_d;\n            tyfza1_recovery_leds_progress(size_d);\n")
    replace(board / "vendor/spi_nand/cortina_spi_nand_base.c", "    \t\tops->retlen += size;\n    \t\twritelen -= size;\n", "    \t\tops->retlen += size;\n    \t\ttyfza1_recovery_leds_progress(size);\n    \t\twritelen -= size;\n")
    replace(board / "vendor/spi_nand/cortina_spi_nand_base.c", "(corrected >= (info->ecc_strength-2))", "(*corrected >= (info->ecc_strength-2))")
    replace(board / "vendor/spi_nand/cortina_spi_nand_base.c", "int timeout = start + CONFIG_SYS_HZ;", "int timeout = CONFIG_SYS_HZ;")
    replace(board / "vendor/spi_nand/cortina_spi_nand_base.c",
            "\tif(!chip || !info)\n\t\treturn -ENOMEM;",
            "\tif(!chip || !info)\n\t\treturn -ENOMEM;\n\tinfo->mtd = mtd;")
    replace(board / "vendor/spi_nand/cortina_spi_nand_base.c",
            "ident_done:\n", "ident_done:\n    mtd->size = info->size;\n")
    replace(board / "vendor/spi_nand/spi-nand-core.c", "#include <nand.h>", "#include <nand.h>\n#include <linux/mtd/rawnand.h>")
    shutil.copytree(ROOT / "overlay", dest, dirs_exist_ok=True)
    version, commit = build_identity(ROOT)
    replace(dest / "configs/tyfza1_defconfig", 'CONFIG_IDENT_STRING=" TYFZA1"', f'CONFIG_IDENT_STRING=" TYFZA1 {version}"')
    (dest / "include/tyfza1_build.h").write_text(
        f"#define TYFZA1_PROJECT_VERSION {json.dumps(version)}\n"
        f"#define TYFZA1_BUILD_COMMIT {json.dumps(commit)}\n")
    # Restore the pinned stack options on incremental builds as well.
    # TCP flow control includes software buffering; it is not an XRAM ring limit.
    opts = dest / "lib/lwip/u-boot/lwipopts.h"
    shutil.copy2(ROOT / "sources" / lock["reference"]["directory"] / "lib/lwip/u-boot/lwipopts.h", opts)
    # A peer RST bypasses the normal close callback. Release partial POST state.
    http_core = dest / "lib/lwip/lwip/src/apps/http/httpd.c"
    shutil.copy2(ROOT / "sources" / lock["reference"]["directory"] / "lib/lwip/lwip/src/apps/http/httpd.c", http_core)
    replace(http_core, '  LWIP_DEBUGF(HTTPD_DEBUG, ("http_err: %s\\n", lwip_strerr(err)));',
            '  LWIP_DEBUGF(HTTPD_DEBUG, ("http_err: %s\\n", lwip_strerr(err)));\n'
            '#if LWIP_HTTPD_SUPPORT_POST\n'
            '  if (hs != NULL && hs->post_content_len_left != 0) {\n'
            '    http_uri_buf[0] = 0;\n'
            '    httpd_post_finished(hs, http_uri_buf, LWIP_HTTPD_URI_BUF_LEN);\n'
            '  }\n'
            '#endif')
    # Preserve the complete frontend while reducing the two-FIP flash footprint.
    http = dest / "net/lwip/httpd.c"
    shutil.copy2(reference_path := ROOT / "sources" / lock["reference"]["directory"] / "net/lwip/httpd.c", http)
    page = dest / "net/lwip/httpd-page.html"
    page_source = ROOT / "overlay/net/lwip/httpd-page.html"
    raw = page_source.read_bytes() if page_source.exists() else reference_path.with_name("httpd-page.html").read_bytes()
    compressed = gzip.compress(raw, mtime=0)
    page.write_bytes(b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Encoding: gzip\r\nConnection: close\r\nContent-Length: " + str(len(compressed)).encode() + b"\r\n\r\n" + compressed)
    replace(http, "fs_set_data(file, httpd_page, httpd_page_size);", "fs_set_data(file, httpd_page, httpd_page_size);\n\t\tfile->flags = FS_FILE_FLAGS_HEADER_INCLUDED;")
    replace(http, '#include <net/httpd.h>', '#include <net/httpd.h>\n#include <tyfza1_recovery.h>\n#include <tyfza1_build.h>')
    # Match physical main-area backups: bad-block gaps occupy bytes in RAM, too.
    replace(http, "/* NAND offsets advance across factory bad blocks while RAM stays packed. */",
            "/* Preserve physical offsets and FF gaps, matching downloaded MTD backups. */")
    replace(http, '''\t\t\t\tphysical = round_down(physical, mtd->erasesize) +
\t\t\t\t\tmtd->erasesize;
\t\t\t\tcontinue;''', '''\t\t\t\tsize_t skip = min_t(size_t, remaining,
\t\t\t\t\t\t\t mtd->erasesize - physical % mtd->erasesize);
\t\t\t\tif (read) memset(data, 0xff, skip);
\t\t\t\tphysical += skip;
\t\t\t\tdata += skip;
\t\t\t\tremaining -= skip;
\t\t\t\tservice_network();
\t\t\t\tcontinue;''')
    replace(http, "static int run_storage_job(void)\n{", '''/* Called only after range and eraseblock-alignment checks, before any erase. */
static int storage_mtd_check_write(struct mtd_info *mtd, u64 offset,
\t\t\t\t   const u8 *data, size_t size)
{
\tsize_t pos, i;
\tint ret;
\tif (!mtd_uses_pages(mtd)) return 0;
\tfor (pos = 0; pos < size; pos += mtd->erasesize) {
\t\tret = mtd_block_isbad(mtd, offset + pos);
\t\tif (ret < 0) return ret;
\t\tif (ret > 0)
\t\t\tfor (i = 0; i < mtd->erasesize; i++)
\t\t\t\tif (data[pos + i] != 0xff) {
\t\t\t\t\tputs("Image contains data at a bad physical block; write refused.\\n");
\t\t\t\t\treturn -EINVAL;
\t\t\t\t}
\t\tservice_network();
\t}
\treturn 0;
}

static int run_storage_job(void)
{''')
    replace(http, '''\tif (!upload_region_valid(load_addr, request.size)) {
\t\tret = CMD_RET_FAILURE;
\t\tgoto out_put_mtd;
\t}''', '''\t/* Boot updates and whole-chip restores have separate validated write paths. */
\tif (!mtd_is_partition(mtd) || !strcmp(mtd->name, "boot")) {
\t\tputs("Use U-Boot update or full Flash restore for this target.\\n");
\t\tret = -EPERM;
\t\tgoto out_put_mtd;
\t}
\tif (!upload_region_valid(load_addr, request.size)) {
\t\tret = CMD_RET_FAILURE;
\t\tgoto out_put_mtd;
\t}''')
    replace(http, '''\tphase = "erase";
\tret = storage_mtd_erase(mtd, request.offset, request.size);''', '''\tret = storage_mtd_check_write(mtd, request.offset, buffer, request.size);
\tif (ret) goto out_unmap;
\tphase = "erase";
\tret = storage_mtd_erase(mtd, request.offset, request.size);''')
    replace(http, '"httpd_ipaddr", "httpd_netmask",', '"httpd_ipaddr", "httpd_netmask", "httpd_dhcp", "tyf_bootconf",')
    replace(http, '\tif (httpd_running)\n\t\treturn 0;', '\tif (httpd_running)\n\t\treturn 0;\n\tif (env_get_yesno("httpd_dhcp") == 0) with_dhcp = false;')
    replace(http, '\t\tret = env_set(env_key, env_value[0] ? env_value : NULL);', '''\t\tif (!strcmp(env_key, "tyf_bootconf")) {
\t\t\tret = tyfza1_save_boot_config(env_value);
\t\t\tbreak;
\t\t}
\t\t/* Accept the familiar IP names as persistent recovery settings, too. */
\t\tif (!strcmp(env_key, "ipaddr"))
\t\t\tret = env_set("httpd_ipaddr", env_value[0] ? env_value : NULL);
\t\telse if (!strcmp(env_key, "netmask"))
\t\t\tret = env_set("httpd_netmask", env_value[0] ? env_value : NULL);
\t\telse
\t\t\tret = 0;
\t\tif (!ret) ret = env_set(env_key, env_value[0] ? env_value : NULL);''')
    replace(http, '\t\tif (!ret) ret = env_save();\n\t\tbreak;', '''\t\tif (!ret) ret = env_save();
\t\tif (!ret && !strcmp(env_key, "httpd_dhcp") && env_get_yesno("httpd_dhcp") == 0)
\t\t\tuboot_httpd_dhcp_stop();
\t\tbreak;''')
    replace(http, "\tHTTP_JOB_NAND_SCRUB,", "\tHTTP_JOB_NAND_SCRUB,\n\tHTTP_JOB_TYF_RESTORE,")
    replace(http, 'static const char *phase = "idle";', 'static const char *phase = "idle";\n#if defined(CONFIG_TARGET_TYFZA1)\n#include <net/tyfza1-httpd.inc>\n#endif')
    replace(http, '\tjson_string(&j, output_buf);', '\tjson_string(&j, output_buf);\n#if defined(CONFIG_TARGET_TYFZA1)\n\ttyf_http_restore_info(&j);\n#endif')
    replace(http, '\tif (flash_all_upload_ready && strcmp(op, "flash-all"))', '''#if defined(CONFIG_TARGET_TYFZA1)
\t{
\t\tint native = tyf_http_parse_restore(&r, op, id);
\t\tif (native != 1) return native;
\t}
#endif
\tif (flash_all_upload_ready && strcmp(op, "flash-all"))''')
    replace(http, '\tcase HTTP_JOB_NAND_SCRUB:', '''#if defined(CONFIG_TARGET_TYFZA1)
\tcase HTTP_JOB_TYF_RESTORE:
\t\tret = tyfza1_restore_job(tyf_restore_operation, buffer_addr, buffer_size,
\t\t\t\t\t tyf_restore_total, tyf_restore_offset, tyf_restore_id, service_network);
\t\tbreak;
#endif
\tcase HTTP_JOB_NAND_SCRUB:''')
    replace(http, '\tif (content_len <= 0)\n\t\tgoto reject;', '''\tif (content_len <= 0)
\t\tgoto reject;
#if defined(CONFIG_TARGET_TYFZA1)
\tif (!strcmp(uri, "/api/upload-all-flash") ||
\t    (tyfza1_restore_status()->active && !strcmp(uri, "/api/upload") && content_len > 0x400000))
\t\tgoto reject;
#endif''')
    replace(http, '\treturn len && end >= addr && addr >= gd->ram_base && end <= safe_end;', '''#if defined(CONFIG_TARGET_TYFZA1)
\tif (!tyf_http_upload_safe(addr, len)) return false;
#endif
\treturn len && end >= addr && addr >= gd->ram_base && end <= safe_end;''')
    replace(http, '\thttp_netif = NULL;', '''#if defined(CONFIG_TARGET_TYFZA1)
\tif (tyfza1_restore_status()->active)
\t\ttyfza1_restore_job("restore-cancel", 0, 0, 0, 0, tyfza1_restore_status()->id, service_network);
#endif
\thttp_netif = NULL;''')
    replace(http, '\t\tjson_printf(&j, "{\\"model\\":"); json_string(&j, board);', '''\t\tjson_printf(&j, "{\\"model\\":"); json_string(&j, board);
#if defined(CONFIG_TARGET_TYFZA1)
\t\t{
\t\t\tint full, speed = tyfza1_link_speed(&full);
\t\t\tjson_printf(&j, ",\\"project_version\\":"); json_string(&j, TYFZA1_PROJECT_VERSION);
\t\t\tjson_printf(&j, ",\\"build_commit\\":"); json_string(&j, TYFZA1_BUILD_COMMIT);
\t\t\tjson_printf(&j, ",\\"link_speed_mbps\\":%d,\\"link_full_duplex\\":%s", speed, full ? "true" : "false");
\t\t\tjson_printf(&j, ",\\"boot_config\\":"); json_string(&j, tyfza1_boot_config() ?: "");
\t\t}
#endif''')
    replace(http, '\tif (!strcmp(name, "/api/device"))\n\t\treturn fs_json(file, 200, info_buf, false);', '\tif (!strcmp(name, "/api/device")) {\n\t\tbuild_info();\n\t\treturn fs_json(file, 200, info_buf, false);\n\t}')
    # Recovery lamps follow the HTTP loop and job results.
    replace(http, "static void service_network(void)\n{", "static void service_network(void)\n{\n#if defined(CONFIG_TARGET_TYFZA1)\n\ttyfza1_recovery_leds_poll();\n#endif")
    replace(http, "\tjob_result = run_captured_job();", "#if defined(CONFIG_TARGET_TYFZA1)\n\tjob_result = tyf_http_run_job();\n#else\n\tjob_result = run_captured_job();\n#endif")
    replace(http, "\tled_activity_blink();\n\tstop_requested = false;", "\tled_activity_blink();\n#if defined(CONFIG_TARGET_TYFZA1)\n\ttyfza1_recovery_leds(TYFZA1_LEDS_IDLE);\n#endif\n\tstop_requested = false;")
    replace(http, "\t\tprocess_job();\n\t}", "\t\tprocess_job();\n#if defined(CONFIG_TARGET_TYFZA1)\n\t\ttyf_http_leds_poll();\n#endif\n\t}")
    replace(http, "\tled_activity_on();\n\tclear_ctrlc();\n\treturn ret", "#if defined(CONFIG_TARGET_TYFZA1)\n\ttyfza1_recovery_leds(TYFZA1_LEDS_OFF);\n#endif\n\tled_activity_on();\n\tclear_ctrlc();\n\treturn ret")
    replace(http, '#define HTTPD_UBI_PART\t\t"ubi"', '#define HTTPD_UBI_PART\t\t"ubi_device"')
    replace(http, '"airoha,an758x-recovery-layout"', '"tianyi,tyfza1-recovery-layout"')
    replace(http, "\thttp_netif = netif;\n\tbuild_info();",
            "\thttp_netif = netif;\n\t/* Populate UBI backups as soon as recovery opens. */\n\tif (ubi_part(HTTPD_UBI_PART, NULL))\n\t\tputs(\"UBI unavailable; raw NAND maintenance remains available.\\n\");\n\tbuild_info();")
    replace(http, "static int run_bootloader_update(bool bl2)\n{", "static int run_bootloader_update(bool bl2)\n{\n\tif (IS_ENABLED(CONFIG_TARGET_TYFZA1))\n\t\treturn tyfza1_install_loader(buffer_addr, buffer_size, bl2, service_network);")
    replace(http, "static int run_firmware_update(void)\n{", "static int run_firmware_update(void)\n{\n\tif (IS_ENABLED(CONFIG_TARGET_TYFZA1))\n\t\treturn tyfza1_install_system(buffer_addr, buffer_size, service_network);")
    replace(http, "static int run_ubi_rebuild(void)\n{", "static int run_ubi_rebuild(void)\n{\n\tif (IS_ENABLED(CONFIG_TARGET_TYFZA1))\n\t\treturn tyfza1_rebuild_ubi(service_network);")
    replace(http, '\t\treturn run_commandf("bootm 0x%lx", load_addr);', '\t\treturn tyfza1_boot_upload(load_addr, buffer_size);')
    if fresh:
        arm = dest / "arch/arm/Kconfig"
        replace(arm, "config TARGET_PRESIDIO_ASIC", "config TARGET_TYFZA1\n\tbool \"Tianyi TYFZA1 (RTL9617CVW)\"\n\tselect ARM64\n\tselect DM\n\tselect OF_CONTROL\n\tselect BOARD_LATE_INIT\n\nconfig TARGET_PRESIDIO_ASIC")
        with arm.open("a") as out:
            out.write('\nsource "board/realtek/tyfza1/Kconfig"\n')
        replace(dest / "drivers/serial/Kconfig", "depends on DM_SERIAL && TARGET_PRESIDIO_ASIC", "depends on DM_SERIAL && (TARGET_PRESIDIO_ASIC || TARGET_TYFZA1)")
    (dest / ".tyfza1-sources.json").write_text(json.dumps(lock, indent=2) + "\n")
    print(dest)


if __name__ == "__main__":
    main()
