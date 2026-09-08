#pragma once

#include <stdint.h>

namespace simple_kvm::audio {

struct SyncTuple {
  uint32_t boot_nonce;
  uint32_t request_id;
};

enum class SyncResult : uint8_t {
  kAcceptedNew = 0,
  kDuplicate,
};

enum class EndResult : uint8_t {
  kEnded = 0,
  kDuplicate,
  kStale,
};

class SourceSessionState {
 public:
  SourceSessionState();
  void reset();
  SyncResult accept_sync(const SyncTuple& sync);
  bool start_source(uint32_t boot_nonce, uint16_t session_counter);
  bool end_source(uint32_t boot_nonce, uint16_t session_counter);
  EndResult end_source_result(uint32_t boot_nonce, uint16_t session_counter);
  bool matches(uint32_t boot_nonce, uint16_t session_counter) const;
  void timeout();
  // A transport gap can make the receiver time out while the source remains
  // in alt=1. The next frame from that same authenticated session may resume
  // the stream, but an explicitly ended session must remain stale.
  bool timed_out() const { return timed_out_; }

  bool synced() const { return synced_; }
  bool active() const { return active_; }
  uint32_t clear_count() const { return clear_count_; }
  uint32_t boot_nonce() const { return boot_nonce_; }
  uint16_t session_counter() const { return session_counter_; }

 private:
  bool synced_;
  bool active_;
  SyncTuple sync_;
  uint32_t boot_nonce_;
  uint16_t session_counter_;
  uint32_t clear_count_;
  bool timed_out_;
  bool last_end_valid_;
  uint32_t last_end_boot_nonce_;
  uint16_t last_end_session_counter_;
};

enum class RunMarker : uint8_t {
  kStart = 1,
  kEnd = 2,
};

struct RunSnapshot {
  uint32_t run_id;
  RunMarker marker;
  uint16_t marker_sequence;
  uint32_t usb_audio_boundary;
  uint32_t spi_pcm_frames;
  uint32_t accepted_pcm_frames;
  uint32_t error_count;
  uint16_t session_counter;
  uint8_t audio_alt;
};

enum class RunRecordResult : uint8_t {
  kCreated = 0,
  kDuplicate,
  kConflict,
};

class RunSnapshotStore {
 public:
  RunSnapshotStore();
  void clear();
  RunRecordResult record(const RunSnapshot& snapshot);
  const RunSnapshot* find(uint32_t run_id, RunMarker marker) const;

 private:
  static constexpr uint8_t kCapacity = 8U;  // four runs, start and end
  RunSnapshot snapshots_[kCapacity];
  bool used_[kCapacity];
  uint8_t next_replace_;
};

}  // namespace simple_kvm::audio
