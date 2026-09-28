"""Byte-level transports. Tests never touch these directly — only DutClient does.

SimTransport: in-process simulator (CI).
SerialTransport: a serial port. Used for the real Arduino (target hw) and for the
host-compiled firmware behind a pseudo-terminal (target fw).
"""

from __future__ import annotations

import time
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


class SerialTransport(Transport):
    """
    boot_delay: opening the port on an Uno/Nano pulses DTR, which resets the
    board. The bootloader then runs for about 1.5 s and drops any bytes sent
    to it. Wait, then discard whatever arrived during boot.
    """

    def __init__(self, port: str, baud: int = 115200, timeout: float = 0.3, boot_delay: float = 2.0):
        try:
            import serial  # pyserial
        except ImportError as exc:
            raise RuntimeError('pyserial is required: pip install -e ".[hw]"') from exc
        try:
            self.ser = serial.Serial(port, baud, timeout=timeout)
        except serial.SerialException as exc:
            raise RuntimeError(
                f"cannot open {port}: {exc}\n"
                "  - is the board plugged in?  ls /dev/ttyACM* /dev/ttyUSB*\n"
                "  - permission denied?        sudo usermod -aG dialout $USER  (then log out/in)\n"
                "  - port busy?                close the Arduino IDE Serial Monitor"
            ) from exc
        if boot_delay:
            time.sleep(boot_delay)
        self.ser.reset_input_buffer()

    def write(self, data: bytes) -> None:
        self.ser.write(data)
        self.ser.flush()

    def read(self, n: int) -> bytes:
        return self.ser.read(n)

    def flush_input(self) -> None:
        self.ser.reset_input_buffer()

    def close(self) -> None:
        self.ser.close()
