#pragma once

#include <stdint.h>

#define SIMPLE_KVM_AUDIO_SAMPLE_RATE       48000UL
#define SIMPLE_KVM_AUDIO_CHANNELS          1U
#define SIMPLE_KVM_AUDIO_BITS              16U
#define SIMPLE_KVM_AUDIO_SAMPLES_PER_MS    48U
#define SIMPLE_KVM_AUDIO_USB_PACKET_BYTES  96U
#define SIMPLE_KVM_AUDIO_SPI_FRAME_BYTES   112U
#define SIMPLE_KVM_AUDIO_RING_CAPACITY     1024U
#define SIMPLE_KVM_AUDIO_RING_TARGET       512U

#ifdef __cplusplus
namespace simple_kvm::audio {

constexpr uint32_t kSampleRate = SIMPLE_KVM_AUDIO_SAMPLE_RATE;
constexpr uint8_t kChannels = SIMPLE_KVM_AUDIO_CHANNELS;
constexpr uint8_t kBitsPerSample = SIMPLE_KVM_AUDIO_BITS;
constexpr uint8_t kSamplesPerUsbFrame = SIMPLE_KVM_AUDIO_SAMPLES_PER_MS;
constexpr uint16_t kUsbPacketBytes = SIMPLE_KVM_AUDIO_USB_PACKET_BYTES;
constexpr uint16_t kSpiFrameBytes = SIMPLE_KVM_AUDIO_SPI_FRAME_BYTES;
constexpr uint16_t kRingCapacity = SIMPLE_KVM_AUDIO_RING_CAPACITY;
constexpr uint16_t kRingTargetFill = SIMPLE_KVM_AUDIO_RING_TARGET;

static_assert(kChannels == 1U, "initial audio bridge is mono");
static_assert(kBitsPerSample == 16U, "initial audio bridge is PCM16");
static_assert(kSamplesPerUsbFrame * sizeof(int16_t) == kUsbPacketBytes,
              "USB audio packet must contain exactly 48 PCM16 samples");
static_assert((kRingCapacity & (kRingCapacity - 1U)) == 0U,
              "audio ring capacity must be a power of two");

}  // namespace simple_kvm::audio
#endif
