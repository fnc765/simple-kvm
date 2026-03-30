/**
 * bluepill1  –  USB CDC → UART1 Bridge
 * (PlatformIO 用エントリポイント。Arduino IDE では bluepill1.ino を使用)
 *
 * Hardware:
 *   PA11/PA12  USB D-/D+  →  Host PC (CDC Serial, 115200 bps)
 *   PA9  TX1              →  BluePill #2 PA10 (RX)
 *   PA10 RX1              ←  BluePill #2 PA9  (TX)  [ACK, future use]
 *   PC13 (Active-Low LED) –  Status / Heartbeat
 */

#include <Arduino.h>
#include <IWatchdog.h>
#include "packet_parser.h"

// ----- Pin / peripheral definitions ----------------------------------------
#define LED_PIN      PC13         // Active-Low
#define UART_BAUD    115200UL

// ----- Global state ----------------------------------------------------------
static PacketParser g_parser;
static Packet       g_pkt;

// Heartbeat LED
static uint32_t g_hb_last  = 0;
static bool     g_led_on   = false;

// Error indication
static uint32_t g_err_last  = 0;
static uint8_t  g_err_count = 0;

// ----- Helpers ---------------------------------------------------------------

/**
 * Rebuild and forward a validated packet to UART1.
 * Checksums the packet on the fly to ensure integrity across the UART link.
 */
static void forward_packet(const Packet *p)
{
    // Pre-allocate worst-case buffer: START(1) + TYPE(1) + LEN(1) + PAYLOAD(16) + CS(1)
    uint8_t buf[1 + 1 + 1 + PKT_MAX_PAYLOAD + 1];
    uint8_t idx = 0;

    buf[idx++] = PKT_START;
    buf[idx++] = p->type;
    buf[idx++] = p->len;

    uint8_t cs = p->type ^ p->len;
    for (uint8_t i = 0; i < p->len; i++) {
        buf[idx++] = p->payload[i];
        cs        ^= p->payload[i];
    }
    buf[idx++] = cs;

    Serial1.write(buf, idx);
}

// ----- Setup / Loop ----------------------------------------------------------

void setup()
{
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, HIGH); // Active-Low → OFF

    // USB CDC (host side) – USB CDC: baud引数は無視される
    Serial.begin(UART_BAUD);

    // UART1 (BP2 side)  PA9=TX, PA10=RX
    Serial1.begin(UART_BAUD);

    parser_init(&g_parser);

    IWatchdog.begin(4000000); // 4秒タイムアウト
}

void loop()
{
    IWatchdog.reload();

    uint32_t now = millis();

    // ---- Heartbeat LED: toggle every 1 s ----------------------------------
    if (now - g_hb_last >= 1000UL) {
        g_hb_last = now;
        g_led_on  = !g_led_on;
        digitalWrite(LED_PIN, g_led_on ? LOW : HIGH);
    }

    // ---- Error blink: rapid 3× blink on parse error -----------------------
    if (g_err_count > 0 && now - g_err_last >= 100UL) {
        g_err_last = now;
        g_err_count--;
        // Override heartbeat LED temporarily
        digitalWrite(LED_PIN, (g_err_count % 2 == 0) ? HIGH : LOW);
        if (g_err_count == 0) {
            // Sync LED state after error blink completes
            g_led_on = false;
            digitalWrite(LED_PIN, HIGH);
        }
    }

    // ---- USB CDC → parse → UART1 forward ----------------------------------
    while (Serial.available()) {
        uint8_t b = (uint8_t)Serial.read();
        if (parser_feed(&g_parser, b, &g_pkt)) {
            forward_packet(&g_pkt);
        } else {
            g_err_count = 6; // 3回点滅
        }
    }

    // ---- (Optional) UART1 → USB CDC passthrough for ACK / debug ----------
    // while (Serial1.available()) { Serial.write(Serial1.read()); }
}
