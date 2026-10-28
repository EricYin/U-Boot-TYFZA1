/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Only the four on-chip PHYs are exposed, through their direct OCP window. */
static int ca_miiphy_read(struct mii_dev *bus, int addr, int devad, int reg)
{
	NI_MDIO_OPER_T op = { .wrd = 0 };
	if (addr < 1 || addr > 4 || devad != MDIO_DEVAD_NONE || reg < 0 || reg > 31)
		return -ENODEV;
	op.bf.reg_off = reg;
	op.bf.phy_addr = addr;
	op.bf.reg_base = CA_NI_MDIO_REG_BASE;
	return CORTINA_CA_REG_READ((ulong)op.wrd);
}

static int ca_miiphy_write(struct mii_dev *bus, int addr, int devad, int reg, u16 value)
{
	NI_MDIO_OPER_T op = { .wrd = 0 };
	if (addr < 1 || addr > 4 || devad != MDIO_DEVAD_NONE || reg < 0 || reg > 31)
		return -ENODEV;
	op.bf.reg_off = reg;
	op.bf.phy_addr = addr;
	op.bf.reg_base = CA_NI_MDIO_REG_BASE;
	CORTINA_CA_REG_WRITE(value, (ulong)op.wrd);
	return 0;
}
