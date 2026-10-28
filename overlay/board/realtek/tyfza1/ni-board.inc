/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Included by the imported DM NI driver, after its PHY/map helpers. */
#include <tyfza1_recovery.h>

static struct cortina_ni_priv *recovery_ni;

static int tyf_ni_phy_status(struct phy_device *phy)
{
	int value;
	if (!phy) return -ENODEV;
	phy->link = 0;
	value = phy_read(phy, MDIO_DEVAD_NONE, MII_BMSR);
	if (value < 0) return value;
	value = phy_read(phy, MDIO_DEVAD_NONE, MII_BMSR);
	if (value < 0) return value;
	if (!(value & BMSR_LSTATUS) || !(value & BMSR_ANEGCOMPLETE)) return 0;
	value = genphy_parse_link(phy);
	if (!value) phy->link = 1;
	return value;
}

static int tyf_ni_board_prepare(struct cortina_ni_priv *priv)
{
	int i;
	/* NI3 has no jack on the 2.5G PCB; its internal PHY is still present. */
	for (i = 0; i < PORT_MAX; i++) priv->maps[i].phy_id = i < 4 ? i + 1 : -1;
	recovery_ni = priv;
	return 0;
}

int tyfza1_link_speed(int *full_duplex)
{
	struct phy_device *phy = recovery_ni ? recovery_ni->phydev : NULL;
	*full_duplex = phy && phy->duplex == DUPLEX_FULL;
	return phy && phy->link ? phy->speed : 0;
}

static int tyf_ni_refresh_link(struct cortina_ni_priv *priv)
{
	struct phy_device *phy;
	int old_port = priv->active_port, speed = -1, duplex = -1, ret;
	if (!priv->is_phyinited || get_timer(priv->link_polled) < 250) return 0;
	priv->link_polled = get_timer(0);
	phy = __get_curr_phydev(priv);
	if (phy) { speed = phy->speed; duplex = phy->duplex; }
	ret = tyf_ni_phy_status(phy);
	if (ret || !phy || !phy->link) {
		if (phy) phy->link = 0;
		ni_auto_scan_active_port(priv);
		phy = __get_curr_phydev(priv);
	}
	if (phy && phy->link && priv->phydev == phy && old_port == priv->active_port &&
	    speed == phy->speed && duplex == phy->duplex) return 0;
	if (old_port >= 0 && is_valid_port(priv, old_port)) ni_enable_tx_rx(old_port, 0);
	priv->phydev = NULL;
	if (!phy || !phy->link) return 0;
	ret = priv->aal_mode_sync(priv->active_port, priv->maps[priv->active_port].sds_mode, phy);
	if (ret) return ret;
	priv->aal_set_active_port(priv->active_port);
	priv->phydev = phy;
	ni_enable_tx_rx(priv->active_port, 1);
	printf("Recovery link: port %d, %d Mbps\n", priv->active_port, phy->speed);
	return 0;
}
