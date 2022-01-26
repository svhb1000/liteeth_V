#!/usr/bin/env python3

#
# This file is part of LiteEth.
#
# Copyright (c) 2015-2020 Florent Kermarrec <florent@enjoy-digital.fr>
# Copyright (c) 2020 Xiretza <xiretza@xiretza.xyz>
# Copyright (c) 2020 Stefan Schrijvers <ximin@ximinity.net>
# SPDX-License-Identifier: BSD-2-Clause

"""
LiteEth standalone core generator

LiteEth aims to be directly used as a python package when the SoC is created using LiteX. However,
for some use cases it could be interesting to generate a standalone verilog file of the core:
- integration of the core in a SoC using a more traditional flow.
- need to version/package the core.
- avoid Migen/LiteX dependencies.
- etc...

The standalone core is generated from a YAML configuration file that allows the user to generate
easily a custom configuration of the core.

TODO: identify limitations
"""

import argparse
import os
import yaml

from migen import *

from litex.build.generic_platform import *
from litex.build.xilinx.platform import XilinxPlatform
from litex.build.lattice.platform import LatticePlatform

from litex.soc.interconnect import wishbone
from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *
from litex.soc.integration.soc import SoCRegion

from liteeth.common import *

from liteeth import phy as liteeth_phys
from liteeth.mac import LiteEthMAC
from liteeth.core import LiteEthUDPIPCore

# IOs ----------------------------------------------------------------------------------------------

_io = [
    # Clk / Rst
    ("sys_clock", 0, Pins(1)),
    ("sys_reset", 1, Pins(1)),

    # IP/MAC Address.
    ("mac_address", 0, Pins(48)),
    ("ip_address",  0, Pins(32)),

    # Interrupt
    ("interrupt", 0, Pins(1)),

    # MII PHY Pads
    ("mii_eth_clocks", 0,
        Subsignal("tx", Pins(1)),
        Subsignal("rx", Pins(1)),
    ),
    ("mii_eth", 0,
        Subsignal("rst_n",   Pins(1)),
        Subsignal("mdio",    Pins(1)),
        Subsignal("mdc",     Pins(1)),
        Subsignal("rx_dv",   Pins(1)),
        Subsignal("rx_er",   Pins(1)),
        Subsignal("rx_data", Pins(4)),
        Subsignal("tx_en",   Pins(1)),
        Subsignal("tx_data", Pins(4)),
        Subsignal("col",     Pins(1)),
        Subsignal("crs",     Pins(1))
    ),

    # RMII PHY Pads
    ("rmii_eth_clocks", 0,
        Subsignal("ref_clk", Pins(1))
    ),
    ("rmii_eth", 0,
        Subsignal("rst_n",   Pins(1)),
        Subsignal("rx_data", Pins(2)),
        Subsignal("crs_dv",  Pins(1)),
        Subsignal("tx_en",   Pins(1)),
        Subsignal("tx_data", Pins(2)),
        Subsignal("mdc",     Pins(1)),
        Subsignal("mdio",    Pins(1)),
    ),

    # GMII PHY Pads
    ("gmii_eth_clocks", 0,
        Subsignal("tx",  Pins(1)),
        Subsignal("gtx", Pins(1)),
        Subsignal("rx",  Pins(1))
    ),
    ("gmii_eth", 0,
        Subsignal("rst_n",   Pins(1)),
        Subsignal("int_n",   Pins(1)),
        Subsignal("mdio",    Pins(1)),
        Subsignal("mdc",     Pins(1)),
        Subsignal("rx_dv",   Pins(1)),
        Subsignal("rx_er",   Pins(1)),
        Subsignal("rx_data", Pins(8)),
        Subsignal("tx_en",   Pins(1)),
        Subsignal("tx_er",   Pins(1)),
        Subsignal("tx_data", Pins(8)),
        Subsignal("col",     Pins(1)),
        Subsignal("crs",     Pins(1))
    ),

    # RGMII PHY Pads
    ("rgmii_eth_clocks", 0,
        Subsignal("tx", Pins(1)),
        Subsignal("rx", Pins(1))
    ),
    ("rgmii_eth", 0,
        Subsignal("rst_n",   Pins(1)),
        Subsignal("int_n",   Pins(1)),
        Subsignal("mdio",    Pins(1)),
        Subsignal("mdc",     Pins(1)),
        Subsignal("rx_ctl",  Pins(1)),
        Subsignal("rx_data", Pins(4)),
        Subsignal("tx_ctl",  Pins(1)),
        Subsignal("tx_data", Pins(4))
    ),

    # UDP
    ("udp_sink", 0,
        # Control
        Subsignal("valid",      Pins(1)),
        Subsignal("last",       Pins(1)),
        Subsignal("ready",      Pins(1)),
        # Param
        Subsignal("src_port",   Pins(16)),
        Subsignal("dst_port",   Pins(16)),
        Subsignal("ip_address", Pins(32)),
        Subsignal("length",     Pins(16)),
        # Payload
        Subsignal("data",       Pins(32)),
        Subsignal("error",      Pins(4))
    ),

    ("udp_source", 0,
        # Control
        Subsignal("valid",      Pins(1)),
        Subsignal("last",       Pins(1)),
        Subsignal("ready",      Pins(1)),
        # Param
        Subsignal("src_port",   Pins(16)),
        Subsignal("dst_port",   Pins(16)),
        Subsignal("ip_address", Pins(32)),
        Subsignal("length",     Pins(16)),
        # Payload
        Subsignal("data",       Pins(32)),
        Subsignal("error",      Pins(4))
    ),
]

# PHY Core -----------------------------------------------------------------------------------------

class PHYCore(SoCMini):
    def __init__(self, platform, core_config):
        for deprecated in ("csr_map", "mem_map"):
            if deprecated in core_config:
                raise RuntimeWarning("Config option {!r} is now a sub-option of 'soc'".format(deprecated))

        # SoC parameters ---------------------------------------------------------------------------
        soc_args = {}
        if "soc" in core_config:
            soc_config = core_config["soc"]

            for arg in soc_config:
                if arg in ("csr_map", "interrupt_map", "mem_map"):
                    getattr(self, arg).update(soc_config[arg])
                else:
                    soc_args[arg] = soc_config[arg]

        # SoCMini ----------------------------------------------------------------------------------
        SoCMini.__init__(self, platform, clk_freq=core_config["clk_freq"], **soc_args)

        # CRG --------------------------------------------------------------------------------------
        self.submodules.crg = CRG(platform.request("sys_clock"), platform.request("sys_reset"))

        # PHY --------------------------------------------------------------------------------------
        phy = core_config["phy"]
        if phy in [liteeth_phys.LiteEthPHYMII]:
            ethphy = phy(
                clock_pads = platform.request("mii_eth_clocks"),
                pads       = platform.request("mii_eth"))
        elif phy in [liteeth_phys.LiteEthPHYRMII]:
            ethphy = phy(
                clock_pads = platform.request("rmii_eth_clocks"),
                pads       = platform.request("rmii_eth"))
        elif phy in [liteeth_phys.LiteEthPHYGMII]:
            ethphy = phy(
                clock_pads = platform.request("gmii_eth_clocks"),
                pads       = platform.request("gmii_eth"))
        elif phy in [liteeth_phys.LiteEthPHYGMIIMII]:
            ethphy = phy(
                clock_pads = platform.request("gmii_eth_clocks"),
                pads       = platform.request("gmii_eth"),
                clk_freq   = self.clk_freq)
        elif phy in [liteeth_phys.LiteEthS7PHYRGMII, liteeth_phys.LiteEthECP5PHYRGMII]:
            ethphy = phy(
                clock_pads         = platform.request("rgmii_eth_clocks"),
                pads               = platform.request("rgmii_eth"),
                tx_delay           = core_config.get("phy_tx_delay", 2e-9),
                rx_delay           = core_config.get("phy_rx_delay", 2e-9),
                with_hw_init_reset = False) # FIXME: required since sys_clk = eth_rx_clk.
        else:
            raise ValueError("Unsupported PHY")
        self.submodules.ethphy = ethphy

        # Timing constaints.
        # Generate timing constraints to ensure the "keep" attribute is properly set on the various
        # clocks. This also adds the constraints to the generated .xdc that can then be "imported"
        # in the project using the core.
        eth_rx_clk = getattr(ethphy, "crg", ethphy).cd_eth_rx.clk
        eth_tx_clk = getattr(ethphy, "crg", ethphy).cd_eth_tx.clk
        from liteeth.phy.model import LiteEthPHYModel
        if not isinstance(ethphy, LiteEthPHYModel):
            self.platform.add_period_constraint(eth_rx_clk, 1e9/phy.rx_clk_freq)
            self.platform.add_period_constraint(eth_tx_clk, 1e9/phy.tx_clk_freq)
            self.platform.add_false_path_constraints(self.crg.cd_sys.clk, eth_rx_clk, eth_tx_clk)

# MAC Core -----------------------------------------------------------------------------------------

class MACCore(PHYCore):
    def __init__(self, platform, core_config):
        # Parameters -------------------------------------------------------------------------------
        nrxslots = core_config.get("nrxslots", 2)
        ntxslots = core_config.get("ntxslots", 2)

        # PHY --------------------------------------------------------------------------------------
        PHYCore.__init__(self, platform, core_config)

        # MAC --------------------------------------------------------------------------------------
        self.submodules.ethmac = ethmac = LiteEthMAC(
            phy            = self.ethphy,
            dw             = 32,
            interface      = "wishbone",
            endianness     = core_config["endianness"],
            nrxslots       = nrxslots,
            ntxslots       = ntxslots,
            full_memory_we = core_config.get("full_memory_we", False))

        # Wishbone Interface -----------------------------------------------------------------------
        ethmac_region_size = (nrxslots + ntxslots)*buffer_depth
        ethmac_region = SoCRegion(origin=self.mem_map.get("ethmac", None), size=ethmac_region_size, cached=False)
        self.bus.add_slave(name="ethmac", slave=ethmac.bus, region=ethmac_region)

        # Interrupt Interface ----------------------------------------------------------------------
        self.comb += self.platform.request("interrupt").eq(self.ethmac.ev.irq)

# UDP Core -----------------------------------------------------------------------------------------

class UDPCore(PHYCore):
    def __init__(self, platform, core_config):
        # PHY --------------------------------------------------------------------------------------
        PHYCore.__init__(self, platform, core_config)

        # Core -------------------------------------------------------------------------------------
        mac_address = core_config.get("mac_address", None)
        if mac_address is None:
            mac_address = platform.request("mac_address") # Get MAC Address from IOs when not specified.
        ip_address = core_config.get("ip_address", None)
        if ip_address is None:
            ip_address = platform.request("ip_address")   # Get IP Address from IOs when not specified.
        self.submodules.core = LiteEthUDPIPCore(self.ethphy,
            mac_address = mac_address,
            ip_address  = ip_address,
            clk_freq    = core_config["clk_freq"]
        )

        # UDP --------------------------------------------------------------------------------------
        udp_port = self.core.udp.crossbar.get_port(core_config["port"], 8)
        # XXX avoid manual connect
        udp_sink = self.platform.request("udp_sink")
        self.comb += [
            # Control
            udp_port.sink.valid.eq(udp_sink.valid),
            udp_port.sink.last.eq(udp_sink.last),
            udp_sink.ready.eq(udp_port.sink.ready),

            # Param
            udp_port.sink.src_port.eq(udp_sink.src_port),
            udp_port.sink.dst_port.eq(udp_sink.dst_port),
            udp_port.sink.ip_address.eq(udp_sink.ip_address),
            udp_port.sink.length.eq(udp_sink.length),

            # Payload
            udp_port.sink.data.eq(udp_sink.data),
            udp_port.sink.error.eq(udp_sink.error)
        ]
        udp_source = self.platform.request("udp_source")
        self.comb += [
            # Control
            udp_source.valid.eq(udp_port.source.valid),
            udp_source.last.eq(udp_port.source.last),
            udp_port.source.ready.eq(udp_source.ready),

            # Param
            udp_source.src_port.eq(udp_port.source.src_port),
            udp_source.dst_port.eq(udp_port.source.dst_port),
            udp_source.ip_address.eq(udp_port.source.ip_address),
            udp_source.length.eq(udp_port.source.length),

            # Payload
            udp_source.data.eq(udp_port.source.data),
            udp_source.error.eq(udp_port.source.error)
        ]

# Build --------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LiteEth standalone core generator")
    builder_args(parser)
    parser.set_defaults(output_dir="build")
    parser.add_argument("config", help="YAML config file")
    args = parser.parse_args()
    core_config = yaml.load(open(args.config).read(), Loader=yaml.Loader)

    # Convert YAML elements to Python/LiteX --------------------------------------------------------
    for k, v in core_config.items():
        replaces = {"False": False, "True": True, "None": None}
        for r in replaces.keys():
            if v == r:
                core_config[k] = replaces[r]
        if k == "phy":
            core_config[k] = getattr(liteeth_phys, core_config[k])
        if k in ["clk_freq", "phy_tx_delay", "phy_rx_delay"]:
            core_config[k] = int(float(core_config[k]))

    # Generate core --------------------------------------------------------------------------------
    if  "device" not in core_config:
        core_config["device"] = ""
    if core_config["vendor"] == "lattice":
        toolchain = core_config.get("toolchain", "diamond")
        platform  = LatticePlatform(core_config["device"], io=[], toolchain=toolchain)
    elif core_config["vendor"] == "xilinx":
        toolchain = core_config.get("toolchain", "vivado")
        platform  = XilinxPlatform(core_config["device"], io=[], toolchain=toolchain)
    else:
        raise ValueError("Unsupported vendor: {}".format(core_config["vendor"]))
    platform.add_extension(_io)

    if core_config["core"] == "wishbone":
        soc = MACCore(platform, core_config)
    elif core_config["core"] == "udp":
        soc = UDPCore(platform, core_config)
    else:
        raise ValueError("Unknown core: {}".format(core_config["core"]))

    builder_arguments = builder_argdict(args)
    builder_arguments["compile_gateware"] = False
    if builder_arguments["csr_csv"] is None:
        builder_arguments["csr_csv"] = os.path.join(builder_arguments["output_dir"], "csr.csv")

    builder = Builder(soc, **builder_arguments)
    builder.build(build_name="liteeth_core")

if __name__ == "__main__":
    main()
