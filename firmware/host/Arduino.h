// Minimal Arduino API shim so the DUT sketch compiles and runs on a Linux host.
//
// Serial is mapped to fd 0 (read) and fd 1 (write). The test harness
// connects both to a pseudo-terminal, so the host-side SerialTransport
// talks to this process exactly as it would talk to a board over USB.
//
// Pin model: the LOOP_OUT → LOOP_IN jumper is present unless VAL01_JUMPER=0.
// Without it, LOOP_IN reads HIGH (internal pull-up), same as the board.
#pragma once

#include <poll.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define HIGH 0x1
#define LOW 0x0
#define INPUT 0x0
#define OUTPUT 0x1
#define INPUT_PULLUP 0x2
#define LED_BUILTIN 13
#define A0 14

namespace shim {
const uint8_t NUM_PINS = 20;
extern uint8_t pinLevel[NUM_PINS];
extern uint8_t pinModeOf[NUM_PINS];
extern bool jumperFitted;
const uint8_t LOOP_OUT = 7, LOOP_IN = 8;
}  // namespace shim

inline unsigned long millis() {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (unsigned long)(ts.tv_sec * 1000UL + ts.tv_nsec / 1000000UL);
}

inline void delay(unsigned long ms) { usleep(ms * 1000UL); }

inline void pinMode(uint8_t pin, uint8_t mode) {
  if (pin < shim::NUM_PINS) shim::pinModeOf[pin] = mode;
}

inline void digitalWrite(uint8_t pin, uint8_t val) {
  if (pin < shim::NUM_PINS) shim::pinLevel[pin] = val ? HIGH : LOW;
}

inline int digitalRead(uint8_t pin) {
  if (pin == shim::LOOP_IN && shim::jumperFitted) return shim::pinLevel[shim::LOOP_OUT];
  if (pin < shim::NUM_PINS && shim::pinModeOf[pin] == INPUT_PULLUP) return HIGH;
  return pin < shim::NUM_PINS ? shim::pinLevel[pin] : LOW;
}

inline int analogRead(uint8_t) {
  return 512 + (rand() % 7) - 3;  // mid-scale with a little noise
}

class HostSerial {
 public:
  void begin(unsigned long) {}

  int available() {
    if (head_ == tail_) fill();
    return tail_ - head_;
  }

  int read() {
    if (available() <= 0) return -1;
    return buf_[head_++];
  }

  size_t write(const uint8_t *data, size_t n) {
    size_t done = 0;
    while (done < n) {
      ssize_t w = ::write(1, data + done, n - done);
      if (w <= 0) exit(0);
      done += (size_t)w;
    }
    return n;
  }

 private:
  void fill() {
    head_ = tail_ = 0;
    struct pollfd p = {0, POLLIN, 0};
    if (poll(&p, 1, 1) <= 0) return;  // wait up to 1 ms, keeps CPU idle
    if (p.revents & (POLLHUP | POLLERR)) exit(0);
    ssize_t r = ::read(0, buf_, sizeof(buf_));
    if (r <= 0) exit(0);  // harness closed the link
    tail_ = (int)r;
  }
  uint8_t buf_[64];
  int head_ = 0, tail_ = 0;
};

extern HostSerial Serial;
