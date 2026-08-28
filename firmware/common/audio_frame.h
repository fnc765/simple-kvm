#pragma once

#include <stddef.h>
#include <stdint.h>

#include "audio_format.h"

namespace simple_kvm::audio {

constexpr uint8_t kAudioFrameVersion = 1U;
constexpr uint8_t kFlagValid = 1U << 0;
constexpr uint8_t kFlagDiscontinuity = 1U << 1;
constexpr uint8_t kFlagMute = 1U << 2;
constexpr uint8_t kFlagTest = 1U << 3;
constexpr uint8_t kFlagSessionStart = 1U << 4;
constexpr uint8_t kFlagSessionEnd = 1U << 5;
constexpr uint8_t kFlagRunStart = 1U << 6;
constexpr uint8_t kFlagRunEnd = 1U << 7;

struct AudioFrame {
  uint8_t flags;
  uint16_t sequence;
  uint32_t boot_nonce;
  uint16_t session_counter;
  uint8_t sample_count;
  union {
    int16_t pcm[kSamplesPerUsbFrame];
    uint8_t control[kUsbPacketBytes];
  };
};

enum class AudioFrameError : uint8_t {
  kOk = 0,
  kLength,
  kMagic,
  kVersion,
  kSampleCount,
  kCrc,
};

uint16_t crc16_ccitt_false(const uint8_t* data, size_t length);
bool encode_audio_frame(const AudioFrame& frame, uint8_t* output, size_t length);
AudioFrameError decode_audio_frame(const uint8_t* input, size_t length,
                                   AudioFrame& frame);
void set_run_id(AudioFrame& frame, uint32_t run_id);
uint32_t get_run_id(const AudioFrame& frame);

enum class SequenceResult : uint8_t {
  kFirst = 0,
  kInOrder,
  kDuplicate,
  kGap,
};

class SequenceTracker {
 public:
  SequenceTracker();
  void reset();
  SequenceResult observe(uint16_t sequence);
  bool initialized() const { return initialized_; }
  uint16_t last() const { return last_; }

 private:
  bool initialized_;
  uint16_t last_;
};

constexpr uint8_t kStatusHealthy = 1U << 0;
constexpr uint8_t kStatusPrefill = 1U << 1;
constexpr uint8_t kStatusAsrcClamp = 1U << 2;
constexpr uint8_t kStatusUsbConfigured = 1U << 3;
constexpr uint8_t kStatusSpiErrorLatched = 1U << 4;

struct AudioStatus {
  uint8_t flags;
  uint16_t ack_sequence;
  uint16_t ring_fill;
  uint16_t ring_min;
  uint16_t ring_max;
  uint16_t crc_errors;
  uint16_t sequence_gaps;
  uint16_t underflows;
  uint16_t overflows;
  int16_t asrc_ppm;
  uint8_t audio_alt;
  uint8_t reset_reason;
  uint16_t spi_short_transfers;
  uint16_t hid_drops;
  uint16_t duplicates;
};

bool encode_status_frame(const AudioStatus& status, uint8_t* output,
                         size_t length);
bool decode_status_frame(const uint8_t* input, size_t length,
                         AudioStatus& status);

}  // namespace simple_kvm::audio
