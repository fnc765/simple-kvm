/**
 * bluepill2  –  UART1 → USB HID Composite (Keyboard + Mouse)
 * (PlatformIO 用エントリポイント。Arduino IDE では bluepill2.ino を使用)
 *
 * Hardware:
 *   PA11/PA12  USB D-/D+  →  Target PC (HID Composite)
 *   PA10 RX1              ←  BluePill #1 PA9 (TX)
 *   PA9  TX1              →  BluePill #1 PA10 (RX)  [ACK, future use]
 *   PC13 (Active-Low LED) –  Status
 *
 * USB: STM32duino 内蔵 USBD_USE_HID_COMPOSITE
 *   HID mouse report  : 4 bytes [buttons, dx, dy, wheel_v]
 *   HID keyboard report: 8 bytes (Boot Keyboard)
 *
 * Note: arpruss/USBComposite_stm32f1 は旧 libmaple 向けのため使用不可。
 *       代わりに STM32duino フレームワーク内蔵の HID_Composite_* API を使用。
 */

#include <Arduino.h>
#include "usbd_hid_composite_if.h"
#include "packet_parser.h"
#include "hid_handler.h"

// ----- Parser state ----------------------------------------------------------
static PacketParser g_parser;
static Packet       g_pkt;

// ----- LED -------------------------------------------------------------------
#define LED_PIN PC13  // Active-Low

// ----- Mouse button state (accumulated, sent with every report) --------------
static uint8_t g_buttons = 0;

// ----- HID report helpers ----------------------------------------------------

/**
 * Send an 8-byte HID Boot Keyboard report via STM32duino composite HID.
 */
static void hid_send_keyboard(const Packet *p)
{
    if (p->len != PKT_LEN_KEYBOARD) return;
    // payload matches HID Boot Keyboard layout directly
    HID_Composite_keyboard_sendReport(const_cast<uint8_t *>(p->payload),
                                       PKT_LEN_KEYBOARD);
}

/**
 * Send a 4-byte HID mouse report: [buttons, dx, dy, wheel_v].
 * The built-in composite descriptor does not include horizontal scroll (wheel_h).
 */
static void hid_send_mouse(const Packet *p)
{
    if (p->len != PKT_LEN_MOUSE) return;

    const KVMMouseReport *rpt = reinterpret_cast<const KVMMouseReport *>(p->payload);

    // Update persistent button state
    g_buttons = rpt->buttons;

    // Build 4-byte mouse report
    uint8_t report[4];
    report[0] = g_buttons;
    report[1] = static_cast<uint8_t>(rpt->dx);
    report[2] = static_cast<uint8_t>(rpt->dy);
    report[3] = static_cast<uint8_t>(rpt->wheel_v);

    HID_Composite_mouse_sendReport(report, sizeof(report));
}

// ----- Setup / Loop ----------------------------------------------------------

void setup()
{
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, HIGH); // Active-Low → OFF

    // UART1 from BP1  PA10=RX, PA9=TX  (initialise before USB)
    Serial1.begin(115200UL);

    parser_init(&g_parser);

    // USB HID Composite initialisation (STM32duino native)
    // Calling with HID_KEYBOARD initialises both keyboard and mouse interfaces
    HID_Composite_Init(HID_KEYBOARD);

    // Give the host time to enumerate (≤5 s)
    delay(200);
}

void loop()
{
    while (Serial1.available()) {
        uint8_t b = static_cast<uint8_t>(Serial1.read());
        if (parser_feed(&g_parser, b, &g_pkt)) {
            switch (g_pkt.type) {
                case PKT_KEYBOARD:
                    hid_send_keyboard(&g_pkt);
                    break;

                case PKT_MOUSE:
                    hid_send_mouse(&g_pkt);
                    break;

                case PKT_HEARTBEAT:
                    digitalWrite(LED_PIN, !digitalRead(LED_PIN));
                    break;

                default:
                    break;
            }
        }
    }
}
