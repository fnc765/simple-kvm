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


def test_bp2_spi_slave_buffers_usb_jitter_and_drains_ready_frames():
    source = _read("firmware/bluepill2/audio_spi_slave.cpp")
    assert "kRxBufferCount = 16U" in source
    assert "kReadyQueueCapacity = kRxBufferCount - 1U" in source
    assert "g_ready_queue" in source
    assert "g_pending_overruns" in source
    assert "g_rearm_pending" in source
    assert "HAL_SPI_Abort" in source
    assert "while (true)" in source
    assert "g_pipeline.note_overrun()" in source
    assert "g_rx_active = static_cast<uint8_t>" in source


def test_audio_status_pages_expose_counter_breakdown():
    bp1 = _read("firmware/bluepill1/main.cpp")
    bp2 = _read("firmware/bluepill2/main.cpp")
    probe = _read("tools/audio_test/_bp_e2e_probe.py")
    assert "bp1_status_values" in bp1
    assert "bp2_status_values" in bp2
    assert "case 2U:  // transport loss" in bp2
    assert "diag.spi_sequence_gap" in bp2
    assert "diag.spi_overrun" in bp2
    assert "diag.underflow" in bp2
    assert "read_status_pages" in probe
    assert "STATUS_PAGES_BEFORE" in probe
    assert "STATUS_PAGES_AFTER" in probe


def test_bp2_audio_usb_callback_does_not_render_asrc_in_usb_irq():
    source = _read("firmware/bluepill2/usbd_hid_audio_composite_patch.c")
    datain = source.split("static uint8_t audio_datain", 1)[1].split(
        "void bp2_audio_mic_service", 1
    )[0]
    assert "bp2_audio_mic_fill_packet" not in datain
    assert "AUDIO_PACKET_READY" in datain
    assert "bp2_audio_mic_note_packet" in datain
    assert "bp2_audio_mic_fill_packet" in source.split(
        "void bp2_audio_mic_service", 1
    )[1]
    assert "HAL_NVIC_SetPriority(DMA1_Channel2_IRQn, 0U, 0U)" in _read(
        "firmware/bluepill2/audio_spi_slave.cpp"
    )
    assert "HAL_NVIC_SetPriority(DMA1_Channel3_IRQn, 0U, 0U)" in _read(
        "firmware/bluepill2/audio_spi_slave.cpp"
    )


def test_audio_probe_capture_artifact_is_repo_relative():
    probe = _read("tools/audio_test/_bp_e2e_probe.py")
    assert "REPO_ROOT = Path(__file__).resolve().parents[2]" in probe
    assert "REPO_ROOT / \".pio\" / \"bp2_e2e_capture.raw\"" in probe
    assert "capture_path.parent.mkdir(parents=True, exist_ok=True)" in probe


def test_control_path_exposes_run_snapshots_and_idempotent_end_ack():
    bp1 = _read("firmware/bluepill1/main.cpp")
    bp2 = _read("firmware/bluepill2/main.cpp")
    assert "send_bp1_run_snapshot" in bp1
    assert "send_bp2_run_snapshot" in bp2
    assert "pipeline.accept_session_end" in bp2
    assert "send_uart_packet(packet)" in bp2


def test_bp1_audio_sync_heartbeat_keeps_receiver_recoverable():
    source = _read("firmware/bluepill1/main.cpp")
    assert "send_sync_heartbeat" in source
    assert "g_last_sync_heartbeat_ms" in source
    assert ">= 1000U" in source
    assert "g_sync.acked()" in source


def test_audio_profiles_connect_spi_transport_only_under_feature_flag():
    bp1 = _read("firmware/bluepill1/main.cpp")
    bp2 = _read("firmware/bluepill2/main.cpp")
    assert "#ifdef SIMPLE_KVM_AUDIO" in bp1
    assert "audio_spi_master_begin" in bp1
    assert "#ifdef SIMPLE_KVM_AUDIO" in bp2
    assert "audio_spi_slave_begin" in bp2
    assert "RCC->CSR" in bp1
    assert "0xEDB88320UL" in bp1
