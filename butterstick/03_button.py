# If the design does not create a "sync" clock domain, it is created by the Amaranth build system
# using the platform default clock (and default reset, if any).

from amaranth import *
from amaranth.build import Pins, Attrs, Connector
from amaranth_boards.butterstick import *
from amaranth_boards.resources import *

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

class Button(Elaboratable):
    def elaborate(self, platform):
        btn0 = platform.request("button", 0)
        btn1 = platform.request("button", 1)

        prog = platform.request("program", 0)

        led0 = platform.request("led", 0)
        rgb = platform.request("rgb_led", 0)

        m = Module()

        m.d.comb += prog.o.eq(btn0.i)
        m.d.comb += led0.o.eq(btn1.i)
        m.d.comb += rgb.b.o.eq(1)
        return m


if __name__ == "__main__":
    platform = ButterStickPlatform()
    platform.build(Button(), do_program=True)
