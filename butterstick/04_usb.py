#!/usr/bin/env python3
#
# Portions Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import os
import logging

from luna                           import top_level_cli
from luna.full_devices              import USBSerialDevice
from luna.gateware.platform.core import LUNAPlatform
from luna.gateware.architecture.car import LunaDomainGenerator

from amaranth import *
from amaranth.build import *
from amaranth.vendor.lattice_ecp5 import LatticeECP5Platform

from amaranth_boards.butterstick import ButterStickPlatform as _ButterStickPlatform


class VccioCtrl(Elaboratable):
    def __init__(self, vccio_pins):
        self.vccio_pins = vccio_pins

    def _pwm_timer_limit(self, platform, instance):
        voltage = platform.vccio_voltage(instance)
        # constants per @tnt
        # The PDM output would have an DC output impedance of 68k and can be modeled like a voltage source of 3.3V * x with a 68k in series. Then essentially you have 3 resistors connecting to FB :
        #   One from that PDM source
        #   One from VIO output with 53.6k
        #   One from GND with 13k
        # The regulator will fight for regulation and adjust its output such that the voltage node at its feedback connection is 0.6V.
        # From there you can just use Kirchhoff's to derive the equation and solve for Vio.
        limit_float = (3.546 - voltage) / 2.601
        return int(limit_float * 2**14)
        
    def elaborate(self, platform):

        m = Module()

        if platform.vccio_voltage(0) is None:
            logging.warning("VCCIO configuration is required for ULPI USB to function.")
            return m

        pwm_timer = Signal(14)
        m.d.sync += pwm_timer.eq(pwm_timer + 1)
        # SYGYZY 0
        m.d.comb += self.vccio_pins.pdm[0].eq(pwm_timer < self._pwm_timer_limit(platform, 0))
        # SYGYZY 1
        m.d.comb += self.vccio_pins.pdm[1].eq(pwm_timer < self._pwm_timer_limit(platform, 1))
        # SYGYZY 2 & ULPI USB (limit to 1.8V - 3.3V for USB3343) 
        m.d.comb += self.vccio_pins.pdm[2].eq(pwm_timer < self._pwm_timer_limit(platform, 2))
        m.d.comb += self.vccio_pins.en.eq(1)

        return m

class LunaECP5DomainGenerator(LunaDomainGenerator):
    """ ECP5 clock domain generator for LUNA. Assumes a 60MHz input clock. """

    # For debugging, we'll allow the ECP5's onboard clock to generate a 62MHz
    # oscillator signal. This won't work for USB, but it'll at least allow
    # running some basic self-tests. The clock is 310 MHz by default, so
    # dividing by 5 will yield 62MHz.
    OSCG_DIV = 5

    # Quick configuration selection
    DEFAULT_CLOCK_FREQUENCIES_MHZ = {
        "fast": 240,
        "sync": 120,
        "usb":  60
    }

    def __init__(self, *, clock_frequencies=None, clock_signal_name=None):
        """
        Parameters:
            clock_frequencies -- A dictionary mapping 'fast', 'sync', and 'usb' to the clock
                                 frequencies for those domains, in MHz. Valid choices for each
                                 domain are 60, 120, and 240. If not provided, fast will be
                                 assumed to be 240, sync will assumed to be 120, and usb will
                                 be assumed to be a standard 60.
        """
        super().__init__(clock_signal_name=clock_signal_name)
        self.clock_frequencies = clock_frequencies


    def create_submodules(self, m, platform):

        self._pll_lock   = Signal()


        # Figure out our platform's clock frequencies -- grab the platform's
        # defaults, and then override any with our local, caller-provided copies.
        new_clock_frequencies = platform.DEFAULT_CLOCK_FREQUENCIES_MHZ.copy()
        if self.clock_frequencies:
            new_clock_frequencies.update(self.clock_frequencies)
        self.clock_frequencies = new_clock_frequencies


        # Use the provided clock name and frequency for our input; or the default clock
        # if no name was provided.
        clock_name = self.clock_name if self.clock_name else platform.default_clk
        clock_frequency = self.clock_frequency if self.clock_name else platform.default_clk_frequency

        # Create absolute-frequency copies of our PLL outputs.
        # We'll use the generate_ methods below to select which domains
        # apply to which components.
        self._clk_240MHz = Signal()
        self._clk_120MHz = Signal()
        self._clk_60MHz  = Signal()
        self._clock_options = {
            60:  self._clk_60MHz,
            120: self._clk_120MHz,
            240: self._clk_240MHz
        }

        # Grab our input clock
        # For debugging: if our clock name is "OSCG", allow using the internal
        # oscillator. This is mostly useful for debugging.
        if clock_name == "OSCG":
            logging.warning("Using FPGA-internal oscillator for an approximately 62MHz.")
            logging.warning("USB communication won't work for f_OSC != 60MHz.")

            input_clock = Signal()
            m.submodules += Instance("OSCG", p_DIV=self.OSCG_DIV, o_OSC=input_clock)
            clock_frequency = 62.0
        else:
            input_clock = platform.request(clock_name)

        pll_params_per_freq = {
            "62000000.0" : { "CLKFB_DIV" : 4,
            },
            "60000000.0" : { "CLKFB_DIV" : 4,
            },
            "30000000.0" : { "CLKFB_DIV" : 8,
            },
        }

        if not str(clock_frequency) in pll_params_per_freq:
            raise ValueError("Unsupported clock frequency {}MHz".format(clock_frequency/1e6))

        pll_params = pll_params_per_freq[str(clock_frequency)]

        # Instantiate the ECP5 PLL.
        # These constants generated by Clarity Designer; which will
        # ideally be replaced by an open-source component.
        # (see https://github.com/SymbiFlow/prjtrellis/issues/34.)
        m.submodules.pll = Instance("EHXPLLL",

                # Clock in.
                i_CLKI=input_clock,

                # Generated clock outputs.
                o_CLKOP=self._clk_240MHz,
                o_CLKOS=self._clk_120MHz,
                o_CLKOS2=self._clk_60MHz,

                # Status.
                o_LOCK=self._pll_lock,

                # PLL parameters...
                p_PLLRST_ENA="DISABLED",
                p_INTFB_WAKE="DISABLED",
                p_STDBY_ENABLE="DISABLED",
                p_DPHASE_SOURCE="DISABLED",
                p_CLKOS3_FPHASE=0,
                p_CLKOS3_CPHASE=0,
                p_CLKOS2_FPHASE=0,
                p_CLKOS2_CPHASE=7,
                p_CLKOS_FPHASE=0,
                p_CLKOS_CPHASE=3,
                p_CLKOP_FPHASE=0,
                p_CLKOP_CPHASE=1,
                p_PLL_LOCK_MODE=0,
                p_CLKOS_TRIM_DELAY="0",
                p_CLKOS_TRIM_POL="FALLING",
                p_CLKOP_TRIM_DELAY="0",
                p_CLKOP_TRIM_POL="FALLING",
                p_OUTDIVIDER_MUXD="DIVD",
                p_CLKOS3_ENABLE="DISABLED",
                p_OUTDIVIDER_MUXC="DIVC",
                p_CLKOS2_ENABLE="ENABLED",
                p_OUTDIVIDER_MUXB="DIVB",
                p_CLKOS_ENABLE="ENABLED",
                p_OUTDIVIDER_MUXA="DIVA",
                p_CLKOP_ENABLE="ENABLED",
                p_CLKOS3_DIV=1,
                p_CLKOS2_DIV=8,
                p_CLKOS_DIV=4,
                p_CLKOP_DIV=2,
                p_CLKFB_DIV=pll_params["CLKFB_DIV"],
                p_CLKI_DIV=1,
                p_FEEDBK_PATH="CLKOP",

                # Internal feedback.
                i_CLKFB=self._clk_240MHz,

                # Control signals.
                i_RST=0,
                i_PHASESEL0=0,
                i_PHASESEL1=0,
                i_PHASEDIR=0,
                i_PHASESTEP=0,
                i_PHASELOADREG=0,
                i_STDBY=0,
                i_PLLWAKESYNC=0,

                # Output Enables.
                i_ENCLKOP=0,
                i_ENCLKOS=0,
                i_ENCLKOS2=0,
                i_ENCLKOS3=0,

                # Synthesis attributes.
                a_FREQUENCY_PIN_CLKI="60.000000",
                a_FREQUENCY_PIN_CLKOS2="60.000000",
                a_FREQUENCY_PIN_CLKOS="120.000000",
                a_FREQUENCY_PIN_CLKOP="240.000000",
                a_ICP_CURRENT="9",
                a_LPF_RESISTOR="8"
        )


        # Set up our global resets so the system is kept fully in reset until
        # our core PLL is fully stable. This prevents us from internally clock
        # glitching ourselves before our PLL is locked. :)
        m.d.comb += [
            ResetSignal("sync").eq(~self._pll_lock),
            ResetSignal("fast").eq(~self._pll_lock),
        ]

    def generate_usb_clock(self, m, platform):
        return self._clock_options[self.clock_frequencies['usb']]

    def generate_sync_clock(self, m, platform):
        return self._clock_options[self.clock_frequencies['sync']]

    def generate_fast_clock(self, m, platform):
        return self._clock_options[self.clock_frequencies['fast']]

class ButterStickDomainGenerator(LunaECP5DomainGenerator):
    """ clock domain generator; uses the luna one with 30Mhz input

    We also add vccio management here for want of a better place.  This is needed to bring up the ulpi.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def elaborate(self, platform):
        m = super().elaborate(platform)
        m.submodules.vccio_ctrl = VccioCtrl(platform.request("vccio_ctrl", 0))
        return m
    
class ButterStickPlatform(_ButterStickPlatform, LUNAPlatform):
    name                   = "ButterStick"
    clock_domain_generator = ButterStickDomainGenerator
    default_usb_connection = "usb"
    default_clk = "clk30"
    DEFAULT_CLOCK_FREQUENCIES_MHZ = {
        "fast": 240,
        "sync": 120,
        "usb":  60
    }
    
    # Add I/O aliases with standard LUNA naming.
    additional_resources = [
    ]

    # Create our semantic aliases.
    def __init__(self, *args, **kwargs):
        logging.warning("This platform is not officially supported, and thus not tested. Your results may vary.")
        super().__init__(*args, **kwargs)
        self.add_resources(self.additional_resources)

class USBSerialDeviceExample(Elaboratable):
    """ Device that acts as a 'USB-to-serial' loopback using our premade gateware. """

    def elaborate(self, platform):
        m = Module()

        # Generate our domain clocks/resets.
        m.submodules.car = platform.clock_domain_generator()

        # Create our USB-to-serial converter.
        ulpi = platform.request(platform.default_usb_connection)
        m.submodules.usb_serial = usb_serial = \
                USBSerialDevice(bus=ulpi, idVendor=0x16d0, idProduct=0x0f3b)

        m.d.comb += [
            # Place the streams into a loopback configuration...
            usb_serial.tx.payload  .eq(usb_serial.rx.payload),
            usb_serial.tx.valid    .eq(usb_serial.rx.valid),
            usb_serial.tx.first    .eq(usb_serial.rx.first),
            usb_serial.tx.last     .eq(usb_serial.rx.last),
            usb_serial.rx.ready    .eq(usb_serial.tx.ready),

            # ... and always connect by default.
            usb_serial.connect     .eq(1)
        ]

        return m

if __name__ == "__main__":
    os.environ["LUNA_PLATFORM"] = "04_usb:ButterStickPlatform"
    top_level_cli(USBSerialDeviceExample)
        
