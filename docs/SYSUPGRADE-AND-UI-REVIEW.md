# 通用 sysupgrade 与恢复页面核验

基线 b009d9f。验证用户本地 `0.8.3-beta/sysupgrade.bin`，SHA256 为 `cff927ff30891a84c9a13b1328ce677f6b16e5e5fa2d58b179274010a1515b3b`，共 12063034 字节。它与虚拟机 `PonWRT-TYFZA1/artifacts/local-0.8.3-beta-devmem-20261026/firmware/sysupgrade.bin` 完全相同。没有修改 OpenWrt 项目，也没有刷写或重启设备。

## 两种硬件的安装约定

同包共用 kernel/rootfs。全千兆选择 conf-1，2.5G 版选择 conf-0。恢复网络始终使用片内千兆口，不根据选择改变端口。页面现在明确显示“未保存/已更改/已保存”，未保存的选择禁止系统上传和启动；U-Boot 更新、备份、恢复维护不依赖 Linux 配置。

后端先验证 fwtool INFO 尾部格式及覆盖整包的 CRC32，再解析 sysupgrade tar、检查 FIT 镜像数据哈希、ARM64 kernel 和启动 script，解压设备树并验证它与所选 configuration 的硬件标记一致。交换两份设备树或缺失启动所需镜像时拒绝。CRC 防意外损坏，不等于软件来源签名认证；没有宣称它能验证固件发布者。

安装保持现有槽位约定：无已装 OpenWrt 时使用当前 OEM 槽的另一槽；已有 OpenWrt 时复用其槽。写入对应 ubi_r0/ubi_k0 或 ubi_r1/ubi_k1，逐段读回比较，重建 rootfs_data 后才设置并保存启动变量。逐项 env_set 的失败会传递并恢复原有启动变量，不再无视设置失败继续 env_save。

写前确认 kernel/root 的固定卷 ID 与名称、只读状态、空间和坏块预留。已迁移到 tyfza1_factory/backup 的设备拒绝缺少 factory-v1 标记的旧格式固件，与 OpenWrt 的 platform_check_image 一致。校准卷、另一系统槽不参与容量回收或写入。

恢复刷写会重置 rootfs_data，且重刷已有槽不是掉电无损 A/B 升级。中途断电或写入失败后可能需要再次用 U-Boot 恢复；本次没有做任何实机掉电测试。

## 验证证据

`scripts/test_sandbox_crypto.py` 接受可选环境变量 `TYFZA1_SYSUPGRADE` 指向真实 sysupgrade 文件。合成包始终验证；本次同时使用上面的原包，执行 98 个 RAM UBI 安装场景，其中真实包占 49 个。

使用生产 tar/CRC/JSON/FIT/libfdt/LZMA 解析、安装逻辑、分段读回以及 U-Boot 环境变量；仅 UBI I/O 和 env 持久化替代为可注入故障的模型。覆盖两配置、两初始槽、首次安装、已安装和缺标记旧安装、校准迁移、读写/resize/data 重建/env_set/env_save 错误、只读、空间不足、卷 ID 不符、root 内容损坏、截断、缺元数据、缺 script、错误 kernel 类型。成功时内核/rootfs 与输入字节逐一相同；非目标卷不变；失败时启动变量未被错误提交。

另执行原包内 script 的四种 conf/slot 组合，只将最后 bootm 替换为参数记录。确认设备树选择、ubi_r0/1、/dev/ubiblock0_4/7、tyfza1.slot 及 bootargs 一致；没有执行 Linux。

## 页面调整

信息区将设备名称、千兆恢复模式、协商速率分行显示，顶部不再称为自动“机型”；Linux 配置单独放置。配置框、文件框、按钮高度和间距统一，桌面用固定按钮列，手机纵排、满宽按钮。390px 手机和桌面预览都无横向溢出。

同时保留此前未提交的独立前端修复：首次完整数据加载失败会自动重试且不开放写入；本地错误不会被后台 idle 状态擦掉；切换语言立即更新链路文字。已在本地只读预览和 DOM/API 测试中验证。预览服务器禁止 POST，所有交互测试不会访问设备。

详细日志、输入摘要、各场景结果与截图保存在本地发布记录。离线结果不构成实机冷启动、PON/Wi-Fi 工作或闪存掉电恢复验收，也不承诺绝无 bug。
