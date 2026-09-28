# Hardware setup (target `hw`)

> **Status:** the firmware passes the full `fw` suite, which runs it compiled for the
> host in CI. It has **not yet been run on a physical board**. This page is the
> bring-up procedure for that first run.

## Board and wiring

Arduino Uno or Nano (ATmega328P).

| Connection            | Purpose                                            | Test IDs           |
|-----------------------|----------------------------------------------------|--------------------|
| Jumper **D7 ↔ D8**    | GPIO loopback: D7 = LOOP_OUT, D8 = LOOP_IN (pull-up) | GPIO-001, GPIO-002 |
| A0 (optional)         | ADC input; floating is fine for the range tests    | ADC-001, ADC-002   |
| USB                   | power + serial link (115200 8N1)                   | all                |

With the jumper fitted, run everything except GPIO-002. GPIO-002 needs the jumper
**removed** (see below).

## Flash the firmware

1. Open `firmware/val01_dut/val01_dut.ino` in the Arduino IDE.
2. Tools → Board: *Arduino Uno* (or *Nano*; for many clones, also set
   Tools → Processor → *ATmega328P (Old Bootloader)*).
3. Tools → Port: pick the board, then Upload.
4. **Close the Serial Monitor.** Only one program can hold the port at a time.

## Find the port and get permission (Linux)

```bash
ls /dev/ttyACM* /dev/ttyUSB*        # genuine Uno: ttyACM0 · CH340 clones: ttyUSB0
sudo usermod -aG dialout $USER      # once; then log out and back in
```

## Run

```bash
pip install -e ".[dev,hw]"
pytest --target hw --port /dev/ttyACM0 --report
```

Opening the port resets the board (DTR). The transport waits 2 s for the
bootloader, then flushes the input, so the first test starts clean.

GPIO-002 (jumper removed):

```bash
# pull the D7-D8 jumper, then:
pytest --target hw --port /dev/ttyACM0 -k loopback_open --jumper-removed
```

Without `--jumper-removed`, GPIO-002 skips on `hw`. The software can't tell
whether the jumper is physically there, so the operator has to state it.

## What differs from `fw`

| Aspect          | `fw` (host)                  | `hw` (board)                             |
|-----------------|------------------------------|------------------------------------------|
| Link            | pseudo-terminal, ~no latency | USB-UART, real latency and buffering     |
| ADC             | 512 ± 3 synthetic            | real analog input on A0                  |
| Clock           | host `CLOCK_MONOTONIC`       | `millis()` from Timer0                   |
| `int` width     | 32-bit                       | **16-bit** (the code avoids depending on it) |
| Compiler        | host g++ -Werror             | avr-gcc via Arduino IDE (first compile happens here) |

Anything that fails on `hw` but passes on `fw` points at one of these rows.
