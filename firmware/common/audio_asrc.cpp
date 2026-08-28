#include "audio_asrc.h"

#include <limits.h>
#include <string.h>

namespace simple_kvm::audio {
namespace {

constexpr int32_t kProportionalPpmPerSample = 8;
constexpr int32_t kIntegralQ16PerSampleUpdate = 128;
constexpr int32_t kIntegralLimitQ16 = kAsrcClampPpm << 16;

int32_t clamp_ppm(int32_t value)
{
  if (value > kAsrcClampPpm) {
    return kAsrcClampPpm;
  }
  if (value < -kAsrcClampPpm) {
    return -kAsrcClampPpm;
  }
  return value;
}

int16_t clamp_sample(int64_t value)
{
  if (value > INT16_MAX) {
    return INT16_MAX;
  }
  if (value < INT16_MIN) {
    return INT16_MIN;
  }
  return static_cast<int16_t>(value);
}

}  // namespace

AsrcController::AsrcController() { reset(); }

void AsrcController::reset()
{
  integral_q16_ = 0;
  step_ppm_ = 0;
  clamp_count_ = 0U;
}

void AsrcController::update(uint16_t fill)
{
  const int32_t error = static_cast<int32_t>(fill) -
                        static_cast<int32_t>(kRingTargetFill);
  int32_t proposed_integral =
      integral_q16_ + error * kIntegralQ16PerSampleUpdate;
  if (proposed_integral > kIntegralLimitQ16) {
    proposed_integral = kIntegralLimitQ16;
  } else if (proposed_integral < -kIntegralLimitQ16) {
    proposed_integral = -kIntegralLimitQ16;
  }

  const int32_t proposed = error * kProportionalPpmPerSample +
                           (proposed_integral >> 16U);
  if (proposed > kAsrcClampPpm || proposed < -kAsrcClampPpm) {
    ++clamp_count_;
    // Anti-windup: keep integrating only when the error moves away from the
    // active clamp.
    if ((proposed > kAsrcClampPpm && error < 0) ||
        (proposed < -kAsrcClampPpm && error > 0)) {
      integral_q16_ = proposed_integral;
    }
  } else {
    integral_q16_ = proposed_integral;
  }
  step_ppm_ = clamp_ppm(error * kProportionalPpmPerSample +
                        (integral_q16_ >> 16U));
}

void AsrcController::set_step_ppm_for_test(int32_t ppm)
{
  step_ppm_ = clamp_ppm(ppm);
  integral_q16_ = step_ppm_ << 16U;
}

AudioAsrc::AudioAsrc() { reset(); }

void AudioAsrc::reset()
{
  controller_.reset();
  phase_q30_ = 0U;
  controller_ms_ = 0U;
  prefilling_ = true;
  ramp_pending_ = true;
  underflow_count_ = 0U;
  prefill_count_ = 0U;
}

RenderResult AudioAsrc::render(AudioRing& ring, int16_t* output, size_t count)
{
  if (output == nullptr || count == 0U) {
    return RenderResult::kUnderflow;
  }

  if (prefilling_) {
    if (ring.fill() < kRingTargetFill) {
      memset(output, 0, count * sizeof(*output));
      return RenderResult::kPrefill;
    }
    prefilling_ = false;
    ramp_pending_ = true;
    phase_q30_ = 0U;
    ++prefill_count_;
  }

  const int64_t step_q30 =
      static_cast<int64_t>(kPhaseOne) +
      (static_cast<int64_t>(controller_.step_ppm()) *
       static_cast<int64_t>(kPhaseOne)) /
          1000000LL;
  const uint64_t maximum_phase =
      phase_q30_ + static_cast<uint64_t>(step_q30) * count;
  const uint16_t required =
      static_cast<uint16_t>((maximum_phase >> 30U) + 2U);
  if (ring.fill() < required) {
    memset(output, 0, count * sizeof(*output));
    ++underflow_count_;
    prefilling_ = true;
    ramp_pending_ = true;
    controller_.reset();
    phase_q30_ = 0U;
    return RenderResult::kUnderflow;
  }

  for (size_t i = 0; i < count; ++i) {
    const int64_t x0 = ring.peek(0U);
    const int64_t x1 = ring.peek(1U);
    const int64_t fraction = static_cast<int64_t>(phase_q30_ & (kPhaseOne - 1U));
    int64_t interpolated = x0 + (((x1 - x0) * fraction) >> 30U);
    if (ramp_pending_ && count > 1U) {
      interpolated = (interpolated * static_cast<int64_t>(i)) /
                     static_cast<int64_t>(count - 1U);
    }
    output[i] = clamp_sample(interpolated);
    phase_q30_ += static_cast<uint64_t>(step_q30);
    const uint16_t advance = static_cast<uint16_t>(phase_q30_ >> 30U);
    if (advance > 0U) {
      ring.discard(advance);
      phase_q30_ &= (kPhaseOne - 1U);
    }
  }
  ramp_pending_ = false;

  ++controller_ms_;
  if (controller_ms_ >= 8U) {
    controller_ms_ = 0U;
    controller_.update(ring.fill());
  }
  return RenderResult::kAudio;
}

}  // namespace simple_kvm::audio
