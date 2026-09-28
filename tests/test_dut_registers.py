"""DUT validation tests. Target-agnostic: they only use the `dut` fixture.

Each test carries a test-plan ID (docs/test_plan.md) via @pytest.mark.tp.
"""

import pytest

from val01.client import DutError
from val01.protocol import Cmd, Status, build_request
from val01.registers import (
    CTRL_LOOP_OUT,
    DEVICE_ID,
    FW_VERSION,
    REGISTER_MAP,
    STATUS_LOOP_IN,
    Reg,
)

pytestmark = pytest.mark.dut

RW_REGS = [a for a, d in REGISTER_MAP.items() if d.writable]
RO_REGS = [a for a, d in REGISTER_MAP.items() if not d.writable]


@pytest.mark.tp("REG-001")
def test_device_id(dut):
    assert dut.read_reg(Reg.ID) == DEVICE_ID


@pytest.mark.tp("REG-002")
def test_fw_version(dut):
    assert dut.read_reg(Reg.FW_VERSION) == FW_VERSION


@pytest.mark.tp("REG-003")
@pytest.mark.parametrize("addr", [a for a, d in REGISTER_MAP.items() if d.reset is not None])
def test_reset_values(dut, addr):
    assert dut.read_reg(addr) == REGISTER_MAP[addr].reset


@pytest.mark.tp("REG-004")
@pytest.mark.parametrize("addr", RW_REGS, ids=lambda a: Reg(a).name)
@pytest.mark.parametrize(
    "value",
    [0x00, 0xFF, 0x55, 0xAA] + [1 << i for i in range(8)],
    ids=lambda v: f"0x{v:02X}",
)
def test_rw_write_readback(dut, addr, value):
    dut.write_reg(addr, value)
    assert dut.read_reg(addr) == value


@pytest.mark.tp("REG-005")
@pytest.mark.parametrize("addr", RO_REGS, ids=lambda a: Reg(a).name)
def test_ro_write_rejected_and_value_unchanged(dut, addr):
    before = dut.read_reg(addr) if REGISTER_MAP[addr].reset is not None else None
    with pytest.raises(DutError) as exc:
        dut.write_reg(addr, 0x5A)
    assert exc.value.status == Status.READ_ONLY
    if before is not None:
        assert dut.read_reg(addr) == before


@pytest.mark.tp("REG-006")
@pytest.mark.parametrize("addr", [0x08, 0x7F, 0xFF])
def test_invalid_address(dut, addr):
    with pytest.raises(DutError) as exc:
        dut.read_reg(addr)
    assert exc.value.status == Status.BAD_ADDR


@pytest.mark.tp("REG-007")
def test_reset_restores_defaults(dut):
    dut.write_reg(Reg.SCRATCH, 0xC3)
    dut.write_reg(Reg.CTRL, 0x03)
    dut.reset()
    assert dut.read_reg(Reg.SCRATCH) == 0x00
    assert dut.read_reg(Reg.CTRL) == 0x00


@pytest.mark.tp("PROT-001")
def test_bad_crc_rejected_and_counted(dut):
    frame = bytearray(build_request(Cmd.READ, Reg.ID))
    frame[-1] ^= 0xFF
    rsp = dut.send_raw(bytes(frame))
    assert rsp.status == Status.BAD_CRC
    assert dut.read_reg(Reg.ERR_COUNT) == 1


@pytest.mark.tp("PROT-002")
def test_unknown_command(dut):
    rsp = dut.send_raw(build_request(0x7E, Reg.ID))
    assert rsp.status == Status.BAD_CMD


@pytest.mark.tp("PROT-003")
@pytest.mark.parametrize(
    "cmd,payload",
    [(Cmd.READ, b"\x00"), (Cmd.WRITE, b""), (Cmd.WRITE, b"\x00\x00")],
    ids=["read-with-payload", "write-empty", "write-2-bytes"],
)
def test_wrong_length(dut, cmd, payload):
    rsp = dut.send_raw(build_request(cmd, Reg.SCRATCH, payload))
    assert rsp.status == Status.BAD_LEN


@pytest.mark.tp("PROT-004")
def test_resync_after_garbage(dut):
    # Leading noise bytes (no 0xA5) must be skipped by the DUT's frame hunter
    rsp = dut.send_raw(b"\x00\x13\x37" + build_request(Cmd.READ, Reg.ID))
    assert rsp.status == Status.OK and rsp.payload == bytes([DEVICE_ID])


@pytest.mark.tp("GPIO-001")
@pytest.mark.parametrize("level", [0, 1, 0, 1])
def test_loopback_follows_output(dut, level):
    dut.write_reg(Reg.CTRL, CTRL_LOOP_OUT if level else 0)
    assert bool(dut.read_reg(Reg.STATUS) & STATUS_LOOP_IN) == bool(level)


@pytest.mark.tp("ADC-001")
def test_adc_in_range(dut):
    for _ in range(20):
        assert 0 <= dut.read_adc() <= 0x3FF


@pytest.mark.tp("ADC-002")
def test_adc_high_byte_reserved_bits_zero(dut):
    dut.read_reg(Reg.ADC_L)
    assert dut.read_reg(Reg.ADC_H) & 0xFC == 0
