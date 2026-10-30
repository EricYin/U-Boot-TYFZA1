<h1 align="center">TYFZA1 U-Boot</h1>

<p align="center">
  本项目的恢复功能与网页前端参考
  <a href="https://github.com/pbs05/uboot-an758x">pbs05/uboot-an758x</a>，<br>
  并针对天翼 TYFZA1 完成平台适配。感谢原项目提供的恢复功能、前端设计和开源实现。
</p>

<p align="center">
  <a href="https://github.com/LeoooChen/U-Boot-TYFZA1/releases/latest"><img src="https://img.shields.io/github/v/release/LeoooChen/U-Boot-TYFZA1?label=release&amp;color=0f766e" alt="Release"></a>
  <a href="https://github.com/LeoooChen/U-Boot-TYFZA1/actions/workflows/build.yml"><img src="https://github.com/LeoooChen/U-Boot-TYFZA1/actions/workflows/build.yml/badge.svg" alt="Build"></a>
  <a href="COPYING"><img src="https://img.shields.io/badge/license-GPL--2.0-blue" alt="GPL-2.0"></a>
</p>

<p align="center">
  <a href="#下载">下载</a> ·
  <a href="#安装">安装</a> ·
  <a href="docs/TTL-RECOVERY.md">TTL 串口恢复</a> ·
  <a href="#恢复网页">恢复网页</a> ·
  <a href="#构建">构建</a> ·
  <a href="https://github.com/LeoooChen/U-Boot-TYFZA1/issues">问题反馈</a>
</p>

> **U-Boot 1.6 使用提示：** 恢复模式不启用 2.5G 口，请连接普通千兆口。刷写或启动 OpenWrt 前，请在恢复网页选择并保存对应机型的启动配置。

## 功能

基于 **U-Boot 2026.07**，为 TYFZA1 全千兆版与 RTL8221B 2.5G 口版提供启动和恢复环境。

- **通用安装包**：核对并保留本机的早期引导代码。
- **网页恢复**：中英文界面，支持 OpenWrt 安装、U-Boot 更新、备份下载和内存启动。
- **原生系统引导**：启动配置由用户选择一次并保存，支持标准 sysupgrade 镜像。
- **双份引导更新**：依次写入 FIP1、FIP0，每块写入后读回校验。
- **维护工具**：环境变量、命令控制台、分区写入和分段整片恢复。

| 硬件 | U-Boot 可用网口 | 首次选择的 OpenWrt 配置 |
| :--- | :--- | :--- |
| 全千兆版 | 四个普通千兆口 | 全千兆版（`conf-1`） |
| 2.5G 口版 | 三个普通千兆口 | 2.5G 版（`conf-0`） |

通用包包含两种机型的 loader，共用同一份 U-Boot BL33。安装时核对本机 GPT 分区布局、BL2、BL31 和保留区域，再选择匹配镜像；GPT 中每台设备独有的 GUID 和 CRC 不参与逐字节比对，但仍校验 CRC。原厂版本造成的 FIP 分区长度差异允许兼容，前提是起点固定、终点位于对应的 `0xc0000` 槽内、主备 GPT 长度一致，且能容纳待写入的完整 FIP。GPT 保留本机原值。

两种硬件运行同一份千兆恢复代码，不自动判断机型，不加载外置 2.5G PHY 或 SerDes 驱动。第一次进入恢复网页时，按设备实际网口选择并保存 **OpenWrt 启动配置**，之后保留该选择。旧版本自动生成的环境变量不会替代这次选择。未配置时自动进入恢复网页，备份和更新 U-Boot 仍可使用。详见 [千兆恢复与启动配置](docs/BOARD-IDENTIFICATION.md)。

## 下载

前往 **[Releases](https://github.com/LeoooChen/U-Boot-TYFZA1/releases/latest)** 下载 **`tyfza1-uboot-install.run`**。全千兆版和 2.5G 口版使用同一个文件。

| 文件 | 用途 |
| :--- | :--- |
| `tyfza1-uboot-install.run` | 从原厂系统或 OpenWrt 安装 U-Boot |
| `tyfza1-uboot-universal.bin` | 在 U-Boot 恢复网页中更新引导器 |

## 安装

### 原厂系统（Telnet）

#### 1. 登录光猫

电脑通过网线连接光猫 LAN 口，打开 [Telnet 开启页面](http://192.168.1.1:8080/CCOM/OpenTelnet.asp)，然后在电脑终端执行：

```sh
telnet 192.168.1.1
```

默认用户名、密码均为 `telnetadmin`。登录后执行 `su`，再次输入 `telnetadmin`，取得 root 权限。已修改地址或密码时，使用实际配置。

#### 2. 传入文件

将 `tyfza1-uboot-install.run` 传入光猫的 `/tmp`，选择以下任一方式。

**电脑传输（Python）**

在电脑上进入文件所在目录，运行：

```sh
python3 -m http.server 8000
```

在光猫 Telnet 中执行，将 `192.168.1.2` 换成电脑的 LAN 地址：

```sh
wget -O /tmp/tyfza1-uboot-install.run \
  http://192.168.1.2:8000/tyfza1-uboot-install.run
```

**U 盘传输**

将文件放到 U 盘根目录，插入光猫后，在 Telnet 中执行：

```sh
cp /mnt/usb*/tyfza1-uboot-install.run /tmp/
```

#### 3. 安装并重启

```sh
sh /tmp/tyfza1-uboot-install.run
```

安装器自动解包、校验文件、匹配本机引导内容，并完成双份 FIP 的刷写和读回校验。看到 `U-Boot installed.` 即安装成功。

boot 备份保存在 `/tmp/tyfza1-boot-backup-*.bin`，重启前可复制到电脑或 U 盘。随后执行：

```sh
reboot
```

### OpenWrt（SSH）

使用支持 boot 分区写入的 OpenWrt。通过 SSH 登录：

```sh
ssh root@192.168.1.1
```

将同一个 `tyfza1-uboot-install.run` 传入 `/tmp`，执行：

```sh
sh /tmp/tyfza1-uboot-install.run
```

看到 `U-Boot installed.` 后保存 boot 备份，再执行 `reboot`。

### TTL 串口恢复旧版 U-Boot

旧版仍能进入 `TYFZA1#`，但因 `Recovery PHY missing` 等错误打不开网页时，可按 [TTL 串口恢复教程](docs/TTL-RECOVERY.md)，通过 Kermit 传入恢复文件、检查本机引导信息，再更新双份 FIP。教程给出完整命令、成功标志和异常处理。

## 恢复网页

### 进入恢复模式

1. 断开光猫电源，用网线连接电脑与普通千兆 LAN 口；2.5G 版请勿使用蓝色 2.5G 口。
2. 电脑网卡设为自动获取地址。
3. **按住 Reset，再接通电源**；PON、LOS 灯同时亮起后即可松开。
4. 打开 **[http://192.168.0.1](http://192.168.0.1/)**。

恢复服务提供 DHCP。手动设置电脑地址时，使用 `192.168.0.2/24`。

使用串口时，参数为 **115200 / 8N1**。开机菜单出现后，按方向键选中 **Web recovery**，再按回车。也可按 Esc 返回 `TYFZA1#`，执行：

```text
httpd dhcp
```

Reset 在网络初始化前锁存，松开按键后仍会进入恢复。正常开机由 **Start OpenWrt** 启动系统。

单个网口的 PHY 初始化失败时，仅停用该口，其余正常网口仍可进入恢复网页。恢复网页仅使用片内千兆 PHY；不要将电脑接到 2.5G 口。页面显示当前实际协商的 10/100/1000 Mbps 和双工状态。

恢复 IP 固定为 `192.168.0.1`，DHCP 服务仅负责给电脑分配地址。电脑也可使用 `192.168.0.2/24`。在环境变量页将 `httpd_dhcp` 保存为 `0` 可立即、持久关闭 DHCP 服务；`1` 在下次进入恢复时启用。恢复地址使用 `httpd_ipaddr` 和 `httpd_netmask`，下次启动恢复服务生效；网页保存 `ipaddr` / `netmask` 也会同步到恢复设置。串口静态恢复示例：

```text
setenv httpd_ipaddr 192.168.0.1
setenv httpd_netmask 255.255.255.0
setenv httpd_dhcp 0
saveenv
tyfrecovery
```

恢复页面显示两段式版本号（如 `1.1`），提交号单独显示。构建时存在未提交修改或未跟踪文件会在提交号后标记 `-dirty`；源码归档没有 Git 信息时不显示提交号。

### 指示灯

U-Boot 通过两种设备共有的 PON、LOS 灯指示当前状态（进入 Linux 后恢复系统灯光含义）：

| 状态 | 灯光 | 说明 |
|---|---|---|
| 正常开机 | PON→LOS 依次各亮 150ms | U-Boot 已启动 |
| Reset 已识别 | 两灯常亮 | 可以松开 Reset |
| 等待操作 | 两灯每 2 秒连闪两下 | 恢复网页已就绪 |
| 上传文件 | PON 快速闪烁 | 文件仅存入内存，断电不影响设备 |
| 写入闪存 | 前半程 PON 闪烁，后半程 PON 常亮、LOS 闪烁 | 切勿断电；闪烁停住说明写入卡住 |
| 写入成功 | 两灯常亮 2 秒 | 随后回到等待 |
| 写入失败 | PON 与 LOS 交替快闪 | 持续到下一次上传或写入，可直接重试 |

整片恢复的上传与写入交替进行，全程显示写入进度，期间不要断电。退出恢复或启动系统时，灯的 GPIO 控制权恢复原状态。

### 安装 OpenWrt

先在页面选择并保存与硬件对应的 **OpenWrt 启动配置**：全千兆版选择“全千兆版”，2.5G 版选择“2.5G 版”。页面显示已保存后再刷写；更改选项必须重新保存。

1. 下载 [PonWRT-TYFZA1](https://github.com/LeoooChen/PonWRT-TYFZA1/releases/latest) 的 `sysupgrade.bin`。
2. 打开“刷机 → 刷写系统”，选择文件，点击“上传并刷写”。
3. 等待任务完成，点击“启动系统”。
4. 电脑重新获取地址后，打开 **[http://192.168.1.1](http://192.168.1.1/)**。

首次安装先识别已有 PonWRT FIT；旧安装即使没有槽位标记，也会复用识别到的 OpenWrt 槽。两槽均无 PonWRT 时才选择原厂当前槽以外的系统槽，并记录为 OpenWrt 槽；后续恢复安装使用同一个槽。安装器先验证 OpenWrt fwtool 整包 CRC、元数据和所选 FIT 设备树，再校验并读回 kernel/rootfs，按实际镜像大小分配 rootfs，将余下空间分配给 rootfs_data。

可写空间大小和原厂系统的保留情况取决于固件的存储布局，请参照所安装固件的说明。

请使用完整的发布版 `sysupgrade.bin`，不要去掉文件尾部的 OpenWrt 元数据。已迁移校准存储的设备仅接受 `factory-v1` 固件。恢复安装会初始化 OpenWrt 配置，重刷已有系统槽不提供断电无损保证。日常保留配置升级可使用 LuCI“系统 → 备份与更新”，或执行：

```sh
sysupgrade /tmp/sysupgrade.bin
```

### 备份与维护

| 功能 | 使用方式 |
| :--- | :--- |
| 更新 U-Boot | 在“刷写 U-Boot”上传通用包，等待双份 FIP 写入并读回完成 |
| 下载备份 | 在“备份”选择 MTD、UBI 卷或整片 NAND，点击“下载备份” |
| 内存启动 | 在“高级 → 内存启动”上传适用于 TYFZA1 的 FIT 镜像 |
| 环境变量 | 在“高级 → 环境变量”读取、修改并保存参数 |
| 命令控制台 | 在“高级 → 命令控制台”执行 U-Boot 命令并查看输出 |
| 分区写入 | 选择 MTD / UBI 目标，上传对应分区镜像；boot 使用“更新 U-Boot” |
| 恢复整片 Flash | 上传本机完整主数据备份，按 4 MiB 分段恢复，最后更新引导区 |
| 重建 UBI | 仅重建系统卷，保留本机出厂配置、FPGA 和 DTB 卷 |
| 清除坏块标记 | 维修功能：擦除整片 NAND，包含出厂坏块标记 |

MTD 备份和分区写入均使用物理偏移，坏块区域填充 `FF`，不包含 OOB。写入前检查整个目标范围；镜像在坏块位置含有非 `FF` 数据时，拒绝擦除和写入。整片恢复的备份大小须与 Flash 容量相同，身份、认证和校准数据使用本机备份。

boot 分区为 2 MiB，U-Boot 更新只写入 `0x40000`、`0x100000` 起始的两份 FIP，每份 `0xc0000`。GPT、保留区域、env/env2 和原厂配置卷保持原有内容。

## 构建

源码版本锁定在 [source-lock.json](source-lock.json)。以下命令适用于 Ubuntu 24.04 ARM64。

### 1. 安装依赖

```sh
sudo apt-get install \
  build-essential gcc-aarch64-linux-gnu binutils-aarch64-linux-gnu \
  device-tree-compiler flex bison libssl-dev python3-cryptography \
  python3-dev python3-pyelftools python3-setuptools swig \
  libgnutls28-dev uuid-dev zlib1g-dev qemu-system-arm
```

### 2. 编译与打包

两版原厂 boot 基线保存在 [evidence/stock-boot](evidence/stock-boot)，SHA-256 见 [stock-inputs.json](evidence/stock-inputs.json)。自动构建使用仓库内的基线，并按固定 SHA-256 校验。

```sh
mkdir -p inputs
cp evidence/stock-boot/*-boot.bin inputs/
sh scripts/build.sh
sh scripts/package_release.sh
```

产物位于 `output/release/`。

### 3. 运行测试

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/test_sandbox_crypto.py
```

提交到 `main` 自动构建并保存产物；推送与 `VERSION` 对应的版本标签（如 `v1.1`）后，自动发布 GitHub Release，仅附带 `.run` 安装包和通用 `.bin` 升级包。

## 验证记录

两种原厂 boot 均通过引导兼容与签名校验，四个内部端口的 10/100/1000 Mbps、双工和 MAC 设置已与固定版本 Realtek 源码逐项比较。上传速度修复已通过 RAM 启动的原始镜像实机验证；最终可刷写包尚未验证冷启动，详细结果与限制见[网页上传速度复核](docs/UPLOAD-PERFORMANCE.md)。

历史版本的实机记录保存在 [原始记录](evidence/hardware-validation-20261018.json)，不代表本次修订已经完成实机验收。网页上传的 TCP 窗口复核、限速回归和性能验证边界见 [上传说明](docs/UPLOAD-PERFORMANCE.md)。

启动、网口重试和 TCP 中断清理的后续修复见 [审查记录](docs/BOOT-NET-TRANSFER-REVIEW.md)。

冷启动错误传递、实际 PHY 协商解析和下载中断处理见 [后续复核](docs/COLD-NEGOTIATION-DOWNLOAD-REVIEW.md)。

上传内存边界、重复恢复启动与网页状态的稳定性修复见 [稳定性复核](docs/STABILITY-REVIEW.md)。

实际 0.8.3-beta 通用包的双配置安装与前端布局验证见 [sysupgrade 与页面核验](docs/SYSUPGRADE-AND-UI-REVIEW.md)。

## 来源与许可

- [pbs05/uboot-an758x](https://github.com/pbs05/uboot-an758x)：恢复功能与网页前端参考。
- [jameywine/GPL-for-GP3000](https://github.com/jameywine/GPL-for-GP3000)：Realtek GPL 平台代码。

新增代码采用 **GPL-2.0-only**，第三方文件保留原有许可。详见 [COPYING](COPYING)。
