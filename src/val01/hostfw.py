"""Run the DUT firmware on the host, behind a pseudo-terminal (target `fw`).

The unmodified sketch (firmware/val01_dut/val01_dut.ino) is compiled with a
small Arduino API shim (firmware/host/). The process's stdin/stdout are
wired to the master side of a pty. The test side opens the slave side with
the ordinary SerialTransport, so the host driver and the firmware logic both
run exactly as they would against a board. Only the MCU and USB cable are
missing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tty
from pathlib import Path

from .transport import SerialTransport

SOURCES = ("firmware/val01_dut/val01_dut.ino", "firmware/host/Arduino.h", "firmware/host/main.cpp")


def build(root: Path) -> Path:
    """Compile the host firmware if missing or older than its sources."""
    out = root / "build" / "val01_dut_host"
    srcs = [root / s for s in SOURCES]
    if out.exists() and all(out.stat().st_mtime >= s.stat().st_mtime for s in srcs):
        return out
    cxx = os.environ.get("CXX") or shutil.which("g++") or shutil.which("c++")
    if not cxx:
        raise RuntimeError("no C++ compiler found (need g++) for the fw target")
    out.parent.mkdir(exist_ok=True)
    cmd = [cxx, "-std=c++11", "-O1", "-Wall", "-Wextra", "-Werror",
           f"-I{root / 'firmware/host'}", str(root / "firmware/host/main.cpp"), "-o", str(out)]
    subprocess.run(cmd, check=True)
    return out


class HostFirmware:
    """Context manager: start the firmware process, yield a SerialTransport to it."""

    def __init__(self, root: Path, jumper: bool = True):
        self.root = Path(root)
        self.jumper = jumper

    def __enter__(self) -> SerialTransport:
        binary = build(self.root)
        master, slave = os.openpty()
        tty.setraw(slave)  # no echo, no newline translation: a clean 8-bit byte pipe
        env = dict(os.environ, VAL01_JUMPER="1" if self.jumper else "0")
        self.proc = subprocess.Popen([str(binary)], stdin=master, stdout=master, env=env)
        os.close(master)  # the child holds its own copy
        self._slave = slave
        self.transport = SerialTransport(os.ttyname(slave), boot_delay=0.05)
        return self.transport

    def __exit__(self, *exc) -> None:
        self.transport.close()
        os.close(self._slave)
        self.proc.terminate()
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.kill()
