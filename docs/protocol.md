# VAL01 DUT Protocol Specification — v0.3

Single source of truth for the host ↔ DUT link. The Python simulator
(`src/val01/sim_dut.py`) and the Arduino firmware
(`firmware/val01_dut/val01_dut.ino`) both implement exactly this document. If behavior and spec disagree, that is a bug.

## Physical link

UART, 115200 baud, 8N1. The simulator skips the physical layer and exchanges bytes directly.

## Frame format

Request (host → DUT):

| Byte | Field   | Notes                              |
|------|---------|------------------------------------|
| 0    | SOF     | `0xA5`                             |
| 1    | CMD     | see Commands                       |
| 2    | ADDR    | register address                   |
| 3    | LEN     | payload length, 0..4 (see Framing errors) |
| 4..  | PAYLOAD | LEN bytes                          |
| last | CRC8    | over bytes 1..(3+LEN), excludes SOF |

Response (DUT → host): same layout, with SOF `0x5A` and STATUS in place of CMD.

CRC-8: poly `0x07`, init `0x00`, no reflection, no final XOR
(CRC-8/SMBUS). Check value for ASCII `"123456789"` is `0xF4`.

## Framing errors and timing

- **Inter-byte timeout (20 ms):** if a frame stops arriving partway through, the DUT
  discards the partial frame once the timeout expires.
- **LEN > 4:** the DUT cannot locate the CRC, so it cannot verify the frame's
  integrity. It discards the frame **without responding** and increments ERR_COUNT.
  The host sees a timeout and retries.
- Rule: the DUT never returns a semantic status (BAD_CMD / BAD_ADDR / BAD_LEN /
  READ_ONLY) for a frame whose CRC has not been verified.
- Bytes before an SOF are skipped (resync after line noise).

## Commands

| CMD  | Name  | Req LEN | Rsp payload       |
|------|-------|---------|-------------------|
| 0x01 | READ  | 0       | 1 byte: value     |
| 0x02 | WRITE | 1       | none              |
| 0x03 | RESET | 0       | none (ADDR ignored)|

## Status codes

| Code | Name      | Meaning                               |
|------|-----------|---------------------------------------|
| 0x00 | OK        |                                       |
| 0x01 | BAD_CRC   | request CRC mismatch; ERR_COUNT += 1  |
| 0x02 | BAD_CMD   | unknown command                       |
| 0x03 | BAD_ADDR  | register does not exist               |
| 0x04 | READ_ONLY | write to a read-only register         |
| 0x05 | BAD_LEN   | LEN wrong for this command            |

## Register map

| Addr | Name       | Access | Reset | Description                                     |
|------|------------|--------|-------|-------------------------------------------------|
| 0x00 | ID         | RO     | 0xA7  | device ID                                       |
| 0x01 | FW_VERSION | RO     | 0x01  | firmware version                                |
| 0x02 | SCRATCH    | RW     | 0x00  | free read/write register                        |
| 0x03 | CTRL       | RW     | 0x00  | bit0 LED, bit1 LOOP_OUT (drives loopback pin)   |
| 0x04 | STATUS     | RO     | —     | bit0 LOOP_IN (reads loopback pin)               |
| 0x05 | ADC_L      | RO     | —     | ADC[7:0]; **reading ADC_L latches ADC_H**       |
| 0x06 | ADC_H      | RO     | —     | ADC[9:8] (bits 7..2 always 0); latched value    |
| 0x07 | ERR_COUNT  | RO     | 0x00  | CRC + framing errors, saturates at 0xFF         |

The latch rule makes reading ADC_L and then ADC_H return one consistent
10-bit sample, even while the ADC keeps converting.

Loopback: a jumper connects LOOP_OUT (D7) to LOOP_IN (D8). LOOP_IN has its
internal pull-up enabled. With the jumper fitted, STATUS.bit0 follows CTRL.bit1.
With the jumper removed, STATUS.bit0 reads 1 whatever CTRL.bit1 is.

## Idempotency

Every command is idempotent: sending it twice leaves the DUT in the same state
as sending it once. ERR_COUNT and the ADC latch are the only side effects, and
they are diagnostic. So a host can safely retry after a timeout, even if the
first attempt was actually executed.
