#include "audio_usb_out.h"

#include <Arduino.h>
#include <string.h>

namespace simple_kvm::audio::bp1 {
namespace {

constexpr uint8_t kQueueSlots = 4U;
TransportEvent g_queue[kQueueSlots];
volatile uint8_t g_head = 0U;
volatile uint8_t g_tail = 0U;
volatile uint8_t g_count = 0U;
volatile uint8_t g_alt = 0U;
volatile uint32_t g_packets = 0U;
volatile uint32_t g_bytes = 0U;
volatile uint32_t g_overwrites = 0U;
volatile uint32_t g_bad_size = 0U;
volatile uint32_t g_short = 0U;
volatile uint32_t g_alt_transitions = 0U;
volatile uint32_t g_boot_nonce = 0U;
volatile uint16_t g_session_counter = 0U;

void clear_queue()
{
  g_head = 0U;
  g_tail = 0U;
  g_count = 0U;
}

bool push_event(const TransportEvent& event)
{
  if (g_count >= kQueueSlots) {
    ++g_overwrites;
    return false;
  }
  g_queue[g_head] = event;
  g_head = static_cast<uint8_t>((g_head + 1U) % kQueueSlots);
  ++g_count;
  return true;
}

}  // namespace

void set_audio_boot_nonce(uint32_t boot_nonce) { g_boot_nonce = boot_nonce; }

bool enqueue_run_marker(bool start, uint32_t run_id)
{
  TransportEvent event{};
  event.type = start ? TransportEventType::kRunStart
                     : TransportEventType::kRunEnd;
  event.usb_audio_boundary = g_packets;
  event.boot_nonce = g_boot_nonce;
  event.session_counter = g_session_counter;
  event.run_id = run_id;
  noInterrupts();
  const bool result = push_event(event);
  interrupts();
  return result;
}

bool pop_transport_event(TransportEvent& event)
{
  noInterrupts();
  if (g_count == 0U) {
    interrupts();
    return false;
  }
  event = g_queue[g_tail];
  g_tail = static_cast<uint8_t>((g_tail + 1U) % kQueueSlots);
  --g_count;
  interrupts();
  return true;
}

uint8_t usb_audio_alt() { return g_alt; }
uint8_t usb_audio_queue_fill() { return g_count; }
uint32_t usb_audio_packet_count() { return g_packets; }
uint32_t usb_audio_overwrite_count() { return g_overwrites; }
uint32_t usb_audio_byte_count() { return g_bytes; }
uint32_t usb_audio_bad_size_count() { return g_bad_size; }
uint32_t usb_audio_short_count() { return g_short; }
uint32_t usb_audio_alt_transition_count() { return g_alt_transitions; }
uint16_t audio_session_counter() { return g_session_counter; }
uint32_t audio_boot_nonce() { return g_boot_nonce; }

}  // namespace simple_kvm::audio::bp1

extern "C" void bp1_audio_usb_on_alt(uint8_t alt)
{
  using namespace simple_kvm::audio::bp1;
  if (g_alt == alt) {
    return;
  }
  g_alt = alt;
  ++g_alt_transitions;
  TransportEvent event{};
  event.usb_audio_boundary = g_packets;
  event.boot_nonce = g_boot_nonce;
  event.session_counter = g_session_counter;
  if (alt == 1U) {
    clear_queue();
    ++g_session_counter;
    event.type = TransportEventType::kSessionStart;
    event.session_counter = g_session_counter;
  } else {
    event.type = TransportEventType::kSessionEnd;
  }
  (void)push_event(event);
}

extern "C" void bp1_audio_usb_receive_packet(const uint8_t* data,
                                               uint16_t length)
{
  using namespace simple_kvm::audio;
  using namespace simple_kvm::audio::bp1;
  if (g_alt != 1U || data == nullptr) {
    return;
  }
  if (length != kUsbPacketBytes) {
    if (length < kUsbPacketBytes) ++g_short;
    ++g_bad_size;
    return;
  }
  ++g_packets;
  g_bytes += length;
  TransportEvent event{};
  event.type = TransportEventType::kPcm;
  event.usb_audio_boundary = g_packets;
  event.boot_nonce = g_boot_nonce;
  event.session_counter = g_session_counter;
  memcpy(event.pcm, data, kUsbPacketBytes);
  (void)push_event(event);
}
