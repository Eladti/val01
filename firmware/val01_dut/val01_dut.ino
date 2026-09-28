// VAL01 DUT firmware. Implements docs/protocol.md (v0.3).
//
// Target: Arduino Uno / Nano (ATmega328P). The same source is also compiled
// for the host by firmware/host (the `fw` pytest target), so it may only use
// the Arduino API subset provided by firmware/host/Arduino.h.
//
// AVR note: int is 16-bit on this MCU. All protocol values use explicit
// uint8_t/uint16_t types, and time comparisons use unsigned subtraction
// (rollover-safe).
//
// Wiring:
//   D7 (LOOP_OUT) ──jumper── D8 (LOOP_IN, internal pull-up)
//   A0            ADC input (optional voltage divider for a known level)
//   LED_BUILTIN   CTRL.bit0

const uint8_t SOF_REQ = 0xA5;
const uint8_t SOF_RSP = 0x5A;
const uint8_t HEADER_LEN = 4;
const uint8_t MAX_PAYLOAD = 4;
const unsigned long INTER_BYTE_TIMEOUT_MS = 20;

enum Cmd : uint8_t { CMD_READ = 0x01, CMD_WRITE = 0x02, CMD_RESET = 0x03 };
enum Status : uint8_t {
  ST_OK = 0x00, ST_BAD_CRC = 0x01, ST_BAD_CMD = 0x02,
  ST_BAD_ADDR = 0x03, ST_READ_ONLY = 0x04, ST_BAD_LEN = 0x05
};
enum Reg : uint8_t {
  R_ID = 0x00, R_FW_VERSION = 0x01, R_SCRATCH = 0x02, R_CTRL = 0x03,
  R_STATUS = 0x04, R_ADC_L = 0x05, R_ADC_H = 0x06, R_ERR_COUNT = 0x07,
  NUM_REGS = 0x08
};

const uint8_t DEVICE_ID = 0xA7;
const uint8_t FW_VERSION = 0x01;
const uint8_t CTRL_LED = 1 << 0;
const uint8_t CTRL_LOOP_OUT = 1 << 1;

const uint8_t PIN_LOOP_OUT = 7;
const uint8_t PIN_LOOP_IN = 8;

// ---- state ------------------------------------------------------------
uint8_t regScratch, regCtrl, regErrCount, adcHighLatch;
uint8_t rxBuf[HEADER_LEN + MAX_PAYLOAD + 1];
uint8_t rxLen = 0;
unsigned long lastByteMs = 0;

// ---- helpers ----------------------------------------------------------
uint8_t crc8(const uint8_t *data, uint8_t n) {  // CRC-8/SMBUS
  uint8_t crc = 0x00;
  for (uint8_t i = 0; i < n; i++) {
    crc ^= data[i];
    for (uint8_t b = 0; b < 8; b++) {
      crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
    }
  }
  return crc;
}

void applyCtrl() {
  digitalWrite(LED_BUILTIN, (regCtrl & CTRL_LED) ? HIGH : LOW);
  digitalWrite(PIN_LOOP_OUT, (regCtrl & CTRL_LOOP_OUT) ? HIGH : LOW);
}

void resetRegisters() {
  regScratch = 0x00;
  regCtrl = 0x00;
  regErrCount = 0x00;
  adcHighLatch = 0x00;
  applyCtrl();
}

void countError() {
  if (regErrCount < 0xFF) regErrCount++;
}

void sendResponse(uint8_t status, uint8_t addr, const uint8_t *payload, uint8_t len) {
  uint8_t frame[HEADER_LEN + MAX_PAYLOAD + 1];
  frame[0] = SOF_RSP;
  frame[1] = status;
  frame[2] = addr;
  frame[3] = len;
  for (uint8_t i = 0; i < len; i++) frame[HEADER_LEN + i] = payload[i];
  frame[HEADER_LEN + len] = crc8(frame + 1, 3 + len);
  Serial.write(frame, HEADER_LEN + len + 1);
}

bool isWritable(uint8_t addr) {
  return addr == R_SCRATCH || addr == R_CTRL;
}

uint8_t readRegister(uint8_t addr) {
  switch (addr) {
    case R_ID:         return DEVICE_ID;
    case R_FW_VERSION: return FW_VERSION;
    case R_SCRATCH:    return regScratch;
    case R_CTRL:       return regCtrl;
    case R_STATUS:     return digitalRead(PIN_LOOP_IN) == HIGH ? 0x01 : 0x00;
    case R_ADC_L: {
      uint16_t sample = (uint16_t)analogRead(A0) & 0x03FF;
      adcHighLatch = (uint8_t)(sample >> 8);  // latch high bits on low-byte read
      return (uint8_t)(sample & 0xFF);
    }
    case R_ADC_H:      return adcHighLatch;
    case R_ERR_COUNT:  return regErrCount;
    default:           return 0x00;  // unreachable: caller checks the address
  }
}

// ---- frame handling ---------------------------------------------------
void handleFrame() {
  uint8_t cmd = rxBuf[1];
  uint8_t addr = rxBuf[2];
  uint8_t len = rxBuf[3];

  if (crc8(rxBuf + 1, 3 + len) != rxBuf[HEADER_LEN + len]) {
    countError();
    sendResponse(ST_BAD_CRC, addr, 0, 0);
    return;
  }

  if (cmd == CMD_RESET) {
    if (len != 0) { sendResponse(ST_BAD_LEN, addr, 0, 0); return; }
    resetRegisters();
    sendResponse(ST_OK, addr, 0, 0);
    return;
  }
  if (cmd != CMD_READ && cmd != CMD_WRITE) { sendResponse(ST_BAD_CMD, addr, 0, 0); return; }
  if (addr >= NUM_REGS) { sendResponse(ST_BAD_ADDR, addr, 0, 0); return; }

  if (cmd == CMD_READ) {
    if (len != 0) { sendResponse(ST_BAD_LEN, addr, 0, 0); return; }
    uint8_t value = readRegister(addr);
    sendResponse(ST_OK, addr, &value, 1);
    return;
  }

  // CMD_WRITE
  if (len != 1) { sendResponse(ST_BAD_LEN, addr, 0, 0); return; }
  if (!isWritable(addr)) { sendResponse(ST_READ_ONLY, addr, 0, 0); return; }
  if (addr == R_SCRATCH) regScratch = rxBuf[HEADER_LEN];
  if (addr == R_CTRL) { regCtrl = rxBuf[HEADER_LEN]; applyCtrl(); }
  sendResponse(ST_OK, addr, 0, 0);
}

void receiveByte(uint8_t b) {
  unsigned long now = millis();
  if (rxLen > 0 && (unsigned long)(now - lastByteMs) > INTER_BYTE_TIMEOUT_MS) {
    rxLen = 0;  // inter-byte timeout: drop the stale partial frame
  }
  lastByteMs = now;

  if (rxLen == 0 && b != SOF_REQ) return;  // hunt for start-of-frame
  rxBuf[rxLen++] = b;

  if (rxLen >= HEADER_LEN) {
    uint8_t len = rxBuf[3];
    if (len > MAX_PAYLOAD) {  // CRC position unknown: drop silently (spec: DEF-001)
      countError();
      rxLen = 0;
      return;
    }
    if (rxLen == HEADER_LEN + len + 1) {
      handleFrame();
      rxLen = 0;
    }
  }
}

// ---- Arduino entry points ---------------------------------------------
void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(PIN_LOOP_OUT, OUTPUT);
  pinMode(PIN_LOOP_IN, INPUT_PULLUP);
  resetRegisters();
}

void loop() {
  while (Serial.available() > 0) {
    receiveByte((uint8_t)Serial.read());
  }
}
