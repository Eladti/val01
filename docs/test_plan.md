# VAL01 Test Plan — v0.1

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
| GPIO-001 | STATUS.LOOP_IN follows CTRL.LOOP_OUT (jumper fitted)    | toggle 0/1/0/1                                 | sim, hw  |
| GPIO-002 | Open loopback does not follow output                    | model with jumper removed                      | sim only |
| ADC-001  | ADC value within 0..1023                                | 20 samples                                     | sim, hw  |
| ADC-002  | ADC_H bits 7..2 read 0                                  | read after latch                               | sim, hw  |
| ADC-003  | ADC_L read latches ADC_H (coherent 10-bit sample)       | ADC changes between byte reads                 | sim only |

## Planned (next steps)

- Fault injection on the link: bit flips, dropped/truncated responses, delays → host detects every one of them and never accepts a corrupted value.
- Timeout/retry policy in the client.
- HW target: SerialTransport, Arduino firmware, ADC limits with a known reference (e.g. a voltage divider).
