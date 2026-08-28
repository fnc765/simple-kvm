"""Static transport gates for the STM32F103 SPI1 DMA implementation."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_bp1_spi_master_is_mode0_4_5mhz_dma_full_duplex():
    source = _read("firmware/bluepill1/audio_spi_master.cpp")
    assert "SPI1" in source
    assert "SPI_POLARITY_LOW" in source
    assert "SPI_PHASE_1EDGE" in source
    assert "SPI_BAUDRATEPRESCALER_16" in source
    assert "DMA1_Channel2" in source
    assert "DMA1_Channel3" in source
    assert "HAL_SPI_TransmitReceive_DMA" in source
    assert "kSpiFrameBytes" in source
    assert "audio_spi_master_inject_fault" in source
    assert "next-frame CRC corruption" in source
    assert "sequence gap" in source
    assert "kFlagSessionStart | kFlagDiscontinuity | kFlagMute" in source


def test_bp2_spi_slave_is_mode0_and_rearms_dma():
    source = _read("firmware/bluepill2/audio_spi_slave.cpp")
    assert "SPI_MODE_SLAVE" in source
    assert "SPI_POLARITY_LOW" in source
    assert "SPI_PHASE_1EDGE" in source
    assert "SPI_NSS_HARD_INPUT" in source
    assert "DMA1_Channel2" in source
    assert "DMA1_Channel3" in source
    assert "HAL_SPI_TransmitReceive_DMA" in source
    assert "audio_spi_slave_arm" in source


def test_control_path_exposes_run_snapshots_and_idempotent_end_ack():
    bp1 = _read("firmware/bluepill1/main.cpp")
    bp2 = _read("firmware/bluepill2/main.cpp")
    assert "send_bp1_run_snapshot" in bp1
    assert "send_bp2_run_snapshot" in bp2
    assert "pipeline.accept_session_end" in bp2
    assert "send_uart_packet(packet)" in bp2


def test_audio_profiles_connect_spi_transport_only_under_feature_flag():
    bp1 = _read("firmware/bluepill1/main.cpp")
    bp2 = _read("firmware/bluepill2/main.cpp")
    assert "#ifdef SIMPLE_KVM_AUDIO" in bp1
    assert "audio_spi_master_begin" in bp1
    assert "#ifdef SIMPLE_KVM_AUDIO" in bp2
    assert "audio_spi_slave_begin" in bp2
    assert "RCC->CSR" in bp1
    assert "0xEDB88320UL" in bp1
