"""Tests that need control over the DUT's inputs — only possible in simulation."""

import pytest

from val01.client import DutClient
from val01.sim_dut import SimDut
from val01.transport import SimTransport

pytestmark = pytest.mark.dut


@pytest.mark.tp("ADC-003")
def test_adc_latch_gives_coherent_sample(sim_dut):
    # The ADC changes between the two byte reads (0x0FF -> 0x100).
    # Without the latch, the host would assemble 0x1FF, a value that never existed.
    samples = iter([0x0FF, 0x100])
    dut = DutClient(SimTransport(SimDut(adc_source=lambda: next(samples))))
    assert dut.read_adc() == 0x0FF

