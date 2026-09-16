#pragma once

#include <stddef.h>
#include <stdint.h>

#include "audio_asrc.h"
#include "audio_diag.h"
#include "audio_frame.h"
#include "audio_session.h"

namespace simple_kvm::audio {

class AudioReceivePipeline {
 public:
  AudioReceivePipeline();

  SyncResult accept_sync(const SyncTuple& sync);
  bool accept_session_end(uint32_t boot_nonce, uint16_t session_counter);
  void set_capture_alt(uint8_t alt);
  bool process_frame(const uint8_t* data, size_t length, uint32_t now_ms);
  bool source_timeout(uint32_t now_ms);
  void note_short_transfer();
  void note_overrun();
  void note_usb_mic_packet(uint16_t bytes);
  void update_uptime(uint32_t uptime_ms);
  void note_usb_state(uint8_t state, uint8_t default_state,
                      uint8_t suspended_state);
  void note_hid_result(uint8_t interface_index, bool busy, bool dropped);
  void set_reset_reason(ResetReason reason);
  RenderResult render(int16_t* output, size_t count);
  AudioStatus status() const;

  const Bp2Diagnostics& diagnostics() const { return diagnostics_; }
  const RunSnapshotStore& run_snapshots() const { return run_snapshots_; }
  bool source_active() const { return source_session_.matches(
      diagnostics_.source_boot_nonce,
      diagnostics_.source_session_counter); }

#ifdef AUDIO_TEST_HOOKS
  AudioRing& test_ring() { return ring_; }
  AudioAsrc& test_asrc() { return asrc_; }
#endif

 private:
  void clear_stream(bool source_clear);
  void refresh_ring_metrics();
  uint32_t error_count() const;

  SourceSessionState source_session_;
  SequenceTracker sequence_;
  AudioRing ring_;
  AudioAsrc asrc_;
  RunSnapshotStore run_snapshots_;
  Bp2Diagnostics diagnostics_;
  uint32_t last_source_ms_;
  uint32_t asrc_clamp_accumulated_;
  uint32_t prefill_accumulated_;
  uint8_t last_usb_state_;
  bool have_source_time_;
  // A session-start control frame is allowed a startup grace period.  The
  // 3 ms source watchdog starts only after the first valid PCM frame, so a
  // host that takes a few milliseconds to deliver its first USB packet does
  // not permanently invalidate the otherwise valid session.
  bool have_source_pcm_;
  bool have_usb_state_;
};

}  // namespace simple_kvm::audio
