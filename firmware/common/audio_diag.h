#pragma once

#include <stdint.h>

namespace simple_kvm::audio {

enum class ResetReason : uint8_t {
  kUnknown = 0,
  kPowerOn = 1,
  kExternalPin = 2,
  kSoftware = 3,
  kIwdg = 4,
  kWwdg = 5,
  kLowPower = 6,
  kHardFault = 7,
};

struct Bp1Diagnostics {
  uint32_t usb_audio_packets;
  uint32_t usb_audio_bytes;
  uint32_t usb_audio_short;
  uint32_t usb_audio_bad_size;
  uint32_t usb_audio_alt_transitions;
  uint32_t usb_audio_reset;
  uint32_t usb_audio_suspend;
  uint32_t usb_audio_resume;
  uint32_t audio_source_session_starts;
  uint32_t audio_source_session_ends;
  uint32_t audio_control_sync_requests;
  uint32_t audio_control_sync_retries;
  uint32_t audio_control_sync_acks;
  uint32_t audio_control_sync_failures;
  uint32_t usb_audio_overwrite;
  uint32_t usb_audio_missing_ms;
  uint32_t spi_pcm_frames;
  uint32_t spi_control_frames;
  uint32_t spi_dma_busy;
  uint32_t spi_deadline_miss;
  uint32_t spi_status_crc_error;
  uint32_t cdc_rx;
  uint32_t cdc_tx;
  uint32_t uart_tx;
  uint32_t uart_rx;
  uint32_t hid_boot_queue_high_water;
  uint32_t hid_boot_queue_overflow;
  uint32_t uptime_ms;
  uint32_t audio_source_boot_nonce;
  uint32_t sync_request_id;
  uint16_t audio_source_session_counter;
  uint8_t usb_audio_alt;
  ResetReason reset_reason;
};

struct Bp2Diagnostics {
  uint32_t spi_rx_frames;
  uint32_t accepted_pcm_frames;
  uint32_t accepted_control_frames;
  uint32_t spi_magic_error;
  uint32_t spi_version_error;
  uint32_t spi_crc_error;
  uint32_t spi_sequence_gap;
  uint32_t spi_duplicate;
  uint32_t spi_short_transfer;
  uint32_t spi_overrun;
  uint32_t source_session_starts;
  uint32_t source_session_ends;
  uint32_t source_session_clears;
  uint32_t source_timeouts;
  uint32_t stale_session_controls;
  uint32_t control_sync_accepts;
  uint32_t control_sync_duplicates;
  uint32_t capture_alt_transitions;
  uint32_t capture_session_starts;
  uint32_t capture_session_clears;
  uint32_t discarded_capture_closed;
  uint32_t asrc_clamp_count;
  uint32_t usb_mic_packets;
  uint32_t usb_mic_bytes;
  uint32_t usb_mic_reset;
  uint32_t usb_mic_suspend;
  uint32_t usb_mic_resume;
  uint32_t underflow;
  uint32_t overflow;
  uint32_t prefill_count;
  uint32_t hid_send_busy[3];
  uint32_t hid_drop[3];
  uint32_t uptime_ms;
  uint32_t source_boot_nonce;
  int32_t asrc_integral;
  int16_t asrc_step_ppm;
  uint16_t source_session_counter;
  uint16_t ring_fill;
  uint16_t ring_min;
  uint16_t ring_max;
  uint8_t capture_alt;
  ResetReason reset_reason;
};

}  // namespace simple_kvm::audio
