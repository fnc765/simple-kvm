#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "../common/audio_diag.h"
#include "../common/audio_session.h"

namespace simple_kvm::audio::bp1 {

bool audio_spi_master_begin();
void audio_spi_master_poll(uint32_t now_ms);
bool audio_spi_master_busy();
const Bp1Diagnostics& audio_spi_master_diagnostics();
const RunSnapshotStore& audio_spi_master_snapshots();
void audio_spi_master_update_control_diagnostics(
    uint32_t uptime_ms, uint32_t sync_request_id, uint32_t sync_send_count,
    bool sync_acked, uint8_t boot_queue_high_water,
    uint32_t boot_queue_overflow);
void audio_spi_master_note_usb_state(uint8_t state, uint8_t default_state,
                                     uint8_t suspended_state);
void audio_spi_master_set_reset_reason(ResetReason reason);
#ifdef AUDIO_TEST_HOOKS
void audio_spi_master_inject_fault(uint8_t fault);
#endif

}  // namespace simple_kvm::audio::bp1
