#include "audio_spi_slave.h"

#include <Arduino.h>
#include <string.h>

#include "../common/audio_frame.h"

namespace simple_kvm::audio::bp2 {
namespace {

// The USB interrupt can briefly hold the main loop for several milliseconds.
// Keep enough RX buffers to absorb that scheduling jitter without overwriting
// an unprocessed DMA frame.  One slot is reserved for the DMA transaction in
// flight, so the ready queue has kRxBufferCount - 1 usable entries.
constexpr uint8_t kRxBufferCount = 16U;
constexpr uint8_t kReadyQueueCapacity = kRxBufferCount - 1U;

SPI_HandleTypeDef g_spi;
DMA_HandleTypeDef g_rx_dma;
DMA_HandleTypeDef g_tx_dma;
uint8_t g_rx_frame[kRxBufferCount][kSpiFrameBytes];
uint8_t g_tx_frame[2][kSpiFrameBytes];
volatile uint8_t g_rx_active = 0U;
volatile uint8_t g_tx_active = 0U;
volatile uint8_t g_ready_queue[kReadyQueueCapacity];
volatile uint8_t g_ready_head = 0U;
volatile uint8_t g_ready_tail = 0U;
volatile uint8_t g_ready_count = 0U;
volatile uint32_t g_pending_overruns = 0U;
volatile bool g_rearm_pending = false;
volatile bool g_short_transfer = false;
volatile bool g_dma_error = false;
// Timestamp the last completed SPI frame in the DMA callback.  The main loop
// can be delayed by USB interrupt work for a few milliseconds; using only the
// processing timestamp would turn that scheduling delay into a false source
// timeout even when SPI has continued to arrive on the wire.
volatile uint32_t g_last_dma_complete_ms = 0U;
volatile uint32_t g_max_dma_gap_ms = 0U;
volatile uint32_t g_last_source_timeout_ms = 0U;
AudioReceivePipeline g_pipeline;

}  // namespace

AudioReceivePipeline& audio_receive_pipeline() { return g_pipeline; }

bool audio_spi_slave_arm()
{
  return HAL_SPI_TransmitReceive_DMA(&g_spi, g_tx_frame[g_tx_active],
                                     g_rx_frame[g_rx_active],
                                     kSpiFrameBytes) == HAL_OK;
}

bool audio_spi_slave_begin()
{
  __HAL_RCC_AFIO_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_DMA1_CLK_ENABLE();
  __HAL_RCC_SPI1_CLK_ENABLE();

  GPIO_InitTypeDef gpio{};
  pinMode(PA4, INPUT_PULLUP);
  gpio.Pin = GPIO_PIN_5 | GPIO_PIN_7;
  gpio.Mode = GPIO_MODE_INPUT;
  gpio.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOA, &gpio);
  gpio.Pin = GPIO_PIN_6;
  gpio.Mode = GPIO_MODE_AF_PP;
  gpio.Speed = GPIO_SPEED_FREQ_HIGH;
  HAL_GPIO_Init(GPIOA, &gpio);

  g_spi.Instance = SPI1;
  g_spi.Init.Mode = SPI_MODE_SLAVE;
  g_spi.Init.Direction = SPI_DIRECTION_2LINES;
  g_spi.Init.DataSize = SPI_DATASIZE_8BIT;
  g_spi.Init.CLKPolarity = SPI_POLARITY_LOW;
  g_spi.Init.CLKPhase = SPI_PHASE_1EDGE;
  g_spi.Init.NSS = SPI_NSS_HARD_INPUT;
  g_spi.Init.FirstBit = SPI_FIRSTBIT_MSB;
  g_spi.Init.TIMode = SPI_TIMODE_DISABLE;
  g_spi.Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
  g_spi.Init.CRCPolynomial = 7U;

  g_rx_dma.Instance = DMA1_Channel2;
  g_rx_dma.Init.Direction = DMA_PERIPH_TO_MEMORY;
  g_rx_dma.Init.PeriphInc = DMA_PINC_DISABLE;
  g_rx_dma.Init.MemInc = DMA_MINC_ENABLE;
  g_rx_dma.Init.PeriphDataAlignment = DMA_PDATAALIGN_BYTE;
  g_rx_dma.Init.MemDataAlignment = DMA_MDATAALIGN_BYTE;
  g_rx_dma.Init.Mode = DMA_NORMAL;
  g_rx_dma.Init.Priority = DMA_PRIORITY_VERY_HIGH;
  if (HAL_DMA_Init(&g_rx_dma) != HAL_OK) {
    return false;
  }
  __HAL_LINKDMA(&g_spi, hdmarx, g_rx_dma);

  g_tx_dma.Instance = DMA1_Channel3;
  g_tx_dma.Init.Direction = DMA_MEMORY_TO_PERIPH;
  g_tx_dma.Init.PeriphInc = DMA_PINC_DISABLE;
  g_tx_dma.Init.MemInc = DMA_MINC_ENABLE;
  g_tx_dma.Init.PeriphDataAlignment = DMA_PDATAALIGN_BYTE;
  g_tx_dma.Init.MemDataAlignment = DMA_MDATAALIGN_BYTE;
  g_tx_dma.Init.Mode = DMA_NORMAL;
  g_tx_dma.Init.Priority = DMA_PRIORITY_HIGH;
  if (HAL_DMA_Init(&g_tx_dma) != HAL_OK) {
    return false;
  }
  __HAL_LINKDMA(&g_spi, hdmatx, g_tx_dma);
  if (HAL_SPI_Init(&g_spi) != HAL_OK) {
    return false;
  }

  // DMA completion must rearm the next frame before the master can start the
  // following NSS window.  Give it precedence over USB endpoint bookkeeping;
  // the callback remains bounded to buffer/counter updates and rearm.
  HAL_NVIC_SetPriority(DMA1_Channel2_IRQn, 0U, 0U);
  HAL_NVIC_EnableIRQ(DMA1_Channel2_IRQn);
  HAL_NVIC_SetPriority(DMA1_Channel3_IRQn, 0U, 0U);
  HAL_NVIC_EnableIRQ(DMA1_Channel3_IRQn);
  memset(g_rx_frame, 0, sizeof(g_rx_frame));
  memset(g_tx_frame, 0, sizeof(g_tx_frame));
  g_rx_active = 0U;
  g_tx_active = 0U;
  g_ready_head = 0U;
  g_ready_tail = 0U;
  g_ready_count = 0U;
  g_pending_overruns = 0U;
  g_rearm_pending = false;
  g_last_dma_complete_ms = 0U;
  g_max_dma_gap_ms = 0U;
  g_last_source_timeout_ms = 0U;
  const AudioStatus status = g_pipeline.status();
  (void)encode_status_frame(status, g_tx_frame[0], kSpiFrameBytes);
  (void)encode_status_frame(status, g_tx_frame[1], kSpiFrameBytes);
  return audio_spi_slave_arm();
}

void audio_spi_slave_poll(uint32_t now_ms)
{
  g_pipeline.update_uptime(now_ms);
  uint32_t pending_overruns = 0U;
  uint32_t last_dma_complete_ms = 0U;
  bool rearm_pending = false;
  noInterrupts();
  const bool explicit_error = g_short_transfer || g_dma_error;
  g_short_transfer = false;
  g_dma_error = false;
  rearm_pending = g_rearm_pending;
  g_rearm_pending = false;
  pending_overruns = g_pending_overruns;
  g_pending_overruns = 0U;
  last_dma_complete_ms = g_last_dma_complete_ms;
  interrupts();

  if (explicit_error || rearm_pending) {
    (void)HAL_SPI_Abort(&g_spi);
    if (explicit_error) {
      g_pipeline.note_short_transfer();
    }
    if (!audio_spi_slave_arm()) {
      noInterrupts();
      g_rearm_pending = true;
      interrupts();
    }
  }

  while (true) {
    uint8_t ready = 0U;
    noInterrupts();
    if (g_ready_count == 0U) {
      interrupts();
      break;
    }
    ready = g_ready_queue[g_ready_tail];
    g_ready_tail = static_cast<uint8_t>(
        (g_ready_tail + 1U) % kReadyQueueCapacity);
    --g_ready_count;
    interrupts();
    (void)g_pipeline.process_frame(g_rx_frame[ready], kSpiFrameBytes, now_ms);
  }
  while (pending_overruns > 0U) {
    g_pipeline.note_overrun();
    --pending_overruns;
  }
  const bool dma_recent =
      last_dma_complete_ms != 0U &&
      static_cast<uint32_t>(now_ms - last_dma_complete_ms) < 3U;
  if (!dma_recent) {
    if (g_pipeline.source_timeout(now_ms)) {
      g_last_source_timeout_ms = now_ms;
    }
  }

  const AudioStatus status = g_pipeline.status();
  noInterrupts();
  const uint8_t inactive = static_cast<uint8_t>(g_tx_active ^ 1U);
  (void)encode_status_frame(status, g_tx_frame[inactive], kSpiFrameBytes);
  interrupts();
}

}  // namespace simple_kvm::audio::bp2

extern "C" void DMA1_Channel2_IRQHandler(void)
{
  HAL_DMA_IRQHandler(&simple_kvm::audio::bp2::g_rx_dma);
}

extern "C" void DMA1_Channel3_IRQHandler(void)
{
  HAL_DMA_IRQHandler(&simple_kvm::audio::bp2::g_tx_dma);
}

extern "C" void HAL_SPI_TxRxCpltCallback(SPI_HandleTypeDef* spi)
{
  using namespace simple_kvm::audio::bp2;
  if (spi != &g_spi) {
    return;
  }
  const uint8_t completed = g_rx_active;
  if (g_ready_count >= kReadyQueueCapacity) {
    // Drop the oldest unprocessed frame.  This is the only safe buffer to
    // recycle when the queue is full; the just-completed frame is preserved.
    g_ready_tail = static_cast<uint8_t>(
        (g_ready_tail + 1U) % kReadyQueueCapacity);
    --g_ready_count;
    ++g_pending_overruns;
  }
  g_ready_queue[g_ready_head] = completed;
  g_ready_head = static_cast<uint8_t>(
      (g_ready_head + 1U) % kReadyQueueCapacity);
  ++g_ready_count;
  const uint32_t now_ms = HAL_GetTick();
  const uint32_t previous_ms = g_last_dma_complete_ms;
  if (previous_ms != 0U) {
    const uint32_t gap_ms = now_ms - previous_ms;
    if (gap_ms > g_max_dma_gap_ms) {
      g_max_dma_gap_ms = gap_ms;
    }
  }
  g_last_dma_complete_ms = now_ms;
  g_rx_active = static_cast<uint8_t>(
      (g_rx_active + 1U) % kRxBufferCount);
  g_tx_active ^= 1U;
  // The RX DMA callback can run before the TX DMA IRQ has finished clearing
  // its channel.  A transient HAL_BUSY is therefore a rearm scheduling race,
  // not a short wire transaction.  Retry from the main loop after both DMA
  // IRQs have quiesced, without manufacturing a diagnostic error counter.
  if (!audio_spi_slave_arm()) {
    g_rearm_pending = true;
  }
}

extern "C" void HAL_SPI_ErrorCallback(SPI_HandleTypeDef* spi)
{
  if (spi == &simple_kvm::audio::bp2::g_spi) {
    simple_kvm::audio::bp2::g_dma_error = true;
  }
}
