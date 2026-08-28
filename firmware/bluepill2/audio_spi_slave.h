#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "../common/audio_pipeline.h"

namespace simple_kvm::audio::bp2 {

bool audio_spi_slave_begin();
bool audio_spi_slave_arm();
void audio_spi_slave_poll(uint32_t now_ms);
AudioReceivePipeline& audio_receive_pipeline();

}  // namespace simple_kvm::audio::bp2
