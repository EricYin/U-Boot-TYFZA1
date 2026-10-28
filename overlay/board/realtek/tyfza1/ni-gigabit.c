// SPDX-License-Identifier: GPL-2.0+
/* Internal GE MAC setup derived from Realtek Taurus (Copyright 2022 Realtek). */
#include <config.h>
#include <phy.h>
#include <linux/errno.h>
#include <asm/arch/registers.h>
#include "vendor/eth_ni.h"

int aal_mode_sync(unsigned int port, aal_sds_mode_t mode, struct phy_device *phy)
{
	NI_HV_PT_PORT_STATIC_CFG_t cfg;
	NI_HV_PT_PORT_GLB_CFG_t glb;
	if (port > NI_PORT_3 || !phy ||
	    (phy->speed != SPEED_10 && phy->speed != SPEED_100 && phy->speed != SPEED_1000))
		return -EINVAL;
	cfg.wrd = CORTINA_CA_REG_READ(NI_HV_PT_PORT_STATIC_CFG + APB0_NI_HV_PT_STRIDE * port);
	cfg.bf.int_cfg = phy->speed == SPEED_1000 ? GE_MAC_INTF_GMII : GE_MAC_INTF_MII;
	CORTINA_CA_REG_WRITE(cfg.wrd, NI_HV_PT_PORT_STATIC_CFG + APB0_NI_HV_PT_STRIDE * port);
	glb.wrd = CORTINA_CA_REG_READ(NI_HV_PT_PORT_GLB_CFG + APB0_NI_HV_PT_STRIDE * port);
	glb.bf.speed = phy->speed == SPEED_10;
	glb.bf.duplex = phy->duplex == DUPLEX_HALF;
	CORTINA_CA_REG_WRITE(glb.wrd, NI_HV_PT_PORT_GLB_CFG + APB0_NI_HV_PT_STRIDE * port);
	return 0;
}

void aal_set_active_port(unsigned int port)
{
	NI_HV_GLB_INTF_RST_CONFIG_t  intf_rst_config;
	NI_HV_GLB_STATIC_CFG_t static_cfg;

	intf_rst_config.wrd = CORTINA_CA_REG_READ(NI_HV_GLB_INTF_RST_CONFIG);

	switch (port) {
	case NI_PORT_0:
		intf_rst_config.bf.intf_rst_p0 = 0;
		intf_rst_config.bf.mac_rx_rst_p0 = 0;
		intf_rst_config.bf.mac_tx_rst_p0 = 0;
		break;

	case NI_PORT_1:
		intf_rst_config.bf.intf_rst_p1 = 0;
		intf_rst_config.bf.mac_rx_rst_p1 = 0;
		intf_rst_config.bf.mac_tx_rst_p1 = 0;
		break;

	case NI_PORT_2:
		intf_rst_config.bf.intf_rst_p2 = 0;
		intf_rst_config.bf.mac_rx_rst_p2 = 0;
		intf_rst_config.bf.mac_tx_rst_p2 = 0;
		break;

	case NI_PORT_3:
		intf_rst_config.bf.intf_rst_p3 = 0;
		intf_rst_config.bf.mac_tx_rst_p3 = 0;
		intf_rst_config.bf.mac_rx_rst_p3 = 0;
		break;

	default:
		return;
	}

	CORTINA_CA_REG_WRITE(intf_rst_config.wrd, NI_HV_GLB_INTF_RST_CONFIG);

	/* Only one GMAC can connect to CPU */
	static_cfg.wrd = CORTINA_CA_REG_READ(NI_HV_GLB_STATIC_CFG);
	static_cfg.bf.port_to_cpu = port;
	static_cfg.bf.txmib_mode = 1;
	static_cfg.bf.rxmib_mode = 1;

	CORTINA_CA_REG_WRITE(static_cfg.wrd, NI_HV_GLB_STATIC_CFG);
}
