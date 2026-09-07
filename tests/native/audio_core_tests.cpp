#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>

#include "audio_asrc.h"
#include "audio_control.h"
#include "audio_frame.h"
#include "audio_pipeline.h"
#include "audio_ring.h"
#include "audio_session.h"

using namespace simple_kvm::audio;

static unsigned g_tests = 0;

#define CHECK(condition)                                                      \
  do {                                                                        \
    ++g_tests;                                                                \
    if (!(condition)) {                                                       \
      std::fprintf(stderr, "AUDIO_FAIL test=%s line=%d\n", #condition,       \
                   __LINE__);                                                 \
      return 1;                                                               \
    }                                                                         \
  } while (0)

static int test_crc_and_frame()
{
  static const uint8_t check[] = {'1', '2', '3', '4', '5', '6', '7', '8', '9'};
  CHECK(crc16_ccitt_false(check, sizeof(check)) == 0x29B1U);

  AudioFrame frame{};
  frame.flags = kFlagValid;
  frame.sequence = 0xFFFFU;
  frame.boot_nonce = 0x78563412UL;
  frame.session_counter = 0x1234U;
  frame.sample_count = kSamplesPerUsbFrame;
  for (uint8_t i = 0; i < kSamplesPerUsbFrame; ++i) {
    frame.pcm[i] = static_cast<int16_t>(static_cast<int>(i) * 997 - 20000);
  }

  std::array<uint8_t, kSpiFrameBytes> encoded{};
  CHECK(encode_audio_frame(frame, encoded.data(), encoded.size()));
  CHECK(encoded[0] == 0xA5U && encoded[1] == 0x5AU);
  CHECK(encoded[12] == kSamplesPerUsbFrame);

  AudioFrame decoded{};
  CHECK(decode_audio_frame(encoded.data(), encoded.size(), decoded) ==
        AudioFrameError::kOk);
  CHECK(decoded.sequence == frame.sequence);
  CHECK(decoded.boot_nonce == frame.boot_nonce);
  CHECK(decoded.session_counter == frame.session_counter);
  CHECK(decoded.pcm[47] == frame.pcm[47]);

  encoded[42] ^= 0x80U;
  CHECK(decode_audio_frame(encoded.data(), encoded.size(), decoded) ==
        AudioFrameError::kCrc);

  frame.sample_count = 49U;
  CHECK(!encode_audio_frame(frame, encoded.data(), encoded.size()));

  AudioStatus status{};
  status.flags = kStatusHealthy | kStatusUsbConfigured;
  status.ack_sequence = 42U;
  status.ring_fill = 511U;
  status.underflows = 3U;
  status.asrc_ppm = -750;
  status.audio_alt = 1U;
  CHECK(encode_status_frame(status, encoded.data(), encoded.size()));
  AudioStatus decoded_status{};
  CHECK(decode_status_frame(encoded.data(), encoded.size(), decoded_status));
  CHECK(decoded_status.ack_sequence == 42U);
  CHECK(decoded_status.ring_fill == 511U);
  CHECK(decoded_status.asrc_ppm == -750);
  encoded[20] ^= 1U;
  CHECK(!decode_status_frame(encoded.data(), encoded.size(), decoded_status));

  frame = AudioFrame{};
  frame.flags = kFlagRunStart;
  frame.sequence = 7U;
  frame.boot_nonce = 9U;
  frame.session_counter = 3U;
  set_run_id(frame, 0xDEADBEEFUL);
  CHECK(encode_audio_frame(frame, encoded.data(), encoded.size()));
  CHECK(decode_audio_frame(encoded.data(), encoded.size(), decoded) ==
        AudioFrameError::kOk);
  CHECK(get_run_id(decoded) == 0xDEADBEEFUL);
  return 0;
}

static int test_sequence_and_session()
{
  SequenceTracker sequence;
  CHECK(sequence.observe(65534U) == SequenceResult::kFirst);
  CHECK(sequence.observe(65535U) == SequenceResult::kInOrder);
  CHECK(sequence.observe(0U) == SequenceResult::kInOrder);
  CHECK(sequence.observe(0U) == SequenceResult::kDuplicate);
  CHECK(sequence.observe(2U) == SequenceResult::kGap);

  SourceSessionState session;
  const SyncTuple first{0x11223344UL, 0x55667788UL};
  const SyncTuple second{0x11223344UL, 0x55667789UL};
  CHECK(session.accept_sync(first) == SyncResult::kAcceptedNew);
  CHECK(session.clear_count() == 1U);
  CHECK(session.accept_sync(first) == SyncResult::kDuplicate);
  CHECK(session.clear_count() == 1U);
  CHECK(session.accept_sync(second) == SyncResult::kAcceptedNew);
  CHECK(session.clear_count() == 2U);
  CHECK(session.start_source(second.boot_nonce, 4U));
  CHECK(session.matches(second.boot_nonce, 4U));
  CHECK(!session.end_source(second.boot_nonce, 3U));
  CHECK(session.end_source(second.boot_nonce, 4U));
  const uint32_t end_clear_count = session.clear_count();
  CHECK(session.end_source_result(second.boot_nonce, 4U) ==
        EndResult::kDuplicate);
  CHECK(session.clear_count() == end_clear_count);

  RunSnapshotStore store;
  RunSnapshot snapshot{};
  snapshot.run_id = 17U;
  snapshot.marker = RunMarker::kStart;
  snapshot.marker_sequence = 20U;
  snapshot.usb_audio_boundary = 100U;
  snapshot.spi_pcm_frames = 99U;
  CHECK(store.record(snapshot) == RunRecordResult::kCreated);
  CHECK(store.record(snapshot) == RunRecordResult::kDuplicate);
  snapshot.marker_sequence = 21U;
  CHECK(store.record(snapshot) == RunRecordResult::kConflict);
  return 0;
}

static int test_boot_barrier_and_sync_retry()
{
  BootHidQueue queue;
  std::array<uint8_t, kBootHidFrameBytes> frame{};
  frame[0] = 0xAAU;
  frame[19] = 0x55U;
  for (uint8_t i = 0U; i < kBootHidQueueSlots; ++i) {
    CHECK(queue.push(frame.data(), static_cast<uint8_t>(frame.size()),
                     100U + i));
  }
  CHECK(queue.fill() == kBootHidQueueSlots);
  CHECK(queue.high_water() == kBootHidQueueSlots);
  CHECK(!queue.push(frame.data(), static_cast<uint8_t>(frame.size()), 999U));
  CHECK(queue.overflow_count() == 1U);
  uint32_t accepted_ms = 0U;
  uint8_t length = 0U;
  std::array<uint8_t, kBootHidFrameBytes> popped{};
  CHECK(queue.pop(popped.data(), length, accepted_ms));
  CHECK(length == kBootHidFrameBytes);
  CHECK(accepted_ms == 100U);
  CHECK(popped == frame);

  SyncRetryState sync;
  sync.begin(1000U, SyncTuple{0x12345678UL, 0x90ABCDEFUL});
  CHECK(sync.barrier_active(1059U));
  CHECK(!sync.barrier_active(1060U));
  CHECK(sync.should_send(1060U));
  sync.mark_sent(1060U);
  CHECK(!sync.should_send(1159U));
  CHECK(sync.should_send(1160U));
  sync.mark_sent(1160U);
  CHECK(sync.send_count() == 2U);
  CHECK(!sync.ack(SyncTuple{0x12345678UL, 1U}));
  CHECK(sync.ack(SyncTuple{0x12345678UL, 0x90ABCDEFUL}));
  CHECK(sync.acked());
  CHECK(!sync.should_send(2000U));
  return 0;
}

static int test_receive_pipeline()
{
  AudioReceivePipeline pipeline;
  const SyncTuple sync{0xAABBCCDDUL, 7U};
  CHECK(pipeline.accept_sync(sync) == SyncResult::kAcceptedNew);
  const uint32_t clears = pipeline.diagnostics().source_session_clears;
  CHECK(pipeline.accept_sync(sync) == SyncResult::kDuplicate);
  CHECK(pipeline.diagnostics().source_session_clears == clears);
  pipeline.set_capture_alt(1U);

  AudioFrame frame{};
  frame.flags = kFlagSessionStart;
  frame.sequence = 10U;
  frame.boot_nonce = sync.boot_nonce;
  frame.session_counter = 3U;
  frame.sample_count = 0U;
  for (uint8_t i = 0U; i < kSamplesPerUsbFrame; ++i) {
    frame.pcm[i] = static_cast<int16_t>(i * 100);
  }
  std::array<uint8_t, kSpiFrameBytes> bytes{};
  CHECK(encode_audio_frame(frame, bytes.data(), bytes.size()));
  CHECK(pipeline.process_frame(bytes.data(), bytes.size(), 100U));
  CHECK(pipeline.diagnostics().accepted_control_frames == 1U);
  // The watchdog starts after the first PCM frame, not at SESSION_START;
  // delayed host-side USB startup must not invalidate a new session.
  CHECK(pipeline.source_timeout(110U) == false);
  frame.flags = kFlagValid;
  frame.sequence = 11U;
  frame.sample_count = kSamplesPerUsbFrame;
  CHECK(encode_audio_frame(frame, bytes.data(), bytes.size()));
  CHECK(pipeline.process_frame(bytes.data(), bytes.size(), 101U));
  CHECK(pipeline.diagnostics().accepted_pcm_frames == 1U);
  CHECK(pipeline.diagnostics().ring_fill == kSamplesPerUsbFrame);

  CHECK(!pipeline.process_frame(bytes.data(), bytes.size(), 102U));
  CHECK(pipeline.diagnostics().spi_duplicate == 1U);
  bytes[40] ^= 1U;
  CHECK(!pipeline.process_frame(bytes.data(), bytes.size(), 103U));
  CHECK(pipeline.diagnostics().spi_crc_error == 1U);

  AudioFrame marker{};
  marker.flags = kFlagRunStart;
  marker.sequence = 12U;
  marker.boot_nonce = sync.boot_nonce;
  marker.session_counter = 3U;
  set_run_id(marker, 0x1234U);
  CHECK(encode_audio_frame(marker, bytes.data(), bytes.size()));
  CHECK(pipeline.process_frame(bytes.data(), bytes.size(), 104U));
  const RunSnapshot* snapshot =
      pipeline.run_snapshots().find(0x1234U, RunMarker::kStart);
  CHECK(snapshot != nullptr);
  CHECK(snapshot->accepted_pcm_frames == 1U);
  CHECK(snapshot->marker_sequence == 12U);

  pipeline.set_capture_alt(0U);
  frame.flags = kFlagValid;
  frame.sequence = 13U;
  CHECK(encode_audio_frame(frame, bytes.data(), bytes.size()));
  CHECK(pipeline.process_frame(bytes.data(), bytes.size(), 105U));
  CHECK(pipeline.diagnostics().discarded_capture_closed == 1U);
  CHECK(pipeline.source_timeout(107U) == false);
  CHECK(pipeline.source_timeout(109U));
  CHECK(pipeline.diagnostics().source_timeouts == 1U);
  pipeline.update_uptime(12345U);
  pipeline.note_usb_mic_packet(kUsbPacketBytes);
  pipeline.note_usb_state(3U, 1U, 4U);  // initial configured state
  pipeline.note_usb_state(4U, 1U, 4U);  // suspend
  pipeline.note_usb_state(3U, 1U, 4U);  // resume
  pipeline.note_usb_state(1U, 1U, 4U);  // reset/default
  pipeline.note_hid_result(0U, true, true);
  pipeline.note_hid_result(2U, false, true);
  pipeline.set_reset_reason(ResetReason::kIwdg);
  CHECK(pipeline.diagnostics().uptime_ms == 12345U);
  CHECK(pipeline.diagnostics().usb_mic_packets == 1U);
  CHECK(pipeline.diagnostics().usb_mic_bytes == kUsbPacketBytes);
  CHECK(pipeline.diagnostics().usb_mic_suspend == 1U);
  CHECK(pipeline.diagnostics().usb_mic_resume == 1U);
  CHECK(pipeline.diagnostics().usb_mic_reset == 1U);
  CHECK(pipeline.diagnostics().hid_send_busy[0] == 1U);
  CHECK(pipeline.diagnostics().hid_drop[0] == 1U);
  CHECK(pipeline.diagnostics().hid_drop[2] == 1U);
  CHECK(pipeline.diagnostics().reset_reason == ResetReason::kIwdg);

  // A receiver reboot must recover an already-running source after the SYNC
  // barrier, even when the source's alt=1 state means no new SESSION_START is
  // emitted.  A new session counter is accepted; the last ended counter is
  // still rejected by the stale-session guard above.
  AudioReceivePipeline recovered;
  CHECK(recovered.accept_sync(sync) == SyncResult::kAcceptedNew);
  recovered.set_capture_alt(1U);
  AudioFrame recovery_frame{};
  recovery_frame.flags = kFlagValid;
  recovery_frame.sequence = 1U;
  recovery_frame.boot_nonce = sync.boot_nonce;
  recovery_frame.session_counter = 4U;
  recovery_frame.sample_count = kSamplesPerUsbFrame;
  CHECK(encode_audio_frame(recovery_frame, bytes.data(), bytes.size()));
  CHECK(recovered.process_frame(bytes.data(), bytes.size(), 200U));
  CHECK(recovered.diagnostics().source_session_starts == 1U);
  CHECK(recovered.diagnostics().accepted_pcm_frames == 1U);
  return 0;
}

static int test_ring()
{
  AudioRing ring;
  CHECK(ring.empty());
  for (uint16_t i = 0; i < kRingCapacity; ++i) {
    CHECK(ring.push_one(static_cast<int16_t>(i)));
  }
  CHECK(ring.full());
  CHECK(!ring.push_one(123));
  CHECK(ring.peek(0U) == 0);
  CHECK(ring.peek(kRingCapacity - 1U) ==
        static_cast<int16_t>(kRingCapacity - 1U));
  CHECK(ring.discard(513U) == 513U);
  CHECK(ring.fill() == 511U);
  for (uint16_t i = 0; i < 513U; ++i) {
    CHECK(ring.push_one(static_cast<int16_t>(-static_cast<int>(i))));
  }
  CHECK(ring.full());
  ring.clear();
  CHECK(ring.empty());
  return 0;
}

static int test_asrc_vectors()
{
  AudioRing ring;
  AudioAsrc asrc;
  std::array<int16_t, kSamplesPerUsbFrame> output{};

  for (uint16_t i = 0; i < kRingTargetFill; ++i) {
    CHECK(ring.push_one(static_cast<int16_t>(i * 32U)));
  }
  CHECK(asrc.render(ring, output.data(), output.size()) == RenderResult::kAudio);
  CHECK(output[0] == 0);  // startup ramp begins at zero
  CHECK(output[47] > output[46]);

  asrc.reset();
  ring.clear();
  CHECK(asrc.render(ring, output.data(), output.size()) == RenderResult::kPrefill);
  for (int16_t sample : output) {
    CHECK(sample == 0);
  }

  // Full-scale alternating interpolation must stay in int16 range.
  ring.clear();
  for (uint16_t i = 0; i < kRingTargetFill; ++i) {
    CHECK(ring.push_one((i & 1U) ? INT16_MAX : INT16_MIN));
  }
  asrc.reset();
  asrc.set_step_ppm_for_test(500);
  CHECK(asrc.render(ring, output.data(), output.size()) == RenderResult::kAudio);
  for (int16_t sample : output) {
    CHECK(sample >= INT16_MIN && sample <= INT16_MAX);
  }
  return 0;
}

static int test_accelerated_drift()
{
  constexpr std::array<int32_t, 7> drifts{{-1000, -500, -100, 0, 100, 500, 1000}};
  constexpr uint32_t updates_per_day = (24U * 60U * 60U * 1000U) / 8U;

  for (const int32_t source_ppm : drifts) {
    AsrcController controller;
    int64_t fill_q16 = static_cast<int64_t>(kRingTargetFill) << 16;
    int64_t source_fraction = 0;
    uint16_t min_fill = kRingTargetFill;
    uint16_t max_fill = kRingTargetFill;

    for (uint32_t update = 0; update < updates_per_day; ++update) {
      // Eight milliseconds at 48 samples/ms, represented in Q16 samples.
      source_fraction += static_cast<int64_t>(384) * source_ppm * 65536LL;
      const int64_t source_q16 = (384LL << 16) + source_fraction / 1000000LL;
      source_fraction %= 1000000LL;
      const int64_t consumed_q16 =
          (384LL << 16) +
          (static_cast<int64_t>(384) * controller.step_ppm() * 65536LL) /
              1000000LL;
      fill_q16 += source_q16 - consumed_q16;
      const int32_t fill = static_cast<int32_t>(fill_q16 >> 16);
      if (fill <= 0 || fill >= kRingCapacity) {
        std::fprintf(stderr,
                     "AUDIO_FAIL stage=asrc drift_ppm=%ld fill=%ld update=%lu\n",
                     static_cast<long>(source_ppm), static_cast<long>(fill),
                     static_cast<unsigned long>(update));
        return 1;
      }
      controller.update(static_cast<uint16_t>(fill));
      if (update > 625U) {  // after five seconds
        min_fill = static_cast<uint16_t>(fill < min_fill ? fill : min_fill);
        max_fill = static_cast<uint16_t>(fill > max_fill ? fill : max_fill);
      }
    }
    CHECK(min_fill >= 205U);
    CHECK(max_fill <= 819U);
    CHECK(controller.clamp_count() == 0U);
    CHECK(controller.step_ppm() >= source_ppm - 20);
    CHECK(controller.step_ppm() <= source_ppm + 20);
  }
  return 0;
}

int main()
{
  if (test_crc_and_frame() != 0 || test_sequence_and_session() != 0 ||
      test_boot_barrier_and_sync_retry() != 0 ||
      test_receive_pipeline() != 0 ||
      test_ring() != 0 || test_asrc_vectors() != 0 ||
      test_accelerated_drift() != 0) {
    return 1;
  }
  std::printf("AUDIO_UNIT_PASS tests=%u\n", g_tests);
  return 0;
}
