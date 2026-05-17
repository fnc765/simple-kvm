#pragma once
#include <stdint.h>

// ---------------------------------------------------------------------------
// HID Report Structures (USB HID Keyboard/Keypad & Generic Desktop Usage Pages)
// ---------------------------------------------------------------------------

/**
 * 8-byte HID Boot Keyboard Report.
 *
 * Layout (matches USB HID Boot Keyboard protocol):
 *   [0] modifier  – bitmask: bit0=LCtrl bit1=LShift bit2=LAlt bit3=LGUI
 *                            bit4=RCtrl bit5=RShift bit6=RAlt bit7=RGUI
 *   [1] reserved  – always 0x00
 *   [2..7] keys   – up to 6 simultaneous HID Usage IDs (0x00 = empty slot)
 *
 * This struct overlays the uint8_t payload[] from the packet parser, so it
 * can be cast from the raw payload array without copying.
 */
typedef struct __attribute__((packed)) {
    uint8_t modifier;
    uint8_t reserved;   // 0x00
    uint8_t keys[6];    // HID Usage IDs; 0x00 = empty
} KVMKeyboardReport;

/**
 * 5-byte HID Mouse Report (relative mode).
 *
 *   [0] buttons  – bit0=Left, bit1=Right, bit2=Middle
 *   [1] dx       – int8  relative X  (-127..+127)
 *   [2] dy       – int8  relative Y  (-127..+127)
 *   [3] wheel_v  – int8  vertical scroll
 *   [4] wheel_h  – int8  horizontal scroll (not all targets support)
 */
typedef struct __attribute__((packed)) {
    uint8_t buttons;
    int8_t  dx;
    int8_t  dy;
    int8_t  wheel_v;
    int8_t  wheel_h;
} KVMMouseReport;

// Convenience bitmasks
#define MOUSE_BTN_LEFT   0x01u
#define MOUSE_BTN_RIGHT  0x02u
#define MOUSE_BTN_MIDDLE 0x04u

// HID report validation
bool validate_keyboard_report(const uint8_t *payload, uint8_t len);
bool validate_mouse_report(const uint8_t *payload, uint8_t len);
