// Host build of the DUT firmware: shim + the unmodified sketch + a main loop.
#include "Arduino.h"

namespace shim {
uint8_t pinLevel[NUM_PINS];
uint8_t pinModeOf[NUM_PINS];
bool jumperFitted = true;
}  // namespace shim

HostSerial Serial;

#include "../val01_dut/val01_dut.ino"

int main() {
  const char *jumper = getenv("VAL01_JUMPER");
  shim::jumperFitted = !(jumper && strcmp(jumper, "0") == 0);
  setup();
  for (;;) loop();
}
