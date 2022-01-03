# If the design does not create a "sync" clock domain, it is created by the Amaranth build system
# using the platform default clock (and default reset, if any).

from amaranth import *
from amaranth.build import Pins, Attrs, Connector
from amaranth_boards.butterstick import *
from amaranth_boards.resources import *

# add_connectors

class SygyzyPmodAdapter():
    def __init__(self, syzygy_name):
        self.syzygy_name = syzygy_name

    def connectors(self):
        pmod_pins = { "pmod_1a" : ["S12",  "S8",  "S4",  "S0", "-", "-", "S14", "S10",  "S6",  "S2", "-", "-"],
                      "pmod_1b" : ["S13",  "S9",  "S5",  "S1", "-", "-", "S15", "S11",  "S7",  "S3", "-", "-"],
                      "pmod_2a" : ["S28", "S24", "S20", "S16", "-", "-", "S30", "S26", "S22", "S18", "-", "-"],
                      "pmod_2b" : ["S29", "S25", "S21", "S17", "-", "-", "S31", "S27", "S23", "S19", "-", "-"],
        }

        connectors = []
        for pmod in pmod_pins:
            pin_str = ""
            for pin in pmod_pins[pmod]:
                pin_str += "{}:{} ".format(self.syzygy_name, pin)
            connectors.append(Connector(pmod, 0, pin_str))
        return connectors

_pmod = [
        *LEDResources("led_1a", pins="pmod_1a_0:1 pmod_1a_0:2 pmod_1a_0:3 pmod_1a_0:4 pmod_1a_0:7 pmod_1a_0:8 pmod_1a_0:9 pmod_1a_0:10", attrs=Attrs(IO_TYPE="LVCMOS33")),
        *LEDResources("led_1b", pins="pmod_1b_0:1 pmod_1b_0:2 pmod_1b_0:3 pmod_1b_0:4 pmod_1b_0:7 pmod_1b_0:8 pmod_1b_0:9 pmod_1b_0:10", attrs=Attrs(IO_TYPE="LVCMOS33")),
        *LEDResources("led_2a", pins="pmod_2a_0:1 pmod_2a_0:2 pmod_2a_0:3 pmod_2a_0:4 pmod_2a_0:7 pmod_2a_0:8 pmod_2a_0:9 pmod_2a_0:10", attrs=Attrs(IO_TYPE="LVCMOS33")),
        *LEDResources("led_2b", pins="pmod_2b_0:1 pmod_2b_0:2 pmod_2b_0:3 pmod_2b_0:4 pmod_2b_0:7 pmod_2b_0:8 pmod_2b_0:9 pmod_2b_0:10", attrs=Attrs(IO_TYPE="LVCMOS33")),
]

class VccioCtrl(Elaboratable):
    def __init__(self, vccio_pins):
        self.vccio_pins = vccio_pins
        
    def elaborate(self, platform):
        m = Module()

        pwm_timer = Signal(14)

        m.d.sync += pwm_timer.eq(pwm_timer + 1)

        m.d.comb += self.vccio_pins.pdm[0].eq(pwm_timer < int(2**14 * (0.10))) # 3.3V
        m.d.comb += self.vccio_pins.pdm[1].eq(pwm_timer < int(2**14 * (0.10))) # 3.3V
        m.d.comb += self.vccio_pins.pdm[2].eq(pwm_timer < int(2**14 * (0.70))) # 1.8V

        m.d.comb += self.vccio_pins.en.eq(1)

        return m

class Shifty(Elaboratable):
    def elaborate(self, platform):
        leds = []
        for pmod in ["led_1a", "led_1b", "led_2a", "led_2b"]:
            for pin in range(0,8):
                leds.append(platform.request(pmod, pin))

        m = Module()

        counter = Signal(23)
        m.d.sync += counter.eq(counter + 1)
        
        shifter = Signal(len(leds), reset=1)

        index = 0
        for led in leds:
            m.d.comb += led.o.eq(shifter[index])
            index += 1
        with m.If(shifter == 0):
            m.d.sync += shifter.eq(1)
        with m.Elif(counter == 0):
            m.d.sync += shifter.eq(shifter << 1)
 
        vccio_ctrl = platform.request("vccio_ctrl", 0)
        m.submodules.vccio_ctrl = VccioCtrl(vccio_ctrl)

        return m


if __name__ == "__main__":
    platform = ButterStickPlatform()
    platform.add_connectors(SygyzyPmodAdapter("syzygy_0").connectors())
    platform.add_resources(_pmod)
    platform.build(Shifty(), do_program=True)
