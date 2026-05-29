# SPDX-FileCopyrightText: 2026 Ephemerality
# SPDX-License-Identifier: MIT

"""
`adafruit_yoto.aw88194`
================================================================================

CircuitPython driver for the AW88194 audio amplifier

The Yoto Mini sends I2S to this chip for the built-in speaker
Init values are from hardware I2C capture, minus SKTune values and other undocumented registers
Register names and format follow the AW88194A datasheet (16-bit registers, MSB first)
https://doc.awinic.com/doc/20230609wm/c4ab5a93-136b-4909-b968-7850d29a550a.pdf

* Author(s): Ephemerality

"""

import time

from adafruit_bus_device.i2c_device import I2CDevice
from adafruit_register.i2c_bit import RWBit
from adafruit_register.i2c_bits import ROBits, RWBits
from micropython import const

_DEFAULT_ADDRESS = const(0x34)
_REG_WIDTH = const(2)  # 16-bit registers

_REG_ID = const(0x00)       # ID / soft-reset (write 0x55AA to reset)
_REG_SYSST = const(0x01)    # system status (read-only)
_REG_SYSINT = const(0x02)  # interrupt mask
_REG_SYSINTM = const(0x03)  # interrupt mask
_REG_SYSCTRL = const(0x04)  # system control
_REG_I2SCTRL = const(0x05)  # I2S interface control
_REG_I2SCFG1 = const(0x06)  # I2S configuration 1
_REG_PWMCTRL = const(0x08)  # muting
_REG_HAGCCFG6 = const(0x0F) # hardware AGC volume
_REG_BSTCTRL1 = const(0x60) # boost control register 1
_REG_BSTCTRL2 = const(0x61) # boost control register 2

_CHIP_ID = const(0x1806)
_RESET_KEY = const(0x55AA)
_DEFAULT_SPK_GAIN = const(0x06)


class AW88194:
    """Driver for the AW88194 audio amplifier"""

    # SYSST @ 0x01 (read-only)
    _pll_locked = ROBits(1, _REG_SYSST, 0, register_width=_REG_WIDTH, lsb_first=False)
    """PLLS - PLL locked status - 0: unlocked, 1: locked"""
    _over_temp = ROBits(1, _REG_SYSST, 1, register_width=_REG_WIDTH, lsb_first=False)
    """OTHS - die temperature is higher than 160C"""
    _pre_clipping = ROBits(1, _REG_SYSST, 2, register_width=_REG_WIDTH, lsb_first=False)
    """CLIP_PRES = clipping pre-status"""
    _over_current_status = ROBits(1, _REG_SYSST, 3, register_width=_REG_WIDTH, lsb_first=False)
    """OCDS - over current status"""
    _clocks_stable = ROBits(1, _REG_SYSST, 4, register_width=_REG_WIDTH, lsb_first=False)
    """CLKS - all internal clocks are stable (required before audio will play)"""
    _no_clocks = ROBits(1, _REG_SYSST, 5, register_width=_REG_WIDTH, lsb_first=False)
    """NOCLKS - reference clock for PLL is not available (i.e. I2S BCLK signal not started)"""
    _wds = ROBits(1, _REG_SYSST, 6, register_width=_REG_WIDTH, lsb_first=False)
    """WDS - DSP watchdog is triggered"""
    _clipping = ROBits(1, _REG_SYSST, 7, register_width=_REG_WIDTH, lsb_first=False)
    """CLIPS - clipping status - 0: not clipping, 1: clipping"""
    _switching = ROBits(1, _REG_SYSST, 8, register_width=_REG_WIDTH, lsb_first=False)
    """SWS - amp switching status - 0: not switiching, 1: switching"""
    _boost_status = ROBits(1, _REG_SYSST, 9, register_width=_REG_WIDTH, lsb_first=False)
    """BSTS - boost status - 0: not ready, 1: ready"""
    _boost_ovp_status = ROBits(1, _REG_SYSST, 10, register_width=_REG_WIDTH, lsb_first=False)
    """OVPS - Boost OVP status indicator"""
    _boost_over_current = ROBits(1, _REG_SYSST, 11, register_width=_REG_WIDTH, lsb_first=False)
    """BSTOCS - boost over current status"""
    _dsps = ROBits(1, _REG_SYSST, 12, register_width=_REG_WIDTH, lsb_first=False)
    """DSPS - set when DSP acknowledge request flag is set"""
    _adps = ROBits(1, _REG_SYSST, 13, register_width=_REG_WIDTH, lsb_first=False)
    """ADPS - Smart Boost status - 0: transparent, 1: boost"""
    _under_voltage = ROBits(1, _REG_SYSST, 14, register_width=_REG_WIDTH, lsb_first=False)
    """UVLS - VDD under voltage indicator - 0: VDD > 2.7V, 1: VDD < 2.6V"""

    # SYSCTRL @ 0x04
    power_down = RWBit(_REG_SYSCTRL, 0, register_width=_REG_WIDTH, lsb_first=False)
    """PWDN - system power down control - 0 = active, 1 = all circuits enter power down mode"""
    amp_power_down = RWBit(_REG_SYSCTRL, 1, register_width=_REG_WIDTH, lsb_first=False)
    """AMPPD - amplifier power down - 0 = active, 1 = amp powered down"""
    dsp_by = RWBit(_REG_SYSCTRL, 2, register_width=_REG_WIDTH, lsb_first=False)
    """DSPBY - DSP bypass I guess?"""
    i2s_enable = RWBit(_REG_SYSCTRL, 6, register_width=_REG_WIDTH, lsb_first=False)
    """I2SEN - enable the I2S interface module"""
    receiver_gain = RWBits(2, _REG_SYSCTRL, 10, register_width=_REG_WIDTH, lsb_first=False)
    """RCV_GAIN - receiver mode AMP_NORM_V configuration - 0: AMP_NORM_V=4.5 1: AMP_NORM_V=5 2: AMP_NORM_V=5.5 3: AMP_NORM_V=5.5"""
    spk_gain = RWBits(3, _REG_SYSCTRL, 12, register_width=_REG_WIDTH, lsb_first=False)
    """SPK_GAIN - speaker-mode gain - 0: AMP_NORM_V=7 1: AMP_NORM_V=8 2: AMP_NORM_V=10 3: AMP_NORM_V=12 4: AMP_NORM_V=14 6: AMP_NORM_V=16"""

    # I2SCTRL @ 0x05
    i2s_sample_rate = RWBits(4, _REG_I2SCTRL, 0, register_width=_REG_WIDTH, lsb_first=False)
    """I2SSR - sample rate - 0: 8 kHz, 1: 11.025 kHz, 2: 12 kHz, 3: 16 kHz, 4: 22.05 kHz, 5: 24 kHz, 6: 32 kHz, 7: 44.1 kHz, 8: 48 kHz, 9: 96 kHz, 10~15: Reserved"""
    i2s_bit_clock = RWBits(2, _REG_I2SCTRL, 4, register_width=_REG_WIDTH, lsb_first=False)
    """I2SBCK - bit clock - 0: 32*fs(16*2), 1: 48*fs(24*2), 2: 64*fs(32*2), 3: Reserved"""
    i2s_frame_select = RWBits(2, _REG_I2SCTRL, 6, register_width=_REG_WIDTH, lsb_first=False)
    """I2SFS (frame select/word select/LRCLK) - 0: 16 bits, 1: 20 bits, 2: 24 bits, 3: 32bits"""
    i2s_mode = RWBits(2, _REG_I2SCTRL, 8, register_width=_REG_WIDTH, lsb_first=False)
    """I2SMD - interface mode - 0: Philips standard, 1: MSB justified, 2: LSB justified, 3: Reserved"""
    i2s_channel_select = RWBits(2, _REG_I2SCTRL, 10, register_width=_REG_WIDTH, lsb_first=False)
    """CHSEL - left/right channel select - 0: Reserved, 1: Left, 2: Right, 3: Mono"""
    i2s_input_level_select = RWBit(_REG_SYSCTRL, 13, register_width=_REG_WIDTH, lsb_first=False)
    """INPLEV - input level select - 0: all input not attenuated, 1: all input attenuated by -6dB"""

    # PWMCTRL @ 0x08
    hardware_mute = RWBit(_REG_PWMCTRL, 0, register_width=_REG_WIDTH, lsb_first=False)
    """HMUTE - hardware mute - 0: unmuted, 1; muted"""
    dc_cancel_enable = RWBit(_REG_PWMCTRL, 1, register_width=_REG_WIDTH, lsb_first=False)
    """HDCCE - hardware DC cancel enable - 0: disabled, 1: enabled"""

    # HAGCCFG6 @ 0x0F
    _volume = RWBits(8, _REG_HAGCCFG6, 8, register_width=_REG_WIDTH, lsb_first=False)
    """VOL - volume control from 0 to -96dB (0 being max volume) - bits 7-4: increments of -6dB, bits 3:0: increments of -0.5dB"""

    # BSTCTRL1 - boost control register 1 @ 0x60
    boost_attack_threshold = RWBits(6, _REG_BSTCTRL1, 0, register_width=_REG_WIDTH, lsb_first=False)
    """BST_ATH - smart boost attack threshold - when the signal is above the threshold, the voltage of VBST will be raised higher than VDD in smart boost mode"""
    boost_release_threshold = RWBits(6, _REG_BSTCTRL1, 8, register_width=_REG_WIDTH, lsb_first=False)
    """BST_RTH - smart boost release threshold - when the signal is below the threshold, the voltage of VBST will not be raised higher than VDD in smart boost mode"""

    # BSTCTRL2 - boost control register 2 @ 0x61
    boost_deglitch_time = RWBits(3, _REG_BSTCTRL2, 0, register_width=_REG_WIDTH, lsb_first=False)
    """BST_TDEG - smart boost small signal level detection deglitch time - 0: 1.33 ms 1: 2.66 ms 2: 5.32 ms 3: 21.30 ms 4: 85.20 ms 5: 340.79 ms 6: 1.363 s 7: 2.73 s"""
    boost_mode = RWBits(3, _REG_BSTCTRL2, 4, register_width=_REG_WIDTH, lsb_first=False)
    """BST_MODE - smart boost mode - 0: transparent 1: force boost 5: smart boost 1 6: smart boost 2"""

    def __init__(self, i2c_bus, address=_DEFAULT_ADDRESS):
        """Create an AW88194 instance.

        :param ~busio.I2C i2c_bus: The I2C bus the device is connected to
        :param int address: 7-bit I2C address (default: 0x34)
        :raises RuntimeError: if the chip ID register does not read 0x1806
        """
        self.i2c_device = I2CDevice(i2c_bus, address)
        if self.chip_id != _CHIP_ID:
            raise RuntimeError(f"Failed to find AW88194! Chip ID: 0x{self.chip_id:04X}")

    def _write_register16(self, register, value):
        with self.i2c_device as i2c:
            i2c.write(bytes([register, (value >> 8) & 0xFF, value & 0xFF]))

    def _read_register16(self, register):
        buf = bytearray(2)
        with self.i2c_device as i2c:
            i2c.write_then_readinto(bytes([register]), buf)
        return (buf[0] << 8) | buf[1]

    @property
    def chip_id(self):
        return self._read_register16(_REG_ID)

    @property
    def mute(self):
        return self.hardware_mute

    @mute.setter
    def mute(self, value):
        self.hardware_mute = value

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value):
        """Set the volume - 0 = loudest, 255 = quietest"""
        self._volume = value & 0xFF

    @property
    def system_status(self):
        """Most relevant SYSST status bits"""
        return {
            "raw": self._read_register16(_REG_SYSST),
            "pll_locked": bool(self._pll_locked),
            "clocks_stable": bool(self._clocks_stable),
            "boost_ready": bool(self._boost_status),
            "clipping": bool(self._clipping),
        }

    def _apply_sysctrl_power_up(self):
        self.power_down = False
        self.amp_power_down = False
        self.spk_gain = _DEFAULT_SPK_GAIN
        self.receiver_gain = 1
        self.dsp_by = True
        self.i2s_enable = True

    def configure(self):
        """Apply the Yoto Mini boot configuration (minus Smart-K tuning settings)"""
        self._apply_sysctrl_power_up()
        self._volume = 10
        self.dc_cancel_enable = True

        self.i2s_sample_rate = 7 # 44.1kHz
        self.i2s_bit_clock = 0 # 32*fs
        self.i2s_frame_select = 0 # 16 bits
        self.i2s_channel_select = 3 # Mono, since the mini only has the 1 speaker

        self.boost_attack_threshold = 9
        self.boost_release_threshold = 10
        self.boost_deglitch_time = 3
        self.boost_mode = 6

    def enable(self, poll_timeout_s=0.5):
        """Enables I2S input and unmutes the amplifier, then polls SYSST for PLL lock and boost ready state

        :param float poll_timeout_s: Seconds to wait for PLL + boost ready
        :return: True if PLL and boost status bits set before timeout
        """
        self._read_register16(_REG_SYSST)
        self._read_register16(_REG_SYSINT)
        self._read_register16(_REG_SYSINTM)
        self._write_register16(_REG_SYSINTM, 0xFFF4)
        self._read_register16(_REG_HAGCCFG6)
        self.hardware_mute = False

        # if the PLL and boost aren't coming up, the init has failed
        deadline = time.monotonic() + poll_timeout_s
        while time.monotonic() < deadline:
            st = self.system_status
            if st["pll_locked"] and st["boost_ready"]:
                return True
            time.sleep(0.01)
        return False

    def reset(self):
        """Soft-reset all registers"""
        self._write_register16(_REG_ID, _RESET_KEY)