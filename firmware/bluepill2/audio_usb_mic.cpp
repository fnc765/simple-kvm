#include "audio_usb_mic.h"

#include <string.h>

#include "audio_spi_slave.h"
#include "../common/audio_format.h"

namespace {

bool g_test_tone = false;
uint32_t g_tone_phase = 0U;

int16_t next_test_sample()
{
  // 997 Hz deterministic square test source.  The phase accumulator keeps the
  // exact average frequency without a large lookup table.
  g_tone_phase += 997U;
  if (g_tone_phase >= simple_kvm::audio::kSampleRate) {
    g_tone_phase -= simple_kvm::audio::kSampleRate;
  }
  return g_tone_phase < (simple_kvm::audio::kSampleRate / 2U) ? 10000 : -10000;
}

}  // namespace

extern "C" void bp2_audio_mic_on_alt(uint8_t alt)
{
  simple_kvm::audio::bp2::audio_receive_pipeline().set_capture_alt(alt);
  g_tone_phase = 0U;
}

extern "C" void bp2_audio_mic_set_test_tone(bool enabled)
{
  g_test_tone = enabled;
  g_tone_phase = 0U;
}

extern "C" void bp2_audio_mic_fill_packet(uint8_t* output, uint16_t length)
{
  using namespace simple_kvm::audio;
  if (output == nullptr) {
    return;
  }
  if (length != kUsbPacketBytes) {
    memset(output, 0, length);
    return;
  }
  int16_t samples[kSamplesPerUsbFrame];
  if (g_test_tone) {
    for (uint8_t i = 0U; i < kSamplesPerUsbFrame; ++i) {
      samples[i] = next_test_sample();
    }
  } else {
    (void)simple_kvm::audio::bp2::audio_receive_pipeline().render(
        samples, kSamplesPerUsbFrame);
  }
  for (uint8_t i = 0U; i < kSamplesPerUsbFrame; ++i) {
    const uint16_t sample = static_cast<uint16_t>(samples[i]);
    output[2U * i] = static_cast<uint8_t>(sample & 0xFFU);
    output[2U * i + 1U] = static_cast<uint8_t>(sample >> 8U);
  }
  simple_kvm::audio::bp2::audio_receive_pipeline().note_usb_mic_packet(length);
}
