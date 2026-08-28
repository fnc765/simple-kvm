#include "audio_frame.h"

#include <string.h>

namespace simple_kvm::audio {
namespace {

constexpr uint8_t kAudioMagic0 = 0xA5U;
constexpr uint8_t kAudioMagic1 = 0x5AU;
constexpr uint8_t kStatusMagic0 = 0x5AU;
constexpr uint8_t kStatusMagic1 = 0xA5U;

void write_u16(uint8_t* output, uint16_t value)
{
  output[0] = static_cast<uint8_t>(value & 0xFFU);
  output[1] = static_cast<uint8_t>(value >> 8U);
}

void write_u32(uint8_t* output, uint32_t value)
{
  output[0] = static_cast<uint8_t>(value & 0xFFU);
  output[1] = static_cast<uint8_t>((value >> 8U) & 0xFFU);
  output[2] = static_cast<uint8_t>((value >> 16U) & 0xFFU);
  output[3] = static_cast<uint8_t>(value >> 24U);
}

uint16_t read_u16(const uint8_t* input)
{
  return static_cast<uint16_t>(input[0]) |
         static_cast<uint16_t>(static_cast<uint16_t>(input[1]) << 8U);
}

uint32_t read_u32(const uint8_t* input)
{
  return static_cast<uint32_t>(input[0]) |
         (static_cast<uint32_t>(input[1]) << 8U) |
         (static_cast<uint32_t>(input[2]) << 16U) |
         (static_cast<uint32_t>(input[3]) << 24U);
}

}  // namespace

uint16_t crc16_ccitt_false(const uint8_t* data, size_t length)
{
  uint16_t crc = 0xFFFFU;
  for (size_t i = 0; i < length; ++i) {
    crc ^= static_cast<uint16_t>(data[i]) << 8U;
    for (uint8_t bit = 0; bit < 8U; ++bit) {
      crc = (crc & 0x8000U) != 0U
                ? static_cast<uint16_t>((crc << 1U) ^ 0x1021U)
                : static_cast<uint16_t>(crc << 1U);
    }
  }
  return crc;
}

bool encode_audio_frame(const AudioFrame& frame, uint8_t* output, size_t length)
{
  if (output == nullptr || length != kSpiFrameBytes ||
      frame.sample_count > kSamplesPerUsbFrame) {
    return false;
  }

  memset(output, 0, length);
  output[0] = kAudioMagic0;
  output[1] = kAudioMagic1;
  output[2] = kAudioFrameVersion;
  output[3] = frame.flags;
  write_u16(&output[4], frame.sequence);
  write_u32(&output[6], frame.boot_nonce);
  write_u16(&output[10], frame.session_counter);
  output[12] = frame.sample_count;
  output[13] = 0U;

  if (frame.sample_count > 0U) {
    for (uint8_t i = 0; i < frame.sample_count; ++i) {
      write_u16(&output[14U + static_cast<size_t>(i) * 2U],
                static_cast<uint16_t>(frame.pcm[i]));
    }
  } else {
    memcpy(&output[14], frame.control, kUsbPacketBytes);
  }
  write_u16(&output[110], crc16_ccitt_false(&output[2], 108U));
  return true;
}

AudioFrameError decode_audio_frame(const uint8_t* input, size_t length,
                                   AudioFrame& frame)
{
  if (input == nullptr || length != kSpiFrameBytes) {
    return AudioFrameError::kLength;
  }
  if (input[0] != kAudioMagic0 || input[1] != kAudioMagic1) {
    return AudioFrameError::kMagic;
  }
  if (input[2] != kAudioFrameVersion) {
    return AudioFrameError::kVersion;
  }
  if (input[12] > kSamplesPerUsbFrame) {
    return AudioFrameError::kSampleCount;
  }
  if (read_u16(&input[110]) != crc16_ccitt_false(&input[2], 108U)) {
    return AudioFrameError::kCrc;
  }

  memset(&frame, 0, sizeof(frame));
  frame.flags = input[3];
  frame.sequence = read_u16(&input[4]);
  frame.boot_nonce = read_u32(&input[6]);
  frame.session_counter = read_u16(&input[10]);
  frame.sample_count = input[12];
  if (frame.sample_count > 0U) {
    for (uint8_t i = 0; i < frame.sample_count; ++i) {
      frame.pcm[i] = static_cast<int16_t>(
          read_u16(&input[14U + static_cast<size_t>(i) * 2U]));
    }
  } else {
    memcpy(frame.control, &input[14], kUsbPacketBytes);
  }
  return AudioFrameError::kOk;
}

void set_run_id(AudioFrame& frame, uint32_t run_id)
{
  frame.sample_count = 0U;
  memset(frame.control, 0, kUsbPacketBytes);
  write_u32(frame.control, run_id);
}

uint32_t get_run_id(const AudioFrame& frame)
{
  return read_u32(frame.control);
}

SequenceTracker::SequenceTracker() : initialized_(false), last_(0U) {}

void SequenceTracker::reset()
{
  initialized_ = false;
  last_ = 0U;
}

SequenceResult SequenceTracker::observe(uint16_t sequence)
{
  if (!initialized_) {
    initialized_ = true;
    last_ = sequence;
    return SequenceResult::kFirst;
  }
  if (sequence == last_) {
    return SequenceResult::kDuplicate;
  }
  const uint16_t expected = static_cast<uint16_t>(last_ + 1U);
  last_ = sequence;
  return sequence == expected ? SequenceResult::kInOrder : SequenceResult::kGap;
}

bool encode_status_frame(const AudioStatus& status, uint8_t* output,
                         size_t length)
{
  if (output == nullptr || length != kSpiFrameBytes) {
    return false;
  }
  memset(output, 0, length);
  output[0] = kStatusMagic0;
  output[1] = kStatusMagic1;
  output[2] = kAudioFrameVersion;
  output[3] = static_cast<uint8_t>(status.flags & 0x1FU);
  write_u16(&output[4], status.ack_sequence);
  write_u16(&output[6], status.ring_fill);
  write_u16(&output[8], status.ring_min);
  write_u16(&output[10], status.ring_max);
  write_u16(&output[12], status.crc_errors);
  write_u16(&output[14], status.sequence_gaps);
  write_u16(&output[16], status.underflows);
  write_u16(&output[18], status.overflows);
  write_u16(&output[20], static_cast<uint16_t>(status.asrc_ppm));
  output[22] = status.audio_alt;
  output[23] = status.reset_reason;
  write_u16(&output[24], status.spi_short_transfers);
  write_u16(&output[26], status.hid_drops);
  write_u16(&output[28], status.duplicates);
  write_u16(&output[30], crc16_ccitt_false(output, 30U));
  return true;
}

bool decode_status_frame(const uint8_t* input, size_t length,
                         AudioStatus& status)
{
  if (input == nullptr || length != kSpiFrameBytes ||
      input[0] != kStatusMagic0 || input[1] != kStatusMagic1 ||
      input[2] != kAudioFrameVersion ||
      read_u16(&input[30]) != crc16_ccitt_false(input, 30U)) {
    return false;
  }
  status.flags = input[3];
  status.ack_sequence = read_u16(&input[4]);
  status.ring_fill = read_u16(&input[6]);
  status.ring_min = read_u16(&input[8]);
  status.ring_max = read_u16(&input[10]);
  status.crc_errors = read_u16(&input[12]);
  status.sequence_gaps = read_u16(&input[14]);
  status.underflows = read_u16(&input[16]);
  status.overflows = read_u16(&input[18]);
  status.asrc_ppm = static_cast<int16_t>(read_u16(&input[20]));
  status.audio_alt = input[22];
  status.reset_reason = input[23];
  status.spi_short_transfers = read_u16(&input[24]);
  status.hid_drops = read_u16(&input[26]);
  status.duplicates = read_u16(&input[28]);
  return true;
}

}  // namespace simple_kvm::audio
