"""Unit tests for the framework itself (host side). No DUT involved."""

import pytest

from val01.protocol import (
    Cmd,
    ProtocolError,
    Status,
    build_request,
    build_response,
    crc8,
    parse_response,
)

pytestmark = pytest.mark.unit


def test_crc8_check_value():
    # Standard CRC-8/SMBUS check value
    assert crc8(b"123456789") == 0xF4


def test_crc8_empty():
    assert crc8(b"") == 0x00


def test_build_request_layout():
    frame = build_request(Cmd.WRITE, 0x02, b"\x5a")
    assert frame[:5] == bytes([0xA5, 0x02, 0x02, 0x01, 0x5A])
    assert frame[-1] == crc8(frame[1:-1])


def test_payload_too_long_rejected():
    with pytest.raises(ValueError):
        build_request(Cmd.WRITE, 0x02, b"\x00" * 5)


def test_response_roundtrip():
    rsp = parse_response(build_response(Status.OK, 0x00, b"\xa7"))
    assert (rsp.status, rsp.addr, rsp.payload) == (Status.OK, 0x00, b"\xa7")


@pytest.mark.parametrize("bit", range(8))
def test_response_single_bit_flip_detected(bit):
    frame = bytearray(build_response(Status.OK, 0x00, b"\xa7"))
    frame[4] ^= 1 << bit  # corrupt the payload byte
    with pytest.raises(ProtocolError, match="CRC"):
        parse_response(bytes(frame))


@pytest.mark.parametrize(
    "frame",
    [b"", b"\x5a\x00", b"\xa5\x00\x00\x00\x00", b"\x5a\x00\x00\x02\x01\x00"],
    ids=["empty", "short", "wrong-sof", "truncated"],
)
def test_malformed_response_rejected(frame):
    with pytest.raises(ProtocolError):
        parse_response(frame)
