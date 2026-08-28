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

  uint16_t fill() const { return count_; }
  bool empty() const { return count_ == 0U; }
  bool full() const { return count_ == kRingCapacity; }
  uint16_t free_space() const {
    return static_cast<uint16_t>(kRingCapacity - count_);
  }

 private:
  int16_t samples_[kRingCapacity];
  uint16_t head_;
  uint16_t tail_;
  uint16_t count_;
};

}  // namespace simple_kvm::audio
