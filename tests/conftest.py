"""Target selection: the same tests run against three DUT implementations.

    pytest                              # sim: Python behavioral model (default)
    pytest --target fw                  # fw:  the Arduino sketch compiled for the host, over a pty
    pytest --target hw --port /dev/ttyACM0   # hw: the real board over USB serial

DUT tests use the `dut` fixture only, so they never know which target they're on.
Tests that need control over DUT internals use `sim_dut` and are skipped off-sim.
"""

import os
from pathlib import Path

import pytest

from val01.client import DutClient
from val01.sim_dut import SimDut
from val01.transport import SimTransport

ROOT = Path(__file__).resolve().parents[1]


def pytest_addoption(parser):
    parser.addoption("--target", choices=["sim", "fw", "hw"], default="sim", help="DUT target")
    parser.addoption("--port", default=os.environ.get("VAL01_PORT", "/dev/ttyACM0"),
                     help="serial port for --target hw (or env VAL01_PORT)")
    parser.addoption("--baud", type=int, default=115200)
    parser.addoption("--jumper-removed", action="store_true",
                     help="hw: operator confirms the D7-D8 jumper is pulled (enables GPIO-002)")


@pytest.fixture(scope="session")
def target(request):
    return request.config.getoption("--target")


@pytest.fixture
def sim_dut(target):
    """Direct handle on the simulator, for sim-only tests (e.g. controlling ADC input)."""
    if target != "sim":
        pytest.skip("simulator-only test")
    return SimDut()


@pytest.fixture(scope="session")
def link(target, request):
    """One serial connection per session. Reopening the port would reset the board every test."""
    if target == "fw":
        from val01.hostfw import HostFirmware

        with HostFirmware(ROOT) as transport:
            yield transport
    elif target == "hw":
        from val01.transport import SerialTransport

        opt = request.config.getoption
        transport = SerialTransport(opt("--port"), opt("--baud"))
        yield transport
        transport.close()
    else:
        yield None


@pytest.fixture
def dut(target, request):
    """A freshly reset DutClient — the only handle DUT tests should use."""
    if target == "sim":
        client = DutClient(SimTransport(request.getfixturevalue("sim_dut")))
    else:
        client = DutClient(request.getfixturevalue("link"))
    client.reset()
    return client


@pytest.fixture
def dut_no_jumper(target, request):
    """DUT with the LOOP_OUT→LOOP_IN jumper removed (sim and fw can do this in software)."""
    if target == "sim":
        client = DutClient(SimTransport(SimDut(loopback_wired=False)))
        client.reset()
        yield client
    elif target == "fw":
        from val01.hostfw import HostFirmware

        with HostFirmware(ROOT, jumper=False) as transport:
            client = DutClient(transport)
            client.reset()
            yield client
    elif request.config.getoption("--jumper-removed"):
        client = DutClient(request.getfixturevalue("link"))
        client.reset()
        yield client
    else:
        pytest.skip("hw: pull the D7-D8 jumper and rerun with --jumper-removed")
