#include "audio_ring.h"

#include <string.h>

namespace simple_kvm::audio {

AudioRing::AudioRing() : samples_{}, head_(0U), tail_(0U), count_(0U) {}

void AudioRing::clear()
{
  head_ = 0U;
  tail_ = 0U;
  count_ = 0U;
}

bool AudioRing::push_one(int16_t sample)
{
  if (full()) {
    return false;
  }
  samples_[head_] = sample;
  head_ = static_cast<uint16_t>((head_ + 1U) & (kRingCapacity - 1U));
  ++count_;
  return true;
}

uint16_t AudioRing::push(const int16_t* samples, uint16_t count)
{
  if (samples == nullptr) {
    return 0U;
  }
  uint16_t written = 0U;
  while (written < count && push_one(samples[written])) {
    ++written;
  }
  return written;
}

uint16_t AudioRing::discard(uint16_t count)
{
  const uint16_t discarded = count < count_ ? count : count_;
  tail_ = static_cast<uint16_t>(
      (tail_ + discarded) & static_cast<uint16_t>(kRingCapacity - 1U));
  count_ = static_cast<uint16_t>(count_ - discarded);
  return discarded;
}

int16_t AudioRing::peek(uint16_t offset) const
{
  if (offset >= count_) {
    return 0;
  }
  const uint16_t index = static_cast<uint16_t>(
      (tail_ + offset) & static_cast<uint16_t>(kRingCapacity - 1U));
  return samples_[index];
}

}  // namespace simple_kvm::audio
