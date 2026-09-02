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
#include "../common/build_info.h"
#include "hid_handler.h"
#ifdef SIMPLE_KVM_AUDIO
#include "audio_spi_slave.h"
#include "audio_usb_mic.h"
#endif

// USB device handle, defined in the framework's usbd_hid_composite_if.c.
extern USBD_HandleTypeDef hUSBD_Device_HID;

static PacketParser g_parser;
static Packet       g_pkt;
#define LED_PIN PC13

static uint8_t  g_err_count = 0;
static bool     g_led_state = false;
static uint32_t g_err_last  = 0;

#ifdef SIMPLE_KVM_AUDIO
static uint32_t read_u32(const uint8_t *data)
{
    return static_cast<uint32_t>(data[0]) |
           (static_cast<uint32_t>(data[1]) << 8U) |
           (static_cast<uint32_t>(data[2]) << 16U) |
           (static_cast<uint32_t>(data[3]) << 24U);
}

static simple_kvm::audio::ResetReason detect_reset_reason(uint32_t csr)
{
    using simple_kvm::audio::ResetReason;
    if ((csr & RCC_CSR_IWDGRSTF) != 0U) return ResetReason::kIwdg;
    if ((csr & RCC_CSR_WWDGRSTF) != 0U) return ResetReason::kWwdg;
    if ((csr & RCC_CSR_SFTRSTF) != 0U) return ResetReason::kSoftware;
    if ((csr & RCC_CSR_LPWRRSTF) != 0U) return ResetReason::kLowPower;
    if ((csr & RCC_CSR_PORRSTF) != 0U) return ResetReason::kPowerOn;
    if ((csr & RCC_CSR_PINRSTF) != 0U) return ResetReason::kExternalPin;
    return ResetReason::kUnknown;
}

static void write_u32(uint8_t *data, uint32_t value)
{
    data[0] = static_cast<uint8_t>(value);
    data[1] = static_cast<uint8_t>(value >> 8U);
    data[2] = static_cast<uint8_t>(value >> 16U);
    data[3] = static_cast<uint8_t>(value >> 24U);
}

static void write_u16(uint8_t *data, uint16_t value)
{
    data[0] = static_cast<uint8_t>(value);
    data[1] = static_cast<uint8_t>(value >> 8U);
}

static void send_uart_packet(const Packet *packet)
{
    uint8_t frame[20];
    const uint8_t length = packet_encode(packet, frame, sizeof(frame));
    if (length > 0U) Serial1.write(frame, length);
}

static void send_bp2_status(uint8_t page)
{
    const auto &diag =
        simple_kvm::audio::bp2::audio_receive_pipeline().diagnostics();
    Packet response{};
    response.type = PKT_AUDIO_RESPONSE;
    response.len = 14U;
    response.payload[0] = 2U;
    response.payload[1] = page;
    write_u32(&response.payload[2], diag.accepted_pcm_frames);
    write_u32(&response.payload[6], diag.spi_crc_error);
    write_u32(&response.payload[10], diag.underflow + diag.overflow);
    send_uart_packet(&response);
}

static void send_bp2_run_snapshot(const Packet *request)
{
    if (request->len != 5U || request->payload[4] < 1U ||
        request->payload[4] > 2U) return;
    const auto marker = static_cast<simple_kvm::audio::RunMarker>(
        request->payload[4]);
    const auto *snapshot =
        simple_kvm::audio::bp2::audio_receive_pipeline().run_snapshots().find(
            read_u32(request->payload), marker);
    if (snapshot == nullptr) return;
    Packet response{};
    response.type = PKT_AUDIO_RESPONSE;
    response.len = 16U;
    response.payload[0] = 2U;
    response.payload[1] = request->payload[4];
    write_u32(&response.payload[2], snapshot->run_id);
    write_u16(&response.payload[6], snapshot->marker_sequence);
    write_u32(&response.payload[8], snapshot->accepted_pcm_frames);
    write_u32(&response.payload[12], snapshot->error_count);
    send_uart_packet(&response);
}

static bool handle_audio_control(const Packet *packet)
{
    using namespace simple_kvm::audio;
    auto &pipeline = simple_kvm::audio::bp2::audio_receive_pipeline();
    if (packet->type == PKT_AUDIO_CONTROL_SYNC && packet->len == 8U) {
        const SyncTuple sync{read_u32(&packet->payload[0]),
                             read_u32(&packet->payload[4])};
        (void)pipeline.accept_sync(sync);
        Packet ack = *packet;
        ack.type = PKT_AUDIO_CONTROL_SYNC_ACK;
        send_uart_packet(&ack);
        return true;
    }
    if (packet->type == PKT_AUDIO_SESSION_END && packet->len == 7U) {
        const uint16_t session = static_cast<uint16_t>(packet->payload[4]) |
            static_cast<uint16_t>(static_cast<uint16_t>(packet->payload[5]) << 8U);
        if (pipeline.accept_session_end(read_u32(packet->payload), session)) {
            send_uart_packet(packet);  // first and duplicate END are idempotent
        }
        return true;
    }
    if (packet->type == PKT_GET_STATUS) {
        send_bp2_status(packet->len > 0U ? packet->payload[0] : 0U);
        return true;
    }
    if (packet->type == PKT_GET_CAPS) {
        Packet response{};
        response.type = PKT_AUDIO_RESPONSE;
        response.len = 6U;
        response.payload[0] = 2U;
        response.payload[1] = 1U;
        response.payload[2] = 0x0FU;  // audio, 3 HID, diagnostics, test hooks
        response.payload[3] = SIMPLE_KVM_AUDIO_CHANNELS;
        response.payload[4] = SIMPLE_KVM_AUDIO_BITS;
        response.payload[5] = 0U;
        response.len = 16U;
        const char *sha = simple_kvm::firmware_git_sha();
        for (uint8_t i = 0U; i < 10U && sha[i] != '\0'; ++i) {
            response.payload[6U + i] = static_cast<uint8_t>(sha[i]);
        }
        send_uart_packet(&response);
        return true;
    }
    if (packet->type == PKT_AUDIO_TEST_TONE && packet->len == 1U) {
#ifdef AUDIO_TEST_HOOKS
        bp2_audio_mic_set_test_tone(packet->payload[0] != 0U);
#endif
        return true;
    }
    if (packet->type == PKT_GET_RUN_SNAPSHOT) {
        send_bp2_run_snapshot(packet);
        return true;
    }
    if (packet->type == PKT_AUDIO_TEST_FAULT ||
        packet->type == PKT_AUDIO_TEST_MODE ||
        packet->type == PKT_CLEAR_COUNTERS) {
        return true;
    }
    return false;
}
#endif

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
#ifdef SIMPLE_KVM_AUDIO
    simple_kvm::audio::bp2::audio_receive_pipeline().note_hid_result(
        2U, status == USBD_BUSY, status != USBD_OK);
#endif
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
#ifdef SIMPLE_KVM_AUDIO
    const uint8_t result = USBD_HID_KEYBOARD_SendReport(
        &hUSBD_Device_HID, report, PKT_LEN_KEYBOARD);
    simple_kvm::audio::bp2::audio_receive_pipeline().note_hid_result(
        0U, result == USBD_BUSY, result != USBD_OK);
#else
    HID_Composite_keyboard_sendReport(report, PKT_LEN_KEYBOARD);
#endif
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
#ifdef SIMPLE_KVM_AUDIO
    const uint8_t result = USBD_HID_MOUSE_SendReport(
        &hUSBD_Device_HID, report, sizeof(report));
    simple_kvm::audio::bp2::audio_receive_pipeline().note_hid_result(
        1U, result == USBD_BUSY, result != USBD_OK);
#else
    HID_Composite_mouse_sendReport(report, sizeof(report));
#endif
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
#ifdef SIMPLE_KVM_AUDIO
    simple_kvm::audio::bp2::audio_receive_pipeline().set_reset_reason(
        detect_reset_reason(RCC->CSR));
    (void)simple_kvm::audio::bp2::audio_spi_slave_begin();
#endif
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
#ifdef SIMPLE_KVM_AUDIO
            if (handle_audio_control(&g_pkt)) {
                continue;
            }
#endif
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
#ifdef SIMPLE_KVM_AUDIO
    auto &pipeline = simple_kvm::audio::bp2::audio_receive_pipeline();
    pipeline.note_usb_state(
        static_cast<uint8_t>(hUSBD_Device_HID.dev_state),
        static_cast<uint8_t>(USBD_STATE_DEFAULT),
        static_cast<uint8_t>(USBD_STATE_SUSPENDED));
    simple_kvm::audio::bp2::audio_spi_slave_poll(millis());
#endif

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
