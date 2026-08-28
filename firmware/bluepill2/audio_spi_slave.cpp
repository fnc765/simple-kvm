#include "audio_spi_slave.h"

#include <Arduino.h>
#include <string.h>

#include "../common/audio_frame.h"

namespace simple_kvm::audio::bp2 {
namespace {

SPI_HandleTypeDef g_spi;
DMA_HandleTypeDef g_rx_dma;
DMA_HandleTypeDef g_tx_dma;
uint8_t g_rx_frame[2][kSpiFrameBytes];
uint8_t g_tx_frame[2][kSpiFrameBytes];
volatile uint8_t g_active = 0U;
volatile uint8_t g_ready = 0U;
volatile bool g_pending = false;
volatile bool g_short_transfer = false;
volatile bool g_dma_error = false;
AudioReceivePipeline g_pipeline;

void on_nss_rise()
{
  if (g_spi.State == HAL_SPI_STATE_BUSY_TX_RX &&
      __HAL_DMA_GET_COUNTER(&g_rx_dma) != 0U) {
    g_short_transfer = true;
  }
}

}  // namespace

AudioReceivePipeline& audio_receive_pipeline() { return g_pipeline; }

bool audio_spi_slave_arm()
{
  return HAL_SPI_TransmitReceive_DMA(&g_spi, g_tx_frame[g_active],
                                     g_rx_frame[g_active],
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
  attachInterrupt(digitalPinToInterrupt(PA4), on_nss_rise, RISING);
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

  HAL_NVIC_SetPriority(DMA1_Channel2_IRQn, 2U, 0U);
  HAL_NVIC_EnableIRQ(DMA1_Channel2_IRQn);
  HAL_NVIC_SetPriority(DMA1_Channel3_IRQn, 2U, 0U);
  HAL_NVIC_EnableIRQ(DMA1_Channel3_IRQn);
  memset(g_rx_frame, 0, sizeof(g_rx_frame));
  const AudioStatus status = g_pipeline.status();
  (void)encode_status_frame(status, g_tx_frame[0], kSpiFrameBytes);
  (void)encode_status_frame(status, g_tx_frame[1], kSpiFrameBytes);
  return audio_spi_slave_arm();
}

void audio_spi_slave_poll(uint32_t now_ms)
{
  g_pipeline.update_uptime(now_ms);
  if (g_short_transfer || g_dma_error) {
    noInterrupts();
    g_short_transfer = false;
    g_dma_error = false;
    interrupts();
    (void)HAL_SPI_Abort(&g_spi);
    g_pipeline.note_short_transfer();
    (void)audio_spi_slave_arm();
  }

  if (g_pending) {
    noInterrupts();
    const uint8_t ready = g_ready;
    g_pending = false;
    interrupts();
    (void)g_pipeline.process_frame(g_rx_frame[ready], kSpiFrameBytes, now_ms);
  }
  (void)g_pipeline.source_timeout(now_ms);

  const AudioStatus status = g_pipeline.status();
  const uint8_t inactive = static_cast<uint8_t>(g_active ^ 1U);
  (void)encode_status_frame(status, g_tx_frame[inactive], kSpiFrameBytes);
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
  if (g_pending) {
    g_pipeline.note_overrun();
  }
  g_ready = g_active;
  g_pending = true;
  g_active ^= 1U;
  (void)audio_spi_slave_arm();
}

extern "C" void HAL_SPI_ErrorCallback(SPI_HandleTypeDef* spi)
{
  if (spi == &simple_kvm::audio::bp2::g_spi) {
    simple_kvm::audio::bp2::g_dma_error = true;
  }
}
