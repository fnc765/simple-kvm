#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "../common/audio_format.h"

#ifdef __cplusplus
extern "C" {
#endif

void bp1_audio_usb_on_alt(uint8_t alt);
void bp1_audio_usb_receive_packet(const uint8_t* data, uint16_t length);

#ifdef __cplusplus
}
#endif

#ifdef __cplusplus
namespace simple_kvm::audio::bp1 {

enum class TransportEventType : uint8_t {
  kPcm = 0,
  kSessionStart,
  kSessionEnd,
  kRunStart,
  kRunEnd,
};

struct TransportEvent {
  TransportEventType type;
  uint32_t usb_audio_boundary;
  uint32_t boot_nonce;
  uint16_t session_counter;
  union {
    uint8_t pcm[kUsbPacketBytes];
    uint32_t run_id;
  };
};

void set_audio_boot_nonce(uint32_t boot_nonce);
bool enqueue_run_marker(bool start, uint32_t run_id);
bool pop_transport_event(TransportEvent& event);
uint8_t usb_audio_alt();
uint8_t usb_audio_queue_fill();
uint32_t usb_audio_packet_count();
uint32_t usb_audio_overwrite_count();
uint32_t usb_audio_byte_count();
uint32_t usb_audio_bad_size_count();
uint32_t usb_audio_short_count();
uint32_t usb_audio_alt_transition_count();
uint16_t audio_session_counter();
uint32_t audio_boot_nonce();

}  // namespace simple_kvm::audio::bp1
#endif
