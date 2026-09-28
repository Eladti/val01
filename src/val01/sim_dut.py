"""Behavioral model of the DUT.

Deliberately written like firmware: a byte-by-byte receive state machine,
not a function that gets handed whole frames. Later the Arduino sketch
ports this same logic.
"""

from __future__ import annotations

from typing import Callable

from .protocol import HEADER_LEN, MAX_PAYLOAD, SOF_REQ, Cmd, Status, build_response, crc8
from .registers import (
    ADC_MAX,
    CTRL_LOOP_OUT,
    REGISTER_MAP,
    STATUS_LOOP_IN,
    Reg,
)


class SimDut:
    def __init__(self, adc_source: Callable[[], int] | None = None, loopback_wired: bool = True):
        self._adc_source = adc_source or (lambda: 512)
        self.loopback_wired = loopback_wired
        self._rx = bytearray()
        self.reset()

    # ---- register behavior ---------------------------------------------
    def reset(self) -> None:
        self._regs = {a: (d.reset or 0) for a, d in REGISTER_MAP.items()}
        self._adc_h_latch = 0

    def _read(self, addr: int) -> int:
        if addr == Reg.STATUS:
            loop_in = self.loopback_wired and bool(self._regs[Reg.CTRL] & CTRL_LOOP_OUT)
            return STATUS_LOOP_IN if loop_in else 0
        if addr == Reg.ADC_L:
            sample = self._adc_source() & ADC_MAX
            self._adc_h_latch = sample >> 8  # latch high bits on low-byte read
            return sample & 0xFF
        if addr == Reg.ADC_H:
            return self._adc_h_latch
        return self._regs[addr]

    # ---- frame handling ------------------------------------------------
    def feed(self, data: bytes) -> bytes:
        """Push received bytes in; return any response bytes produced."""
        out = bytearray()
        for b in data:
            if not self._rx and b != SOF_REQ:
                continue  # hunt for start-of-frame
            self._rx.append(b)
            if len(self._rx) >= HEADER_LEN:
                length = self._rx[3]
                if length > MAX_PAYLOAD:
                    out += build_response(Status.BAD_LEN, self._rx[2])
                    self._rx.clear()
                    continue
                if len(self._rx) == HEADER_LEN + length + 1:
                    out += self._handle(bytes(self._rx))
                    self._rx.clear()
        return bytes(out)

    def _handle(self, frame: bytes) -> bytes:
        cmd, addr, length = frame[1], frame[2], frame[3]
        payload = frame[4:-1]
        if crc8(frame[1:-1]) != frame[-1]:
            self._regs[Reg.ERR_COUNT] = min(self._regs[Reg.ERR_COUNT] + 1, 0xFF)
            return build_response(Status.BAD_CRC, addr)

        if cmd == Cmd.RESET:
            if length != 0:
                return build_response(Status.BAD_LEN, addr)
            self.reset()
            return build_response(Status.OK, addr)
        if cmd not in (Cmd.READ, Cmd.WRITE):
            return build_response(Status.BAD_CMD, addr)
        if addr not in REGISTER_MAP:
            return build_response(Status.BAD_ADDR, addr)

        if cmd == Cmd.READ:
            if length != 0:
                return build_response(Status.BAD_LEN, addr)
            return build_response(Status.OK, addr, bytes([self._read(addr)]))

        # WRITE
        if length != 1:
            return build_response(Status.BAD_LEN, addr)
        if not REGISTER_MAP[addr].writable:
            return build_response(Status.READ_ONLY, addr)
        self._regs[addr] = payload[0]
        return build_response(Status.OK, addr)
