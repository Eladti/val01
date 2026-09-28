"""Frame encoding/decoding and CRC-8 for the VAL01 link. See docs/protocol.md."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

SOF_REQ = 0xA5
SOF_RSP = 0x5A
HEADER_LEN = 4  # SOF, CMD/STATUS, ADDR, LEN
MAX_PAYLOAD = 4


class Cmd(IntEnum):
    READ = 0x01
    WRITE = 0x02
    RESET = 0x03


class Status(IntEnum):
    OK = 0x00
    BAD_CRC = 0x01
    BAD_CMD = 0x02
    BAD_ADDR = 0x03
    READ_ONLY = 0x04
    BAD_LEN = 0x05


class ProtocolError(Exception):
    """Malformed frame received from the DUT."""


def crc8(data: bytes, poly: int = 0x07, init: int = 0x00) -> int:
    """CRC-8/SMBUS: poly 0x07, init 0x00, no reflection, no final XOR."""
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def _build(sof: int, code: int, addr: int, payload: bytes) -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload too long: {len(payload)} > {MAX_PAYLOAD}")
    body = bytes([code & 0xFF, addr & 0xFF, len(payload)]) + payload
    return bytes([sof]) + body + bytes([crc8(body)])


def build_request(cmd: int, addr: int, payload: bytes = b"") -> bytes:
    return _build(SOF_REQ, cmd, addr, payload)


def build_response(status: int, addr: int, payload: bytes = b"") -> bytes:
    return _build(SOF_RSP, status, addr, payload)


@dataclass(frozen=True)
class Response:
    status: Status
    addr: int
    payload: bytes


def parse_response(frame: bytes) -> Response:
    """Validate and decode one complete response frame."""
    if len(frame) < HEADER_LEN + 1:
        raise ProtocolError(f"frame too short: {frame.hex()}")
    if frame[0] != SOF_RSP:
        raise ProtocolError(f"bad SOF 0x{frame[0]:02X}")
    length = frame[3]
    if len(frame) != HEADER_LEN + length + 1:
        raise ProtocolError(f"length mismatch: LEN={length}, frame={frame.hex()}")
    body = frame[1:-1]
    if crc8(body) != frame[-1]:
        raise ProtocolError(f"response CRC mismatch: {frame.hex()}")
    try:
        status = Status(frame[1])
    except ValueError as exc:
        raise ProtocolError(f"unknown status 0x{frame[1]:02X}") from exc
    return Response(status=status, addr=frame[2], payload=bytes(frame[4:-1]))
