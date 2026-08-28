#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

void bp2_audio_mic_on_alt(uint8_t alt);
void bp2_audio_mic_fill_packet(uint8_t* output, uint16_t length);
void bp2_audio_mic_set_test_tone(bool enabled);

#ifdef __cplusplus
}
#endif
