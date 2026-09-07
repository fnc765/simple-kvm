#include "audio_ring.h"

#include <string.h>

namespace simple_kvm::audio {

AudioRing::AudioRing() : samples_{}, head_(0U), tail_(0U) {}

void AudioRing::clear()
{
  head_ = 0U;
  tail_ = 0U;
}

bool AudioRing::push_one(int16_t sample)
{
  if (full()) {
    return false;
  }
  samples_[static_cast<uint16_t>(head_ & (kRingCapacity - 1U))] = sample;
  head_ = static_cast<uint16_t>(head_ + 1U);
  return true;
}

uint16_t AudioRing::push(const int16_t* samples, uint16_t count)
{
  if (samples == nullptr) {
    return 0U;
  }
  const uint16_t available = free_space();
  const uint16_t written = count < available ? count : available;
  const uint16_t start = head_;
  for (uint16_t i = 0U; i < written; ++i) {
    const uint16_t index = static_cast<uint16_t>(
        (start + i) & static_cast<uint16_t>(kRingCapacity - 1U));
    samples_[index] = samples[i];
  }
  // Publish the new head only after all samples are visible to the consumer.
  head_ = static_cast<uint16_t>(start + written);
  return written;
}

uint16_t AudioRing::discard(uint16_t count)
{
  const uint16_t available = fill();
  const uint16_t discarded = count < available ? count : available;
  tail_ = static_cast<uint16_t>(tail_ + discarded);
  return discarded;
}

int16_t AudioRing::peek(uint16_t offset) const
{
  if (offset >= fill()) {
    return 0;
  }
  const uint16_t index = static_cast<uint16_t>(
      (tail_ + offset) & static_cast<uint16_t>(kRingCapacity - 1U));
  return samples_[index];
}

}  // namespace simple_kvm::audio
