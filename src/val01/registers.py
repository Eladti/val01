"""Register map — mirrors the table in docs/protocol.md."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Reg(IntEnum):
    ID = 0x00
    FW_VERSION = 0x01
    SCRATCH = 0x02
    CTRL = 0x03
    STATUS = 0x04
    ADC_L = 0x05
    ADC_H = 0x06
    ERR_COUNT = 0x07


@dataclass(frozen=True)
class RegDef:
    addr: Reg
    writable: bool
    reset: int | None  # None = value comes from hardware, not reset


REGISTER_MAP: dict[int, RegDef] = {
    r.addr: r
    for r in (
        RegDef(Reg.ID, False, 0xA7),
        RegDef(Reg.FW_VERSION, False, 0x01),
        RegDef(Reg.SCRATCH, True, 0x00),
        RegDef(Reg.CTRL, True, 0x00),
        RegDef(Reg.STATUS, False, None),
        RegDef(Reg.ADC_L, False, None),
        RegDef(Reg.ADC_H, False, None),
        RegDef(Reg.ERR_COUNT, False, 0x00),
    )
}

# Bit fields
CTRL_LED = 1 << 0
CTRL_LOOP_OUT = 1 << 1
STATUS_LOOP_IN = 1 << 0

DEVICE_ID = 0xA7
FW_VERSION = 0x01
ADC_MAX = 0x3FF
