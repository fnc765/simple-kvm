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
#include "usbd_hid_composite_patch.h"
#include "../common/packet_parser.h"
#include "hid_handler.h"

// USB device handle, defined in the framework's usbd_hid_composite_if.c.
extern USBD_HandleTypeDef hUSBD_Device_HID;

static PacketParser g_parser;
static Packet       g_pkt;
#define LED_PIN PC13

static uint8_t  g_err_count = 0;
static bool     g_led_state = false;
static uint32_t g_err_last  = 0;

// Absolute reports arrive over 115200-baud UART much faster than the USB
// interrupt endpoint can complete them.  Keep button edges FIFO ordered,
// while replacing redundant same-button motion at the queue tail.
#define ABS_MOUSE_QUEUE_CAPACITY 32u
#define ABS_INPUT_TIMEOUT_MS 2500u
static uint8_t g_abs_queue[ABS_MOUSE_QUEUE_CAPACITY][PKT_LEN_MOUSE_ABS];
static uint8_t g_abs_head = 0;
static uint8_t g_abs_count = 0;
static bool g_abs_head_inflight = false;
static uint8_t g_abs_last_desired[PKT_LEN_MOUSE_ABS] = {0, 0, 0, 0, 0};
static uint32_t g_last_uart_activity_ms = 0;

static uint8_t abs_queue_index(uint8_t offset)
{
    return static_cast<uint8_t>((g_abs_head + offset) % ABS_MOUSE_QUEUE_CAPACITY);
}

static void abs_queue_clear(void)
{
    g_abs_head = 0;
    g_abs_count = 0;
    g_abs_head_inflight = false;
    memset(g_abs_last_desired, 0, sizeof(g_abs_last_desired));
}

static void abs_queue_pop_head(void)
{
    if (g_abs_count == 0) return;
    g_abs_head = abs_queue_index(1);
    g_abs_count--;
}

static void abs_queue_report(const uint8_t *report)
{
    memcpy(g_abs_last_desired, report, PKT_LEN_MOUSE_ABS);

    if (g_abs_count > 0) {
        const uint8_t tail_offset = static_cast<uint8_t>(g_abs_count - 1);
        const uint8_t tail = abs_queue_index(tail_offset);
        const bool tail_is_inflight = g_abs_head_inflight && g_abs_count == 1;

        // Motion with an unchanged button mask is state, not history.  Only
        // the newest coordinate matters, but never overwrite the buffer that
        // the USB peripheral is currently transmitting.
        if (!tail_is_inflight && g_abs_queue[tail][0] == report[0]) {
            memcpy(g_abs_queue[tail], report, PKT_LEN_MOUSE_ABS);
            return;
        }
    }

    if (g_abs_count < ABS_MOUSE_QUEUE_CAPACITY) {
        const uint8_t slot = abs_queue_index(g_abs_count);
        memcpy(g_abs_queue[slot], report, PKT_LEN_MOUSE_ABS);
        g_abs_count++;
        return;
    }

    // Fail safe on pathological button spam: preserve the newest final state
    // rather than risking a permanently held button.  Normal pointer motion
    // cannot fill this queue because same-state coordinates are coalesced.
    const uint8_t tail = abs_queue_index(
        static_cast<uint8_t>(ABS_MOUSE_QUEUE_CAPACITY - 1)
    );
    memcpy(g_abs_queue[tail], report, PKT_LEN_MOUSE_ABS);
    g_err_count = 6;
}

static void abs_mouse_service(void)
{
    if (hUSBD_Device_HID.dev_state != USBD_STATE_CONFIGURED) {
        // Never replay stale clicks after a USB disconnect/re-enumeration.
        abs_queue_clear();
        return;
    }

    if (g_abs_head_inflight) {
        if (!HID_Composite_abs_mouse_isIdle()) return;
        abs_queue_pop_head();
        g_abs_head_inflight = false;
    }

    if (g_abs_count == 0) return;
    const uint8_t status = USBD_HID_ABS_MOUSE_SendReport(
        &hUSBD_Device_HID,
        g_abs_queue[g_abs_head],
        PKT_LEN_MOUSE_ABS
    );
    if (status == USBD_OK) {
        g_abs_head_inflight = true;
    }
}

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
    uint8_t report[5];
    report[0] = rpt.buttons;
    report[1] = static_cast<uint8_t>(rpt.dx);
    report[2] = static_cast<uint8_t>(rpt.dy);
    report[3] = static_cast<uint8_t>(rpt.wheel_v);
    report[4] = static_cast<uint8_t>(rpt.wheel_h);
    HID_Composite_mouse_sendReport(report, sizeof(report));
}

static void hid_send_mouse_abs(const Packet *p)
{
    if (p->len != PKT_LEN_MOUSE_ABS) return;
    if (!validate_mouse_abs_report(p->payload, p->len)) { g_err_count = 6; return; }
    // Payload is [buttons, x_lo, x_hi, y_lo, y_hi] - little-endian.
    // Queue it so USBD_BUSY never silently discards a button transition.
    abs_queue_report(p->payload);
}

void setup()
{
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, HIGH);
    Serial1.begin(115200UL);
    parser_init(&g_parser);

    IWatchdog.begin(4000000);
    HID_Composite_Init(HID_KEYBOARD);
    g_last_uart_activity_ms = millis();
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
            g_last_uart_activity_ms = millis();
            switch (g_pkt.type) {
                case PKT_KEYBOARD:   hid_send_keyboard(&g_pkt); break;
                case PKT_MOUSE:      hid_send_mouse(&g_pkt);    break;
                case PKT_MOUSE_ABS:  hid_send_mouse_abs(&g_pkt); break;
                case PKT_HEARTBEAT:
                    g_led_state = !g_led_state;
                    digitalWrite(LED_PIN, g_led_state ? LOW : HIGH);
                    break;
                default: g_err_count = 6; break;
            }
            abs_mouse_service();
        }
    }

    // Heartbeats arrive once per second while the app is healthy.  If UART
    // disappears during a drag, release every absolute button at the last
    // known coordinate instead of leaving the target permanently held.
    if (
        g_abs_last_desired[0] != 0
        && static_cast<uint32_t>(millis() - g_last_uart_activity_ms)
            > ABS_INPUT_TIMEOUT_MS
    ) {
        uint8_t release_report[PKT_LEN_MOUSE_ABS];
        memcpy(release_report, g_abs_last_desired, PKT_LEN_MOUSE_ABS);
        release_report[0] = 0;
        abs_queue_report(release_report);
        g_last_uart_activity_ms = millis();
    }
    abs_mouse_service();
}
