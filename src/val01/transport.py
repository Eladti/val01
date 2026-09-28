"""Byte-level transports. Tests never touch these directly — only DutClient does.

SimTransport: in-process simulator (CI).
SerialTransport: real UART to the Arduino (added in the HW step).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .sim_dut import SimDut


class Transport(ABC):
    @abstractmethod
    def write(self, data: bytes) -> None: ...

    @abstractmethod
    def read(self, n: int) -> bytes:
        """Return up to n bytes; fewer means the read timed out."""

    @abstractmethod
    def flush_input(self) -> None: ...

    def close(self) -> None:  # noqa: B027 — optional hook
        pass


class SimTransport(Transport):
    def __init__(self, dut: SimDut | None = None):
        self.dut = dut or SimDut()
        self._rx = bytearray()

    def write(self, data: bytes) -> None:
        # Timing model: bytes within one write() arrive back to back, and the
        # gap before each write() is longer than the DUT's inter-byte timeout.
        self.dut.on_idle()
        self._rx += self.dut.feed(data)

    def read(self, n: int) -> bytes:
        chunk, self._rx = bytes(self._rx[:n]), self._rx[n:]
        return chunk

    def flush_input(self) -> None:
        self._rx.clear()
