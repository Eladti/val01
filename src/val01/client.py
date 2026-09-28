"""Host-side driver: the only API tests use to talk to a DUT."""

from __future__ import annotations

from collections import Counter

from .protocol import HEADER_LEN, Cmd, ProtocolError, Response, Status, build_request, parse_response
from .registers import Reg
from .transport import Transport


class DutError(Exception):
    """DUT answered with a non-OK status."""

    def __init__(self, status: Status, addr: int):
        super().__init__(f"{status.name} at addr 0x{addr:02X}")
        self.status = status
        self.addr = addr


class DutTimeout(Exception):
    """DUT did not answer (or answered partially) in time."""


class DutClient:
    """
    retries: extra attempts after a link-level failure (timeout, corrupted
    response, or BAD_CRC meaning the request was corrupted). Retrying is safe
    because every command is idempotent (docs/protocol.md). Other error
    statuses are real DUT answers and are never retried.
    Default 0, so conformance tests see raw DUT behavior.
    """

    def __init__(self, transport: Transport, retries: int = 0):
        self.t = transport
        self.retries = retries
        self.stats: Counter[str] = Counter()

    # ---- low level -----------------------------------------------------
    def send_raw(self, frame: bytes) -> Response:
        """Send arbitrary bytes, return the parsed response (no status check)."""
        self.t.flush_input()
        self.t.write(frame)
        header = self.t.read(HEADER_LEN)
        if len(header) < HEADER_LEN:
            raise DutTimeout(f"header timeout, got {header.hex() or 'nothing'}")
        rest = self.t.read(header[3] + 1)
        if len(rest) < header[3] + 1:
            raise DutTimeout(f"body timeout, got {(header + rest).hex()}")
        return parse_response(header + rest)

    def _transact(self, cmd: Cmd, addr: int, payload: bytes = b"") -> Response:
        frame = build_request(cmd, addr, payload)
        for _ in range(self.retries + 1):
            self.stats["attempts"] += 1
            try:
                rsp = self.send_raw(frame)
            except (DutTimeout, ProtocolError) as exc:
                self.stats[type(exc).__name__] += 1
                last_exc: Exception = exc
                continue
            if rsp.status == Status.BAD_CRC:
                self.stats["BAD_CRC"] += 1
                last_exc = DutError(rsp.status, addr)
                continue
            break
        else:
            self.stats["gave_up"] += 1
            raise last_exc

        if rsp.addr != (addr & 0xFF):
            raise ProtocolError(f"addr echo mismatch: sent 0x{addr:02X}, got 0x{rsp.addr:02X}")
        if rsp.status != Status.OK:
            raise DutError(rsp.status, addr)
        return rsp

    # ---- high level ----------------------------------------------------
    def read_reg(self, addr: int) -> int:
        rsp = self._transact(Cmd.READ, addr)
        if len(rsp.payload) != 1:
            raise ProtocolError(f"READ returned {len(rsp.payload)} bytes")
        return rsp.payload[0]

    def write_reg(self, addr: int, value: int) -> None:
        self._transact(Cmd.WRITE, addr, bytes([value & 0xFF]))

    def reset(self) -> None:
        self._transact(Cmd.RESET, 0)

    def read_adc(self) -> int:
        lo = self.read_reg(Reg.ADC_L)  # latches ADC_H
        hi = self.read_reg(Reg.ADC_H)
        return (hi << 8) | lo
