#pragma once

#include <stddef.h>
#include <stdint.h>

#include "audio_format.h"
#include "audio_ring.h"

namespace simple_kvm::audio {

constexpr int32_t kAsrcClampPpm = 2000;

class AsrcController {
 public:
  AsrcController();
  void reset();
  void update(uint16_t fill);
  void set_step_ppm_for_test(int32_t ppm);

  int32_t step_ppm() const { return step_ppm_; }
  int32_t integral_q16() const { return integral_q16_; }
  uint32_t clamp_count() const { return clamp_count_; }

 private:
  int32_t integral_q16_;
  int32_t step_ppm_;
  uint32_t clamp_count_;
};

enum class RenderResult : uint8_t {
  kAudio = 0,
  kPrefill,
  kUnderflow,
};

class AudioAsrc {
 public:
  AudioAsrc();
  void reset();
  RenderResult render(AudioRing& ring, int16_t* output, size_t count);
  void set_step_ppm_for_test(int32_t ppm) {
    controller_.set_step_ppm_for_test(ppm);
  }

  bool prefilling() const { return prefilling_; }
  int32_t step_ppm() const { return controller_.step_ppm(); }
  int32_t integral_q16() const { return controller_.integral_q16(); }
  uint32_t underflow_count() const { return underflow_count_; }
  uint32_t prefill_count() const { return prefill_count_; }
  uint32_t clamp_count() const { return controller_.clamp_count(); }

 private:
  static constexpr uint64_t kPhaseOne = 1ULL << 30U;
  AsrcController controller_;
  uint64_t phase_q30_;
  uint8_t controller_ms_;
  bool prefilling_;
  bool ramp_pending_;
  uint32_t underflow_count_;
  uint32_t prefill_count_;
};

}  // namespace simple_kvm::audio
