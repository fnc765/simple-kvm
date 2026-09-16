#include "audio_pipeline.h"

#include <string.h>

namespace simple_kvm::audio {

AudioReceivePipeline::AudioReceivePipeline()
    : source_session_{}, sequence_{}, ring_{}, asrc_{}, run_snapshots_{},
      diagnostics_{}, last_source_ms_(0U), asrc_clamp_accumulated_(0U),
      prefill_accumulated_(0U), last_usb_state_(0U),
      have_source_time_(false), have_source_pcm_(false),
      have_usb_state_(false)
{
  diagnostics_.ring_min = kRingCapacity;
}

void AudioReceivePipeline::clear_stream(bool source_clear)
{
  asrc_clamp_accumulated_ += asrc_.clamp_count();
  prefill_accumulated_ += asrc_.prefill_count();
  ring_.clear();
  asrc_.reset();
  sequence_.reset();
  diagnostics_.ring_fill = 0U;
  if (source_clear) {
    ++diagnostics_.source_session_clears;
    have_source_pcm_ = false;
  }
}

SyncResult AudioReceivePipeline::accept_sync(const SyncTuple& sync)
{
  const SyncResult result = source_session_.accept_sync(sync);
  if (result == SyncResult::kAcceptedNew) {
    ++diagnostics_.control_sync_accepts;
    diagnostics_.source_boot_nonce = sync.boot_nonce;
    diagnostics_.source_session_counter = 0U;
    have_source_time_ = false;
    clear_stream(true);
  } else {
    ++diagnostics_.control_sync_duplicates;
  }
  return result;
}

bool AudioReceivePipeline::accept_session_end(uint32_t boot_nonce,
                                               uint16_t session_counter)
{
  const EndResult result =
      source_session_.end_source_result(boot_nonce, session_counter);
  if (result == EndResult::kStale) {
    ++diagnostics_.stale_session_controls;
    return false;
  }
  if (result == EndResult::kDuplicate) {
    return true;
  }
  ++diagnostics_.source_session_ends;
  have_source_time_ = false;
  clear_stream(true);
  return true;
}

void AudioReceivePipeline::set_capture_alt(uint8_t alt)
{
  alt = alt == 0U ? 0U : 1U;
  if (diagnostics_.capture_alt == alt) {
    return;
  }
  diagnostics_.capture_alt = alt;
  ++diagnostics_.capture_alt_transitions;
  if (alt == 1U) {
    ++diagnostics_.capture_session_starts;
  }
  ++diagnostics_.capture_session_clears;
  clear_stream(false);
}

uint32_t AudioReceivePipeline::error_count() const
{
  return diagnostics_.spi_magic_error + diagnostics_.spi_version_error +
         diagnostics_.spi_crc_error + diagnostics_.spi_sequence_gap +
         diagnostics_.spi_duplicate + diagnostics_.spi_short_transfer +
         diagnostics_.spi_overrun + diagnostics_.underflow +
         diagnostics_.overflow;
}

void AudioReceivePipeline::refresh_ring_metrics()
{
  diagnostics_.ring_fill = ring_.fill();
  if (diagnostics_.ring_fill < diagnostics_.ring_min) {
    diagnostics_.ring_min = diagnostics_.ring_fill;
  }
  if (diagnostics_.ring_fill > diagnostics_.ring_max) {
    diagnostics_.ring_max = diagnostics_.ring_fill;
  }
  diagnostics_.asrc_step_ppm = static_cast<int16_t>(asrc_.step_ppm());
  diagnostics_.asrc_integral = asrc_.integral_q16();
  diagnostics_.asrc_clamp_count =
      asrc_clamp_accumulated_ + asrc_.clamp_count();
  diagnostics_.prefill_count =
      prefill_accumulated_ + asrc_.prefill_count();
}

bool AudioReceivePipeline::process_frame(const uint8_t* data, size_t length,
                                         uint32_t now_ms)
{
  ++diagnostics_.spi_rx_frames;
  AudioFrame frame{};
  const AudioFrameError decode = decode_audio_frame(data, length, frame);
  if (decode != AudioFrameError::kOk) {
    switch (decode) {
      case AudioFrameError::kMagic: ++diagnostics_.spi_magic_error; break;
      case AudioFrameError::kVersion: ++diagnostics_.spi_version_error; break;
      case AudioFrameError::kCrc: ++diagnostics_.spi_crc_error; break;
      case AudioFrameError::kLength: ++diagnostics_.spi_short_transfer; break;
      default: ++diagnostics_.spi_version_error; break;
    }
    return false;
  }

  const bool source_changed = !source_session_.matches(
      frame.boot_nonce, frame.session_counter);
  const bool valid_pcm =
      (frame.flags & kFlagValid) != 0U &&
      frame.sample_count == kSamplesPerUsbFrame;
  if (source_changed) {
    // A receiver can reboot, or a short transport gap can trip the source
    // watchdog, while the source remains in alt=1. In either case the source
    // has no reason to emit another SESSION_START, but the next PCM frame
    // still carries the authenticated boot nonce and session counter. Re-arm
    // only a synced, timed-out session (or a newly observed session counter);
    // PCM from an explicitly ended session remains fail-closed.
    const bool recover_pcm_session =
        valid_pcm && source_session_.synced() && !source_session_.active() &&
        frame.boot_nonce == source_session_.boot_nonce() &&
        (source_session_.timed_out() ||
         frame.session_counter != source_session_.session_counter());
    const bool timed_out_same_session =
        valid_pcm && source_session_.synced() && !source_session_.active() &&
        source_session_.timed_out() &&
        frame.boot_nonce == source_session_.boot_nonce() &&
        frame.session_counter == source_session_.session_counter();
    if ((!recover_pcm_session &&
         (frame.flags & kFlagSessionStart) == 0U) ||
        !source_session_.start_source(frame.boot_nonce,
                                      frame.session_counter)) {
      ++diagnostics_.stale_session_controls;
      return false;
    }
    diagnostics_.source_boot_nonce = frame.boot_nonce;
    diagnostics_.source_session_counter = frame.session_counter;
    ++diagnostics_.source_session_starts;
    // A source watchdog trip can be caused by a transient scheduling gap
    // while the source remains in alt=1. Keep buffered PCM and ASRC phase for
    // that same authenticated session; a true source stop will drain the
    // ring and render() will fail closed through its normal underflow reset.
    // New sessions and explicit control transitions still clear/prefill.
    if (!timed_out_same_session) {
      clear_stream(true);
    }
  }

  const SequenceResult sequence_result = sequence_.observe(frame.sequence);
  if (sequence_result == SequenceResult::kDuplicate) {
    ++diagnostics_.spi_duplicate;
    return false;
  }
  if (sequence_result == SequenceResult::kGap) {
    ++diagnostics_.spi_sequence_gap;
  }
  if (valid_pcm) {
    have_source_pcm_ = true;
  }
  if (have_source_pcm_) {
    last_source_ms_ = now_ms;
    have_source_time_ = true;
  }

  if ((frame.flags & kFlagSessionStart) != 0U &&
      frame.sample_count == 0U) {
    ++diagnostics_.accepted_control_frames;
    return true;
  }

  if ((frame.flags & kFlagSessionEnd) != 0U ||
      (frame.flags & kFlagMute) != 0U) {
    ++diagnostics_.accepted_control_frames;
    (void)accept_session_end(frame.boot_nonce, frame.session_counter);
    return true;
  }

  if ((frame.flags & (kFlagRunStart | kFlagRunEnd)) != 0U) {
    ++diagnostics_.accepted_control_frames;
    RunSnapshot snapshot{};
    snapshot.run_id = get_run_id(frame);
    snapshot.marker = (frame.flags & kFlagRunStart) != 0U
                          ? RunMarker::kStart
                          : RunMarker::kEnd;
    snapshot.marker_sequence = frame.sequence;
    snapshot.accepted_pcm_frames = diagnostics_.accepted_pcm_frames;
    snapshot.error_count = error_count();
    snapshot.session_counter = frame.session_counter;
    snapshot.audio_alt = diagnostics_.capture_alt;
    (void)run_snapshots_.record(snapshot);
    return true;
  }

  if ((frame.flags & kFlagValid) == 0U ||
      frame.sample_count != kSamplesPerUsbFrame) {
    ++diagnostics_.spi_version_error;
    return false;
  }
  ++diagnostics_.accepted_pcm_frames;
  if (diagnostics_.capture_alt == 0U) {
    ++diagnostics_.discarded_capture_closed;
    return true;
  }
  if (ring_.push(frame.pcm, frame.sample_count) != frame.sample_count) {
    ++diagnostics_.overflow;
    clear_stream(false);
    return false;
  }
  refresh_ring_metrics();
  return true;
}

bool AudioReceivePipeline::source_timeout(uint32_t now_ms)
{
  if (!have_source_time_ ||
      static_cast<uint32_t>(now_ms - last_source_ms_) < 3U) {
    return false;
  }
  have_source_time_ = false;
  source_session_.timeout();
  ++diagnostics_.source_timeouts;
  // Do not discard the buffered tail on a short watchdog trip.  This avoids
  // an unnecessary prefill-sized silence when the authenticated source
  // resumes.  If the source is genuinely absent, the ring drains and
  // AudioAsrc::render() emits zeroes and resets itself at underflow.  Explicit
  // SESSION_END, MUTE, SYNC, and session changes still use clear_stream().
  return true;
}

void AudioReceivePipeline::note_short_transfer()
{
  ++diagnostics_.spi_short_transfer;
}

void AudioReceivePipeline::note_overrun()
{
  ++diagnostics_.spi_overrun;
}

void AudioReceivePipeline::note_usb_mic_packet(uint16_t bytes)
{
  ++diagnostics_.usb_mic_packets;
  diagnostics_.usb_mic_bytes += bytes;
}

void AudioReceivePipeline::update_uptime(uint32_t uptime_ms)
{
  diagnostics_.uptime_ms = uptime_ms;
}

void AudioReceivePipeline::note_usb_state(uint8_t state,
                                          uint8_t default_state,
                                          uint8_t suspended_state)
{
  if (!have_usb_state_) {
    last_usb_state_ = state;
    have_usb_state_ = true;
    return;
  }
  if (state == last_usb_state_) return;
  if (state == default_state) ++diagnostics_.usb_mic_reset;
  if (state == suspended_state) {
    ++diagnostics_.usb_mic_suspend;
  } else if (last_usb_state_ == suspended_state) {
    ++diagnostics_.usb_mic_resume;
  }
  last_usb_state_ = state;
}

void AudioReceivePipeline::note_hid_result(uint8_t interface_index,
                                           bool busy, bool dropped)
{
  if (interface_index >= 3U) return;
  if (busy) ++diagnostics_.hid_send_busy[interface_index];
  if (dropped) ++diagnostics_.hid_drop[interface_index];
}

void AudioReceivePipeline::set_reset_reason(ResetReason reason)
{
  diagnostics_.reset_reason = reason;
}

RenderResult AudioReceivePipeline::render(int16_t* output, size_t count)
{
  const RenderResult result = asrc_.render(ring_, output, count);
  if (result == RenderResult::kUnderflow) {
    ++diagnostics_.underflow;
  }
  refresh_ring_metrics();
  return result;
}

AudioStatus AudioReceivePipeline::status() const
{
  AudioStatus result{};
  result.flags = source_active() ? kStatusHealthy : kStatusPrefill;
  if (asrc_.prefilling()) {
    result.flags |= kStatusPrefill;
  }
  if (asrc_.step_ppm() == kAsrcClampPpm ||
      asrc_.step_ppm() == -kAsrcClampPpm) {
    result.flags |= kStatusAsrcClamp;
  }
  result.ring_fill = diagnostics_.ring_fill;
  result.ack_sequence = sequence_.initialized() ? sequence_.last() : 0U;
  result.ring_min = diagnostics_.ring_min;
  result.ring_max = diagnostics_.ring_max;
  result.crc_errors = static_cast<uint16_t>(diagnostics_.spi_crc_error);
  result.sequence_gaps = static_cast<uint16_t>(diagnostics_.spi_sequence_gap);
  result.underflows = static_cast<uint16_t>(diagnostics_.underflow);
  result.overflows = static_cast<uint16_t>(diagnostics_.overflow);
  result.asrc_ppm = diagnostics_.asrc_step_ppm;
  result.audio_alt = diagnostics_.capture_alt;
  result.spi_short_transfers =
      static_cast<uint16_t>(diagnostics_.spi_short_transfer);
  result.duplicates = static_cast<uint16_t>(diagnostics_.spi_duplicate);
  return result;
}

}  // namespace simple_kvm::audio
