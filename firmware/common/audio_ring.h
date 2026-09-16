#pragma once

#include <stddef.h>
#include <stdint.h>

#include "audio_format.h"

namespace simple_kvm::audio {

class AudioRing {
 public:
  AudioRing();

  void clear();
  bool push_one(int16_t sample);
  uint16_t push(const int16_t* samples, uint16_t count);
  uint16_t discard(uint16_t count);
  int16_t peek(uint16_t offset) const;

  // Producer and consumer own separate monotonic cursors.  The cursors are
  // 16-bit and the ring is 1024 samples, so unsigned subtraction remains
  // correct across cursor wrap while avoiding a racy shared count update
  // between the SPI main loop and the USB interrupt.
  uint16_t fill() const {
    return static_cast<uint16_t>(head_ - tail_);
  }
  bool empty() const { return fill() == 0U; }
  bool full() const { return fill() == kRingCapacity; }
  uint16_t free_space() const {
    return static_cast<uint16_t>(kRingCapacity - fill());
  }

 private:
  int16_t samples_[kRingCapacity];
  volatile uint16_t head_;
  volatile uint16_t tail_;
};

}  // namespace simple_kvm::audio
