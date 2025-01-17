from liteeth.common import *


def LiteEthPHY(clock_pads, pads, clk_freq=None, **kwargs):
    # Autodetect PHY
    if hasattr(clock_pads, "gtx") and len(pads.tx_data) == 8:
        if hasattr(clock_pads, "tx"):
            # This is a 10/100/1G PHY
            from liteeth.phy.gmii_mii import LiteEthPHYGMIIMII
            return LiteEthPHYGMIIMII(clock_pads, pads, clk_freq=clk_freq, **kwargs)
        else:
            # This is a pure 1G PHY
            from liteeth.phy.gmii import LiteEthPHYGMII
            return LiteEthPHYGMII(clock_pads, pads, **kwargs)
    elif hasattr(pads, "rx_ctl"):
        # This is a 10/100/1G RGMII PHY
        raise ValueError("RGMII PHYs are specific to vendors (for now), use direct instantiation")
    elif len(pads.tx_data) == 4:
        # This is a MII PHY
        from liteeth.phy.mii import LiteEthPHYMII
        return LiteEthPHYMII(clock_pads, pads, **kwargs)
    else:
        raise ValueError("Unable to autodetect PHY from platform file, use direct instantiation")

from liteeth.phy.mii  import LiteEthPHYMII
from liteeth.phy.rmii import LiteEthPHYRMII
from liteeth.phy.gmii import LiteEthPHYGMII
from liteeth.phy.gmii_mii import LiteEthPHYGMIIMII
from liteeth.phy.xgmii import LiteEthPHYXGMII

from liteeth.phy.s6rgmii import LiteEthPHYRGMII as LiteEthS6PHYRGMII
from liteeth.phy.s7rgmii   import LiteEthPHYRGMII as LiteEthS7PHYRGMII
from liteeth.phy.usrgmii   import LiteEthPHYRGMII as LiteEthUSPHYRGMII
from liteeth.phy.ecp5rgmii import LiteEthPHYRGMII as LiteEthECP5PHYRGMII

from liteeth.phy.a7_1000basex import A7_1000BASEX
try:
    from liteeth.phy.k7_1000basex import K7_1000BASEX
except:
    pass
from liteeth.phy.ku_1000basex import KU_1000BASEX
