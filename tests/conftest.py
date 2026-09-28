"""Target selection: the same tests run against the simulator or real hardware.

    pytest                  # simulator (default, what CI runs)
    pytest --target hw      # real DUT over UART (added in the HW step)
"""

import pytest

from val01.client import DutClient
from val01.sim_dut import SimDut
from val01.transport import SimTransport


def pytest_addoption(parser):
    parser.addoption("--target", choices=["sim", "hw"], default="sim", help="DUT target")


@pytest.fixture
def target(request):
    return request.config.getoption("--target")


@pytest.fixture
def sim_dut(target):
    """Direct handle on the simulator, for sim-only tests (e.g. controlling ADC input)."""
    if target != "sim":
        pytest.skip("simulator-only test")
    return SimDut()


@pytest.fixture
def dut(target, request):
    """A freshly reset DutClient — the only handle DUT tests should use."""
    if target == "hw":
        pytest.skip("hw target not implemented yet")
    client = DutClient(SimTransport(request.getfixturevalue("sim_dut")))
    client.reset()
    yield client
    client.t.close()
