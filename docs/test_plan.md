# VAL01 Test Plan — v0.2

Every DUT test carries its ID via `@pytest.mark.tp("<ID>")`. Targets: `sim`
means it runs on the simulator (CI), `hw` means it runs on the Arduino DUT.
Tests marked sim-only need control over DUT inputs that hardware can't
provide on its own.

| ID       | Requirement (docs/protocol.md)                          | Method                                         | Targets  |
|----------|---------------------------------------------------------|------------------------------------------------|----------|
| REG-001  | ID reads 0xA7                                           | read                                           | sim, hw  |
| REG-002  | FW_VERSION reads 0x01                                   | read                                           | sim, hw  |
| REG-003  | Registers with a defined reset hold it after RESET      | read all after reset                           | sim, hw  |
| REG-004  | RW registers store any 8-bit value                      | patterns 00/FF/55/AA + walking ones            | sim, hw  |
| REG-005  | Writes to RO registers → READ_ONLY, value unchanged     | write + readback                               | sim, hw  |
| REG-006  | Unmapped addresses → BAD_ADDR                           | read 0x08, 0x7F, 0xFF                          | sim, hw  |
| REG-007  | RESET restores RW registers to defaults                 | dirty, reset, read                             | sim, hw  |
| PROT-001 | Bad request CRC → BAD_CRC, ERR_COUNT increments         | corrupt CRC byte                               | sim, hw  |
| PROT-002 | Unknown CMD → BAD_CMD                                   | CMD 0x7E                                       | sim, hw  |
| PROT-003 | Wrong LEN for CMD → BAD_LEN                             | 3 malformed lengths                            | sim, hw  |
| PROT-004 | DUT resyncs on SOF after line noise                     | garbage prefix before a valid frame            | sim, hw  |
| PROT-005 | Partial frame discarded after inter-byte gap            | 3 bytes, silence, then a valid frame           | sim, hw  |
| PROT-006 | LEN > 4 → no response, ERR_COUNT increments             | LEN = 5, 0x20, 0xFF                            | sim, hw  |
| GPIO-001 | STATUS.LOOP_IN follows CTRL.LOOP_OUT (jumper fitted)    | toggle 0/1/0/1                                 | sim, hw  |
| GPIO-002 | Open loopback does not follow output                    | model with jumper removed                      | sim only |
| ADC-001  | ADC value within 0..1023                                | 20 samples                                     | sim, hw  |
| ADC-002  | ADC_H bits 7..2 read 0                                  | read after latch                               | sim, hw  |
| ADC-003  | ADC_L read latches ADC_H (coherent 10-bit sample)       | ADC changes between byte reads                 | sim only |

## Fault injection (link robustness)

Faults are injected by `FaultyTransport` (src/val01/faults.py) between client and DUT.

| ID     | Requirement                                                        | Method                                               |
|--------|--------------------------------------------------------------------|------------------------------------------------------|
| FI-001 | Every single link fault is detected when retries=0                 | 4 fault types × 10 seeds, expect an exception        |
| FI-002 | A single fault is recovered with retries=1                         | per fault type, expect a correct value in 2 attempts |
| FI-003 | Retries exhausted → exception, not a value                         | 3 drops with retries=2                               |
| FI-004 | Real DUT errors (e.g. BAD_ADDR) are not retried                    | invalid address with retries=3                       |
| FI-005 | Soak: zero silent corruption, ≥99% completion                      | 2000 random ops, 20% fault rate, retries=3           |
| FI-006 | Late/stale response is not consumed by the next transaction        | unread response in RX buffer                         |

Expected give-up rate in FI-005 is about p^(r+1) = 0.2^4 = 0.16%, or about 3 of 2000.

### Defect found by fault injection

**DEF-001 — DUT answered BAD_LEN to a corrupted frame.** A single bit flip in LEN
(0x00 → 0x20) made the DUT answer `BAD_LEN` before checking the CRC. The host
received what looked like a legitimate rejection and did not retry. In soak,
14 of 16 failures traced back to this.
Found by FI-001 (seed 5, flip_req) and the soak-count mismatch.
Fix: oversize-LEN frames are dropped silently and counted (PROT-006). The soak now
fails on any non-link DUT status, so this class of defect cannot come back unnoticed.

## Planned (next steps)

- HW target: SerialTransport, Arduino firmware, ADC limits with a known reference (e.g. a voltage divider).
