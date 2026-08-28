#pragma once

#include <stddef.h>
#include <stdint.h>

#include "audio_session.h"

namespace simple_kvm::audio {

constexpr uint8_t kBootHidQueueSlots = 32U;
constexpr uint8_t kBootHidFrameBytes = 20U;
constexpr uint32_t kBootBarrierMs = 60U;
constexpr uint32_t kSyncRetryMs = 100U;

struct BootHidSlot {
  uint32_t metadata;  // high byte: length, low 24 bits: acceptance time in ms
  uint8_t frame[kBootHidFrameBytes];
};

static_assert(sizeof(BootHidSlot) == 24U,
              "boot HID queue slot must remain exactly 24 bytes");

class BootHidQueue {
 public:
  BootHidQueue();
  void clear();
  bool push(const uint8_t* frame, uint8_t length, uint32_t accepted_ms);
  bool pop(uint8_t* frame, uint8_t& length, uint32_t& accepted_ms);

  uint8_t fill() const { return count_; }
  uint8_t high_water() const { return high_water_; }
  uint32_t overflow_count() const { return overflow_count_; }

 private:
  BootHidSlot slots_[kBootHidQueueSlots];
  uint8_t head_;
  uint8_t tail_;
  uint8_t count_;
  uint8_t high_water_;
  uint32_t overflow_count_;
};

static_assert(sizeof(BootHidSlot) * kBootHidQueueSlots == 768U,
              "boot HID queue budget is fixed at 768 bytes");

class SyncRetryState {
 public:
  SyncRetryState();
  void begin(uint32_t now_ms, const SyncTuple& tuple);
  bool barrier_active(uint32_t now_ms) const;
  bool should_send(uint32_t now_ms) const;
  void mark_sent(uint32_t now_ms);
  bool ack(const SyncTuple& tuple);

  const SyncTuple& tuple() const { return tuple_; }
  bool acked() const { return acked_; }
  uint32_t send_count() const { return send_count_; }

 private:
  SyncTuple tuple_;
  uint32_t barrier_deadline_ms_;
  uint32_t retry_deadline_ms_;
  uint32_t send_count_;
  bool started_;
  bool sent_;
  bool acked_;
};

}  // namespace simple_kvm::audio
