#include "hid_handler.h"
#include <stdbool.h>
#include <stdint.h>

bool validate_keyboard_report(const uint8_t *payload, uint8_t len)
{
    if (len < 8) return false;

    // Byte 1 (reserved) must be 0x00 per HID Boot Keyboard spec
    if (payload[1] != 0x00) return false;

    // Validate keycodes (bytes 2-7)
    // Valid: 0x00 (empty), 0x04-0x73 (Keyboard/Keypad Usage IDs)
    for (uint8_t i = 2; i < 8; i++) {
        uint8_t kc = payload[i];
        if (kc == 0x00) continue;
        if (kc >= 0x04 && kc <= 0x73) continue;
        return false;
    }

    return true;
}

bool validate_mouse_report(const uint8_t *payload, uint8_t len)
{
    if (len < 5) return false;

    // Buttons: only bits 0-2 are defined (Left/Right/Middle)
    // Bits 3-7 should be 0
    if (payload[0] & 0xF8) return false;

    return true;
}
