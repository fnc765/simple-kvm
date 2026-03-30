/**
 * bluepill2.ino  –  UART1 → USB HID Composite (Keyboard + Mouse)
 *
 * Hardware:
 *   PA11/PA12  USB D-/D+  →  Target PC (HID Composite)
 *   PA10 RX1              ←  BluePill #1 PA9 (TX)
 *   PA9  TX1              →  BluePill #1 PA10 (RX)  [ACK, future use]
 *   PC13 (Active-Low LED) –  Status
 *
 * Required library:
 *   arpruss/USBComposite_stm32f1
 *   Install via Arduino Library Manager or:
 *   https://github.com/arpruss/USBComposite_stm32f1
 *
 * Board settings (Arduino IDE):
 *   Board      : Generic STM32F103C series
 *   Variant    : STM32F103C8 (Blue Pill)
 *   USB support: No USB  ← USB is managed by USBComposite; do NOT select CDC
 *   Upload     : STLink or HID bootloader
 *
 * Note: USB CDC and HID cannot coexist on STM32F103.
 *       Debug output must use Serial1 (UART1) if needed.
 */

#include <USBComposite.h>
#include "packet_parser.h"
#include "hid_handler.h"

// ----- USB HID objects -------------------------------------------------------
USBHID      HID;
HIDKeyboard Keyboard(HID);
HIDMouse    Mouse(HID);

// ----- Parser state ----------------------------------------------------------
static PacketParser g_parser;
static Packet       g_pkt;

// ----- LED -------------------------------------------------------------------
#define LED_PIN PC13  // Active-Low

// ----- Previous button state (for press/release tracking) -------------------
static uint8_t g_prev_buttons = 0;

// ----- Helpers ---------------------------------------------------------------

static void handle_keyboard(const Packet *p)
{
    if (p->len != PKT_LEN_KEYBOARD) return;

    // Copy payload into a properly typed HIDKeyReport to avoid strict-aliasing issues
    HIDKeyReport hidRpt;
    memcpy(&hidRpt, p->payload, sizeof(hidRpt));
    Keyboard.sendReport(&hidRpt);
}

static void handle_mouse(const Packet *p)
{
    if (p->len != PKT_LEN_MOUSE) return;

    const KVMMouseReport *rpt = (const KVMMouseReport *)p->payload;

    // --- Button state changes -----------------------------------------------
    uint8_t changed = g_prev_buttons ^ rpt->buttons;
    if (changed) {
        if (changed & MOUSE_BTN_LEFT) {
            if (rpt->buttons & MOUSE_BTN_LEFT) Mouse.press(MOUSE_LEFT);
            else                                Mouse.release(MOUSE_LEFT);
        }
        if (changed & MOUSE_BTN_RIGHT) {
            if (rpt->buttons & MOUSE_BTN_RIGHT) Mouse.press(MOUSE_RIGHT);
            else                                 Mouse.release(MOUSE_RIGHT);
        }
        if (changed & MOUSE_BTN_MIDDLE) {
            if (rpt->buttons & MOUSE_BTN_MIDDLE) Mouse.press(MOUSE_MIDDLE);
            else                                  Mouse.release(MOUSE_MIDDLE);
        }
        g_prev_buttons = rpt->buttons;
    }

    // --- Movement & scroll --------------------------------------------------
    if (rpt->dx || rpt->dy || rpt->wheel_v || rpt->wheel_h) {
        Mouse.move(rpt->dx, rpt->dy, rpt->wheel_v);
    }
}

// ----- Setup / Loop ----------------------------------------------------------

void setup()
{
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, HIGH); // Active-Low → OFF

    // UART1 from BP1  PA10=RX, PA9=TX  (W-3: initialise before USB)
    Serial1.begin(115200UL);

    parser_init(&g_parser);

    // USB HID Composite initialisation
    USBComposite.clear();
    USBComposite.setProductString("simple-kvm HID");
    HID.begin(); // C-1: no argument – mode is configured via HIDKeyboard/HIDMouse objects
    uint32_t t = millis();
    while (!USBComposite.isReady()) { // W-1: proper USB enumeration wait (5 s timeout)
        if (millis() - t > 5000) break;
        delay(10);
    }
}

void loop()
{
    while (Serial1.available()) {
        uint8_t b = (uint8_t)Serial1.read();
        if (parser_feed(&g_parser, b, &g_pkt)) {
            switch (g_pkt.type) {
                case PKT_KEYBOARD:
                    handle_keyboard(&g_pkt);
                    break;

                case PKT_MOUSE:
                    handle_mouse(&g_pkt);
                    break;

                case PKT_HEARTBEAT:
                    // Toggle LED as a liveness indicator
                    digitalWrite(LED_PIN, !digitalRead(LED_PIN));
                    break;

                default:
                    break;
            }
        }
    }
}
