"""Fault injection: the host must never accept corrupted data.

Every injected fault ends one of two ways. The client recovers through a
retry, or it raises. It must never return a wrong value.
"""

import time

import pytest

from val01.client import DutClient, DutError, DutTimeout
from val01.faults import Fault, FaultyTransport
from val01.protocol import Cmd, ProtocolError, Status, build_request
from val01.registers import DEVICE_ID, Reg
from val01.sim_dut import SimDut
from val01.transport import SimTransport

pytestmark = pytest.mark.dut

LINK_FAULTS = [Fault.FLIP_REQ, Fault.FLIP_RSP, Fault.TRUNCATE_RSP, Fault.DROP_RSP]


def make_client(script=None, rate=0.0, seed=0, retries=0):
    ft = FaultyTransport(SimTransport(SimDut()), script=script, rate=rate, seed=seed)
    return DutClient(ft, retries=retries), ft


@pytest.mark.tp("FI-001")
@pytest.mark.parametrize("fault", LINK_FAULTS, ids=lambda f: f.value)
@pytest.mark.parametrize("seed", range(10))
def test_fault_detected_without_retry(sim_dut, fault, seed):
    dut, _ = make_client(script=[fault], seed=seed)
    with pytest.raises((DutTimeout, ProtocolError, DutError)) as exc:
        dut.read_reg(Reg.ID)
    if isinstance(exc.value, DutError):
        assert exc.value.status == Status.BAD_CRC  # request corruption, caught by the DUT


@pytest.mark.tp("FI-002")
@pytest.mark.parametrize("fault", LINK_FAULTS, ids=lambda f: f.value)
def test_single_fault_recovered_by_retry(sim_dut, fault):
    dut, ft = make_client(script=[fault], retries=1)
    assert dut.read_reg(Reg.ID) == DEVICE_ID
    assert dut.stats["attempts"] == 2
    assert ft.injected[fault] == 1


@pytest.mark.tp("FI-003")
def test_retries_exhausted_raises(sim_dut):
    dut, _ = make_client(script=[Fault.DROP_RSP] * 3, retries=2)
    with pytest.raises(DutTimeout):
        dut.read_reg(Reg.ID)
    assert dut.stats["gave_up"] == 1


@pytest.mark.tp("FI-004")
def test_dut_error_status_not_retried(sim_dut):
    # BAD_ADDR is a real answer from the DUT, not a link failure. Retrying would hide bugs.
    dut, _ = make_client(retries=3)
    with pytest.raises(DutError) as exc:
        dut.read_reg(0x7F)
    assert exc.value.status == Status.BAD_ADDR
    assert dut.stats["attempts"] == 1


@pytest.mark.tp("PROT-005")
def test_dut_drops_partial_frame_after_gap(dut):
    # A frame cut off mid-way must not glue itself onto the next request
    good = build_request(Cmd.READ, Reg.ID)
    dut.t.write(good[:3])  # partial frame...
    time.sleep(0.05)  # ...then silence longer than the 20 ms inter-byte timeout
    rsp = dut.send_raw(good)
    assert rsp.status == Status.OK and rsp.payload == bytes([DEVICE_ID])


@pytest.mark.tp("FI-006")
def test_late_response_discarded(dut):
    # A response to an earlier request arrives late and sits in the RX buffer.
    # The next transaction must not consume it as its own answer.
    dut.write_reg(Reg.SCRATCH, 0x3C)
    dut.t.write(build_request(Cmd.READ, Reg.ID))  # response left unread = stale
    time.sleep(0.05)  # let it arrive (real links are not instantaneous)
    assert dut.read_reg(Reg.SCRATCH) == 0x3C


@pytest.mark.tp("PROT-006")
@pytest.mark.parametrize("bad_len", [5, 0x20, 0xFF])
def test_oversize_len_dropped_silently(dut, bad_len):
    # An invalid LEN means the CRC can't be located. The DUT must not answer, only count it.
    frame = bytes([0xA5, Cmd.READ, Reg.ID, bad_len, 0x00])
    with pytest.raises(DutTimeout):
        dut.send_raw(frame)
    assert dut.read_reg(Reg.ERR_COUNT) == 1


@pytest.mark.tp("FI-005")
def test_soak_no_silent_corruption(sim_dut, record_property):
    """2000 random transactions at a 20% fault rate with retries=3.

    Pass criteria: zero silently wrong values, and at least 99% of
    transactions completed.
    """
    n, rate = 2000, 0.20
    dut, ft = make_client(rate=rate, seed=1234, retries=3)
    rng = ft.rng
    expected_scratch = 0x00
    wrong = completed = gave_up = unexpected = 0

    for _ in range(n):
        try:
            if rng.random() < 0.5:
                value = rng.randrange(256)
                dut.write_reg(Reg.SCRATCH, value)
                expected_scratch = value
            else:
                got = dut.read_reg(Reg.SCRATCH)
                if expected_scratch is not None and got != expected_scratch:
                    wrong += 1
            completed += 1
        except (DutTimeout, ProtocolError, DutError) as exc:
            # Under link faults the only legal DUT error is BAD_CRC (after retries ran out).
            # Any other status means the DUT answered a frame it should have rejected.
            if isinstance(exc, DutError) and exc.status != Status.BAD_CRC:
                unexpected += 1
            gave_up += 1
            expected_scratch = None  # a failed write may or may not have landed

    print(
        f"\nsoak: n={n} rate={rate} completed={completed} gave_up={gave_up} "
        f"unexpected={unexpected} "
        f"wrong={wrong} injected={dict((f.value, c) for f, c in ft.injected.items())} "
        f"client={dict(dut.stats)}"
    )
    for key, val in {
        "transactions": n, "fault_rate": rate, "completed": completed, "gave_up": gave_up,
        "expected_gave_up": round(n * rate ** (dut.retries + 1), 1), "wrong": wrong,
        "faults_injected": sum(c for f, c in ft.injected.items() if f is not Fault.NONE),
    }.items():
        record_property(key, val)
    assert wrong == 0, "client returned corrupted data"
    assert unexpected == 0, "DUT returned a non-link error status under link faults"
    assert gave_up == dut.stats["gave_up"], "every failure should come from exhausted retries"
    assert completed / n >= 0.99
