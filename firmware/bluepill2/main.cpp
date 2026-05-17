/**
 * bluepill2  -  UART1 -> USB HID Composite (Keyboard + Mouse)
 * (PlatformIO entry point)
 *
 * Hardware:
 *   PA11/PA12  USB D-/D+  ->  Target PC (HID Composite)
 *   PA10 RX1              <-  BluePill #1 PA9 (TX)
 *   PC13 (Active-Low LED) -  Status
 */
#include <Arduino.h>
#include <IWatchdog.h>
#include "usbd_hid_composite_if.h"
#include "../common/packet_parser.h"
#include "hid_handler.h"

static PacketParser g_parser;
static Packet       g_pkt;
#define LED_PIN PC13

static uint8_t  g_buttons   = 0;
static uint8_t  g_err_count = 0;
static bool     g_led_state = false;
static uint32_t g_err_last  = 0;

static void hid_send_keyboard(const Packet *p)
{
    if (p->len != PKT_LEN_KEYBOARD) return;
    if (!validate_keyboard_report(p->payload, p->len)) { g_err_count = 6; return; }
    uint8_t report[PKT_LEN_KEYBOARD];
    memcpy(report, p->payload, PKT_LEN_KEYBOARD);
    HID_Composite_keyboard_sendReport(report, PKT_LEN_KEYBOARD);
}

static void hid_send_mouse(const Packet *p)
{
    if (p->len != PKT_LEN_MOUSE) return;
    if (!validate_mouse_report(p->payload, p->len)) { g_err_count = 6; return; }
    KVMMouseReport rpt;
    memcpy(&rpt, p->payload, sizeof(rpt));
    g_buttons = rpt.buttons;
    uint8_t report[4];
    report[0] = g_buttons;
    report[1] = static_cast<uint8_t>(rpt.dx);
    report[2] = static_cast<uint8_t>(rpt.dy);
    report[3] = static_cast<uint8_t>(rpt.wheel_v);
    HID_Composite_mouse_sendReport(report, sizeof(report));
}

void setup()
{
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, HIGH);
    Serial1.begin(115200UL);
    parser_init(&g_parser);

    IWatchdog.begin(4000000);
    HID_Composite_Init(HID_KEYBOARD);
    IWatchdog.reload();
    for (int i = 0; i < 30; i++) { IWatchdog.reload(); delay(100); }
}

void loop()
{
    IWatchdog.reload();

    if (g_err_count > 0) {
        if (millis() - g_err_last >= 50) {
            g_err_last = millis();
            g_err_count--;
            g_led_state = !g_led_state;
            digitalWrite(LED_PIN, g_led_state ? LOW : HIGH);
        }
    }

    while (Serial1.available()) {
        uint8_t b = static_cast<uint8_t>(Serial1.read());
        if (parser_feed(&g_parser, b, &g_pkt)) {
            switch (g_pkt.type) {
                case PKT_KEYBOARD: hid_send_keyboard(&g_pkt); break;
                case PKT_MOUSE:    hid_send_mouse(&g_pkt);    break;
                case PKT_HEARTBEAT:
                    g_led_state = !g_led_state;
                    digitalWrite(LED_PIN, g_led_state ? LOW : HIGH);
                    break;
                default: g_err_count = 6; break;
            }
        }
    }
}
