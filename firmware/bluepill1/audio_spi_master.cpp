#include "audio_spi_master.h"

#include <Arduino.h>
#include <string.h>

#include "audio_usb_out.h"
#include "../common/audio_frame.h"

namespace simple_kvm::audio::bp1 {
namespace {

SPI_HandleTypeDef g_spi;
DMA_HandleTypeDef g_rx_dma;
DMA_HandleTypeDef g_tx_dma;
uint8_t g_tx_frame[kSpiFrameBytes];
uint8_t g_rx_frame[kSpiFrameBytes];
volatile bool g_dma_complete = false;
volatile bool g_dma_error = false;
bool g_busy = false;
uint16_t g_sequence = 0U;
uint32_t g_last_overwrite = 0U;
Bp1Diagnostics g_diagnostics{};
RunSnapshotStore g_snapshots;
uint8_t g_last_usb_state = 0U;
bool g_have_usb_state = false;
#ifdef AUDIO_TEST_HOOKS
uint8_t g_test_fault = 0U;
#endif

void end_transaction()
{
  uint32_t wait = 2048U;
  while (__HAL_SPI_GET_FLAG(&g_spi, SPI_FLAG_BSY) != RESET && wait > 0U) {
    --wait;
  }
  digitalWrite(PA4, HIGH);
  if (wait == 0U || g_dma_error) {
    ++g_diagnostics.spi_deadline_miss;
    (void)HAL_SPI_Abort(&g_spi);
  }
  g_busy = false;
  g_dma_complete = false;
  g_dma_error = false;

  AudioStatus status{};
  if (!decode_status_frame(g_rx_frame, sizeof(g_rx_frame), status)) {
    if ((g_diagnostics.spi_pcm_frames + g_diagnostics.spi_control_frames) > 1U) {
      ++g_diagnostics.spi_status_crc_error;
    }
  }
}

void make_frame(const TransportEvent& event)
{
  AudioFrame frame{};
  frame.sequence = g_sequence++;
  frame.boot_nonce = event.boot_nonce;
  frame.session_counter = event.session_counter;
  switch (event.type) {
    case TransportEventType::kPcm:
      frame.flags = kFlagValid;
      frame.sample_count = kSamplesPerUsbFrame;
      memcpy(frame.pcm, event.pcm, kUsbPacketBytes);
      ++g_diagnostics.spi_pcm_frames;
      break;
    case TransportEventType::kSessionStart:
      frame.flags = kFlagSessionStart | kFlagDiscontinuity | kFlagMute;
      ++g_diagnostics.audio_source_session_starts;
      ++g_diagnostics.spi_control_frames;
      break;
    case TransportEventType::kSessionEnd:
      frame.flags = kFlagSessionEnd | kFlagMute;
      ++g_diagnostics.audio_source_session_ends;
      ++g_diagnostics.spi_control_frames;
      break;
    case TransportEventType::kRunStart:
    case TransportEventType::kRunEnd: {
      frame.flags = event.type == TransportEventType::kRunStart
                        ? kFlagRunStart
                        : kFlagRunEnd;
      set_run_id(frame, event.run_id);
      RunSnapshot snapshot{};
      snapshot.run_id = event.run_id;
      snapshot.marker = event.type == TransportEventType::kRunStart
                            ? RunMarker::kStart
                            : RunMarker::kEnd;
      snapshot.marker_sequence = frame.sequence;
      snapshot.usb_audio_boundary = event.usb_audio_boundary;
      snapshot.spi_pcm_frames = g_diagnostics.spi_pcm_frames;
      snapshot.error_count = g_diagnostics.spi_deadline_miss +
                             g_diagnostics.spi_status_crc_error;
      snapshot.session_counter = event.session_counter;
      snapshot.audio_alt = usb_audio_alt();
      (void)g_snapshots.record(snapshot);
      ++g_diagnostics.spi_control_frames;
      break;
    }
  }
  (void)encode_audio_frame(frame, g_tx_frame, sizeof(g_tx_frame));
#ifdef AUDIO_TEST_HOOKS
  if (g_test_fault == 1U) {
    g_tx_frame[kSpiFrameBytes - 1U] ^= 0x01U;  // next-frame CRC corruption
  } else if (g_test_fault == 2U) {
    ++g_sequence;  // next valid frame exposes a deterministic sequence gap
  }
  g_test_fault = 0U;
#endif
}

}  // namespace

bool audio_spi_master_begin()
{
  __HAL_RCC_AFIO_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_DMA1_CLK_ENABLE();
  __HAL_RCC_SPI1_CLK_ENABLE();

  GPIO_InitTypeDef gpio{};
  gpio.Pin = GPIO_PIN_5 | GPIO_PIN_7;
  gpio.Mode = GPIO_MODE_AF_PP;
  gpio.Speed = GPIO_SPEED_FREQ_HIGH;
  HAL_GPIO_Init(GPIOA, &gpio);
  gpio.Pin = GPIO_PIN_6;
  gpio.Mode = GPIO_MODE_INPUT;
  gpio.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOA, &gpio);
  pinMode(PA4, OUTPUT);
  digitalWrite(PA4, HIGH);

  g_spi.Instance = SPI1;
  g_spi.Init.Mode = SPI_MODE_MASTER;
  g_spi.Init.Direction = SPI_DIRECTION_2LINES;
  g_spi.Init.DataSize = SPI_DATASIZE_8BIT;
  g_spi.Init.CLKPolarity = SPI_POLARITY_LOW;
  g_spi.Init.CLKPhase = SPI_PHASE_1EDGE;
  g_spi.Init.NSS = SPI_NSS_SOFT;
  g_spi.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_16;
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
  return true;
}

void audio_spi_master_poll(uint32_t now_ms)
{
  (void)now_ms;
  if (g_busy) {
    if (g_dma_complete || g_dma_error) {
      end_transaction();
    } else if (usb_audio_queue_fill() > 0U) {
      ++g_diagnostics.spi_dma_busy;
    }
    return;
  }
  const uint32_t overwrite = usb_audio_overwrite_count();
  g_diagnostics.spi_deadline_miss += overwrite - g_last_overwrite;
  g_last_overwrite = overwrite;

  TransportEvent event{};
  if (!pop_transport_event(event)) {
    return;
  }
  make_frame(event);
  memset(g_rx_frame, 0, sizeof(g_rx_frame));
  g_dma_complete = false;
  g_dma_error = false;
  g_busy = true;
  digitalWrite(PA4, LOW);
  if (HAL_SPI_TransmitReceive_DMA(&g_spi, g_tx_frame, g_rx_frame,
                                  kSpiFrameBytes) != HAL_OK) {
    digitalWrite(PA4, HIGH);
    g_busy = false;
    ++g_diagnostics.spi_deadline_miss;
  }
  g_diagnostics.usb_audio_packets = usb_audio_packet_count();
  g_diagnostics.usb_audio_bytes = usb_audio_byte_count();
  g_diagnostics.usb_audio_bad_size = usb_audio_bad_size_count();
  g_diagnostics.usb_audio_short = usb_audio_short_count();
  g_diagnostics.usb_audio_alt_transitions =
      usb_audio_alt_transition_count();
  g_diagnostics.usb_audio_overwrite = usb_audio_overwrite_count();
  g_diagnostics.audio_source_boot_nonce = audio_boot_nonce();
  g_diagnostics.audio_source_session_counter = audio_session_counter();
  g_diagnostics.usb_audio_alt = usb_audio_alt();
}

bool audio_spi_master_busy() { return g_busy; }
const Bp1Diagnostics& audio_spi_master_diagnostics() { return g_diagnostics; }
const RunSnapshotStore& audio_spi_master_snapshots() { return g_snapshots; }
void audio_spi_master_update_control_diagnostics(
    uint32_t uptime_ms, uint32_t sync_request_id, uint32_t sync_send_count,
    bool sync_acked, uint8_t boot_queue_high_water,
    uint32_t boot_queue_overflow)
{
  g_diagnostics.uptime_ms = uptime_ms;
  g_diagnostics.sync_request_id = sync_request_id;
  g_diagnostics.audio_control_sync_requests = sync_send_count;
  g_diagnostics.audio_control_sync_retries =
      sync_send_count > 0U ? sync_send_count - 1U : 0U;
  g_diagnostics.audio_control_sync_acks = sync_acked ? 1U : 0U;
  g_diagnostics.hid_boot_queue_high_water = boot_queue_high_water;
  g_diagnostics.hid_boot_queue_overflow = boot_queue_overflow;
}
void audio_spi_master_note_usb_state(uint8_t state, uint8_t default_state,
                                     uint8_t suspended_state)
{
  if (!g_have_usb_state) {
    g_last_usb_state = state;
    g_have_usb_state = true;
    return;
  }
  if (state == g_last_usb_state) return;
  if (state == default_state) ++g_diagnostics.usb_audio_reset;
  if (state == suspended_state) {
    ++g_diagnostics.usb_audio_suspend;
  } else if (g_last_usb_state == suspended_state) {
    ++g_diagnostics.usb_audio_resume;
  }
  g_last_usb_state = state;
}
void audio_spi_master_set_reset_reason(ResetReason reason)
{
  g_diagnostics.reset_reason = reason;
}
#ifdef AUDIO_TEST_HOOKS
void audio_spi_master_inject_fault(uint8_t fault) { g_test_fault = fault; }
#endif

}  // namespace simple_kvm::audio::bp1

extern "C" void DMA1_Channel2_IRQHandler(void)
{
  HAL_DMA_IRQHandler(&simple_kvm::audio::bp1::g_rx_dma);
}

extern "C" void DMA1_Channel3_IRQHandler(void)
{
  HAL_DMA_IRQHandler(&simple_kvm::audio::bp1::g_tx_dma);
}

extern "C" void HAL_SPI_TxRxCpltCallback(SPI_HandleTypeDef* spi)
{
  if (spi == &simple_kvm::audio::bp1::g_spi) {
    simple_kvm::audio::bp1::g_dma_complete = true;
  }
}

extern "C" void HAL_SPI_ErrorCallback(SPI_HandleTypeDef* spi)
{
  if (spi == &simple_kvm::audio::bp1::g_spi) {
    simple_kvm::audio::bp1::g_dma_error = true;
  }
}
