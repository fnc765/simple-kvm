#include "audio_session.h"

#include <string.h>

namespace simple_kvm::audio {
namespace {

bool same_sync(const SyncTuple& left, const SyncTuple& right)
{
  return left.boot_nonce == right.boot_nonce &&
         left.request_id == right.request_id;
}

bool same_snapshot(const RunSnapshot& left, const RunSnapshot& right)
{
  return left.run_id == right.run_id && left.marker == right.marker &&
         left.marker_sequence == right.marker_sequence &&
         left.usb_audio_boundary == right.usb_audio_boundary &&
         left.spi_pcm_frames == right.spi_pcm_frames &&
         left.accepted_pcm_frames == right.accepted_pcm_frames &&
         left.error_count == right.error_count &&
         left.session_counter == right.session_counter &&
         left.audio_alt == right.audio_alt;
}

}  // namespace

SourceSessionState::SourceSessionState() { reset(); }

void SourceSessionState::reset()
{
  synced_ = false;
  active_ = false;
  sync_ = SyncTuple{};
  boot_nonce_ = 0U;
  session_counter_ = 0U;
  clear_count_ = 0U;
  last_end_valid_ = false;
  last_end_boot_nonce_ = 0U;
  last_end_session_counter_ = 0U;
}

SyncResult SourceSessionState::accept_sync(const SyncTuple& sync)
{
  if (synced_ && same_sync(sync_, sync)) {
    return SyncResult::kDuplicate;
  }
  synced_ = true;
  active_ = false;
  sync_ = sync;
  boot_nonce_ = sync.boot_nonce;
  session_counter_ = 0U;
  last_end_valid_ = false;
  ++clear_count_;
  return SyncResult::kAcceptedNew;
}

bool SourceSessionState::start_source(uint32_t boot_nonce,
                                      uint16_t session_counter)
{
  if (!synced_ || boot_nonce != sync_.boot_nonce) {
    return false;
  }
  if (!active_ || boot_nonce_ != boot_nonce ||
      session_counter_ != session_counter) {
    active_ = true;
    boot_nonce_ = boot_nonce;
    session_counter_ = session_counter;
    ++clear_count_;
    last_end_valid_ = false;
  }
  return true;
}

bool SourceSessionState::end_source(uint32_t boot_nonce,
                                    uint16_t session_counter)
{
  return end_source_result(boot_nonce, session_counter) != EndResult::kStale;
}

EndResult SourceSessionState::end_source_result(uint32_t boot_nonce,
                                                uint16_t session_counter)
{
  if (matches(boot_nonce, session_counter)) {
    active_ = false;
    last_end_valid_ = true;
    last_end_boot_nonce_ = boot_nonce;
    last_end_session_counter_ = session_counter;
    ++clear_count_;
    return EndResult::kEnded;
  }
  if (!active_ && last_end_valid_ && last_end_boot_nonce_ == boot_nonce &&
      last_end_session_counter_ == session_counter) {
    return EndResult::kDuplicate;
  }
  return EndResult::kStale;
}

bool SourceSessionState::matches(uint32_t boot_nonce,
                                 uint16_t session_counter) const
{
  return active_ && boot_nonce_ == boot_nonce &&
         session_counter_ == session_counter;
}

void SourceSessionState::timeout()
{
  if (active_) {
    active_ = false;
    ++clear_count_;
  }
}

RunSnapshotStore::RunSnapshotStore() { clear(); }

void RunSnapshotStore::clear()
{
  memset(snapshots_, 0, sizeof(snapshots_));
  memset(used_, 0, sizeof(used_));
  next_replace_ = 0U;
}

RunRecordResult RunSnapshotStore::record(const RunSnapshot& snapshot)
{
  for (uint8_t i = 0U; i < kCapacity; ++i) {
    if (used_[i] && snapshots_[i].run_id == snapshot.run_id &&
        snapshots_[i].marker == snapshot.marker) {
      return same_snapshot(snapshots_[i], snapshot)
                 ? RunRecordResult::kDuplicate
                 : RunRecordResult::kConflict;
    }
  }
  snapshots_[next_replace_] = snapshot;
  used_[next_replace_] = true;
  next_replace_ = static_cast<uint8_t>((next_replace_ + 1U) % kCapacity);
  return RunRecordResult::kCreated;
}

const RunSnapshot* RunSnapshotStore::find(uint32_t run_id,
                                          RunMarker marker) const
{
  for (uint8_t i = 0U; i < kCapacity; ++i) {
    if (used_[i] && snapshots_[i].run_id == run_id &&
        snapshots_[i].marker == marker) {
      return &snapshots_[i];
    }
  }
  return nullptr;
}

}  // namespace simple_kvm::audio
