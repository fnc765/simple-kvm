#include "audio_control.h"

#include <string.h>

namespace simple_kvm::audio {
namespace {

bool deadline_reached(uint32_t now_ms, uint32_t deadline_ms)
{
  return static_cast<int32_t>(now_ms - deadline_ms) >= 0;
}

bool same_tuple(const SyncTuple& left, const SyncTuple& right)
{
  return left.boot_nonce == right.boot_nonce &&
         left.request_id == right.request_id;
}

}  // namespace

BootHidQueue::BootHidQueue() { clear(); }

void BootHidQueue::clear()
{
  memset(slots_, 0, sizeof(slots_));
  head_ = 0U;
  tail_ = 0U;
  count_ = 0U;
  high_water_ = 0U;
  overflow_count_ = 0U;
}

bool BootHidQueue::push(const uint8_t* frame, uint8_t length,
                        uint32_t accepted_ms)
{
  if (frame == nullptr || length == 0U || length > kBootHidFrameBytes) {
    return false;
  }
  if (count_ == kBootHidQueueSlots) {
    ++overflow_count_;
    return false;
  }
  BootHidSlot& slot = slots_[head_];
  slot.metadata = (static_cast<uint32_t>(length) << 24U) |
                  (accepted_ms & 0x00FFFFFFUL);
  memset(slot.frame, 0, sizeof(slot.frame));
  memcpy(slot.frame, frame, length);
  head_ = static_cast<uint8_t>((head_ + 1U) % kBootHidQueueSlots);
  ++count_;
  if (count_ > high_water_) {
    high_water_ = count_;
  }
  return true;
}

bool BootHidQueue::pop(uint8_t* frame, uint8_t& length,
                       uint32_t& accepted_ms)
{
  if (frame == nullptr || count_ == 0U) {
    return false;
  }
  const BootHidSlot& slot = slots_[tail_];
  length = static_cast<uint8_t>(slot.metadata >> 24U);
  accepted_ms = slot.metadata & 0x00FFFFFFUL;
  memcpy(frame, slot.frame, length);
  tail_ = static_cast<uint8_t>((tail_ + 1U) % kBootHidQueueSlots);
  --count_;
  return true;
}

SyncRetryState::SyncRetryState()
    : tuple_{}, barrier_deadline_ms_(0U), retry_deadline_ms_(0U),
      send_count_(0U), started_(false), sent_(false), acked_(false) {}

void SyncRetryState::begin(uint32_t now_ms, const SyncTuple& tuple)
{
  tuple_ = tuple;
  barrier_deadline_ms_ = now_ms + kBootBarrierMs;
  retry_deadline_ms_ = barrier_deadline_ms_;
  send_count_ = 0U;
  started_ = true;
  sent_ = false;
  acked_ = false;
}

bool SyncRetryState::barrier_active(uint32_t now_ms) const
{
  return started_ && !deadline_reached(now_ms, barrier_deadline_ms_);
}

bool SyncRetryState::should_send(uint32_t now_ms) const
{
  return started_ && !acked_ && !barrier_active(now_ms) &&
         (!sent_ || deadline_reached(now_ms, retry_deadline_ms_));
}

void SyncRetryState::mark_sent(uint32_t now_ms)
{
  sent_ = true;
  retry_deadline_ms_ = now_ms + kSyncRetryMs;
  ++send_count_;
}

bool SyncRetryState::ack(const SyncTuple& tuple)
{
  if (!started_ || !same_tuple(tuple_, tuple)) {
    return false;
  }
  acked_ = true;
  return true;
}

}  // namespace simple_kvm::audio
