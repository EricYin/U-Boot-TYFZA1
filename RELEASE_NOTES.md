## 1.6

- 改用实际网口 PHY 芯片识别全千兆版和带 2.5G 口版，恢复网页、网口初始化和系统启动配置统一使用硬件检测结果。
- 等待 PHY 稳定响应后再确定机型，并核验复位、使能和 MDIO 配置，避免过早采样造成误判。

下载：`tyfza1-uboot-install.run` 用于安装；`tyfza1-uboot-universal.bin` 用于恢复网页更新 U-Boot。用法见 [安装指南](https://github.com/LeoooChen/U-Boot-TYFZA1#安装)。
