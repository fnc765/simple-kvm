#include <cstdint>
#include <cstdio>
#include <cstring>

#include "audio_frame.h"
#include "audio_pipeline.h"

// Only MCU I/O is replaced. The fixture contains the product poll function
// and state verbatim, and the observer below calls the real frame encoder.
struct SPI_HandleTypeDef {};
struct DMA_HandleTypeDef {};
static bool irq_enabled = true;
static bool encoder_blocked_uart = false;
static bool complete_dma_during_encoding = false;
static unsigned encoder_calls = 0U;

static void noInterrupts() { irq_enabled = false; }
static void interrupts() { irq_enabled = true; }
static int HAL_SPI_Abort(SPI_HandleTypeDef*) { return 0; }

namespace simple_kvm::audio::bp2 {
bool audio_spi_slave_arm() { return true; }
struct StatusEncoderObserver {
  bool operator()(const AudioStatus&, uint8_t*, size_t) const;
};
static const StatusEncoderObserver encode_status_frame{};
}

#include "bp2_spi_poll_fixture.h"

namespace simple_kvm::audio::bp2 {
// Instrument entry/exit without replacing any encoding behavior. A DMA
// completion between encoding and publication must change the target slot.
bool StatusEncoderObserver::operator()(const AudioStatus& status, uint8_t* output,
                                       size_t length) const
{
  ++encoder_calls;
  encoder_blocked_uart |= !irq_enabled;
  const bool result = simple_kvm::audio::encode_status_frame(status, output, length);
  if (complete_dma_during_encoding && irq_enabled) {
    g_tx_active ^= 1U;
  }
  return result;
}
}

#define SPI_CHECK(condition)                                                   \
  do {                                                                        \
    if (!(condition)) {                                                       \
      std::fprintf(stderr, "SPI_POLL_FAIL test=%s line=%d\n", #condition, __LINE__); \
      return 1;                                                               \
    }                                                                         \
  } while (0)

int run_bp2_spi_poll_tests()
{
  using namespace simple_kvm::audio;
  using namespace simple_kvm::audio::bp2;
  for (unsigned initial = 0U; initial < 2U; ++initial) {
    for (unsigned complete = 0U; complete < 2U; ++complete) {
      std::memset(g_tx_frame, 0xCC, sizeof(g_tx_frame));
      g_tx_active = static_cast<uint8_t>(initial);
      irq_enabled = true;
      encoder_blocked_uart = false;
      complete_dma_during_encoding = complete != 0U;
      const unsigned before = encoder_calls;
      audio_spi_slave_poll(100U);
      SPI_CHECK(irq_enabled);
      SPI_CHECK(!encoder_blocked_uart);
      SPI_CHECK(encoder_calls == before + 1U);
      SPI_CHECK(g_tx_active == static_cast<uint8_t>(initial ^ complete));
      for (size_t index = 0U; index < kSpiFrameBytes; ++index) {
        SPI_CHECK(g_tx_frame[g_tx_active][index] == 0xCC);
      }
      AudioStatus observed{};
      SPI_CHECK(decode_status_frame(g_tx_frame[g_tx_active ^ 1U], kSpiFrameBytes,
                                    observed));
      uint8_t expected[kSpiFrameBytes];
      SPI_CHECK(simple_kvm::audio::encode_status_frame(g_pipeline.status(), expected,
                                                       sizeof(expected)));
      SPI_CHECK(std::memcmp(expected, g_tx_frame[g_tx_active ^ 1U], sizeof(expected)) == 0);
    }
  }
  std::printf("BP2_SPI_POLL_PASS cases=4\n");
  return 0;
}
