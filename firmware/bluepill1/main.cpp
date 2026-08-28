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
#include "../common/packet_parser.h"
#include "../common/build_info.h"
#ifdef SIMPLE_KVM_AUDIO
#include "../common/audio_control.h"
#include "audio_spi_master.h"
#include "audio_usb_out.h"
#include "usbd_def.h"
extern USBD_HandleTypeDef hUSBD_Device_CDC;
#endif

// ----- Pin / peripheral definitions ----------------------------------------
#define LED_PIN      PC13         // Active-Low
#define UART_BAUD    115200UL

// ----- Global state ----------------------------------------------------------
static PacketParser g_parser;
static Packet       g_pkt;
#ifdef SIMPLE_KVM_AUDIO
static PacketParser g_uart_parser;
static Packet       g_uart_pkt;
static simple_kvm::audio::BootHidQueue g_boot_queue;
static simple_kvm::audio::SyncRetryState g_sync;
static uint8_t g_last_audio_alt = 0U;
#endif

// Heartbeat LED
static uint32_t g_hb_last  = 0;
static bool     g_led_on   = false;

// ----- Helpers ---------------------------------------------------------------

/**
 * Rebuild and forward a validated packet to UART1.
 * Appends CRC-8-CCITT over type + len + payload to ensure integrity.
 */
static void forward_packet(const Packet *p)
{
    uint8_t buf[1 + 1 + 1 + PKT_MAX_PAYLOAD + 1];
    const uint8_t length = packet_encode(p, buf, sizeof(buf));
    if (length > 0U) Serial1.write(buf, length);
}

#ifdef SIMPLE_KVM_AUDIO
static uint32_t read_u32(const uint8_t *data)
{
    return static_cast<uint32_t>(data[0]) |
           (static_cast<uint32_t>(data[1]) << 8U) |
           (static_cast<uint32_t>(data[2]) << 16U) |
           (static_cast<uint32_t>(data[3]) << 24U);
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

static uint32_t make_boot_nonce()
{
    const uint32_t *uid = reinterpret_cast<const uint32_t *>(UID_BASE);
    const uint32_t entropy[5] = {
        uid[0], uid[1], uid[2], RCC->CSR, micros(),
    };
    uint32_t crc = 0xFFFFFFFFUL;
    for (uint8_t word = 0U; word < 5U; ++word) {
        uint32_t value = entropy[word];
        for (uint8_t byte = 0U; byte < 4U; ++byte) {
            crc ^= value & 0xFFU;
            value >>= 8U;
            for (uint8_t bit = 0U; bit < 8U; ++bit) {
                crc = (crc >> 1U) ^
                      ((crc & 1U) != 0U ? 0xEDB88320UL : 0U);
            }
        }
    }
    const uint32_t nonce = ~crc;
    return nonce == 0U ? 1U : nonce;
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

static void send_sync(uint32_t now)
{
    Packet sync{};
    sync.type = PKT_AUDIO_CONTROL_SYNC;
    sync.len = 8U;
    write_u32(&sync.payload[0], g_sync.tuple().boot_nonce);
    write_u32(&sync.payload[4], g_sync.tuple().request_id);
    forward_packet(&sync);
    g_sync.mark_sent(now);
}

static void send_bp1_status(uint8_t page)
{
    const auto &diag = simple_kvm::audio::bp1::audio_spi_master_diagnostics();
    Packet response{};
    response.type = PKT_AUDIO_RESPONSE;
    response.len = 14U;
    response.payload[0] = 1U;
    response.payload[1] = page;
    write_u32(&response.payload[2], diag.usb_audio_packets);
    write_u32(&response.payload[6], diag.spi_pcm_frames);
    write_u32(&response.payload[10], diag.spi_deadline_miss);
    uint8_t frame[20];
    const uint8_t length = packet_encode(&response, frame, sizeof(frame));
    if (length > 0U) Serial.write(frame, length);
}

static void send_bp1_caps()
{
    Packet response{};
    response.type = PKT_AUDIO_RESPONSE;
    response.len = 16U;
    response.payload[0] = 1U;
    response.payload[1] = 1U;
    response.payload[2] = 0x0DU;  // audio, diagnostics, test hooks
    response.payload[3] = 0U;
    const char *sha = simple_kvm::firmware_git_sha();
    for (uint8_t i = 0U; i < 12U && sha[i] != '\0'; ++i) {
        response.payload[4U + i] = static_cast<uint8_t>(sha[i]);
    }
    uint8_t frame[20];
    const uint8_t length = packet_encode(&response, frame, sizeof(frame));
    if (length > 0U) Serial.write(frame, length);
}

static void send_bp1_run_snapshot(const Packet *request)
{
    if (request->len != 5U || request->payload[4] < 1U ||
        request->payload[4] > 2U) return;
    const auto marker = static_cast<simple_kvm::audio::RunMarker>(
        request->payload[4]);
    const auto *snapshot =
        simple_kvm::audio::bp1::audio_spi_master_snapshots().find(
            read_u32(request->payload), marker);
    if (snapshot == nullptr) return;
    Packet response{};
    response.type = PKT_AUDIO_RESPONSE;
    response.len = 16U;
    response.payload[0] = 1U;
    response.payload[1] = request->payload[4];
    write_u32(&response.payload[2], snapshot->run_id);
    write_u16(&response.payload[6], snapshot->marker_sequence);
    write_u32(&response.payload[8], snapshot->usb_audio_boundary);
    write_u32(&response.payload[12], snapshot->spi_pcm_frames);
    uint8_t frame[20];
    const uint8_t length = packet_encode(&response, frame, sizeof(frame));
    if (length > 0U) Serial.write(frame, length);
}

static void dispatch_host_packet(const Packet *packet)
{
    if ((packet->type == PKT_AUDIO_RUN_START ||
         packet->type == PKT_AUDIO_RUN_END) && packet->len == 4U) {
        (void)simple_kvm::audio::bp1::enqueue_run_marker(
            packet->type == PKT_AUDIO_RUN_START, read_u32(packet->payload));
        return;
    }
    if (packet->type == PKT_GET_STATUS) {
        send_bp1_status(packet->len > 0U ? packet->payload[0] : 0U);
    }
    if (packet->type == PKT_GET_CAPS) send_bp1_caps();
    if (packet->type == PKT_GET_RUN_SNAPSHOT) send_bp1_run_snapshot(packet);
#ifdef AUDIO_TEST_HOOKS
    if (packet->type == PKT_AUDIO_TEST_FAULT && packet->len == 1U) {
        simple_kvm::audio::bp1::audio_spi_master_inject_fault(
            packet->payload[0]);
    }
#endif
    forward_packet(packet);
}

static void accept_or_queue_host_packet(const Packet *packet, uint32_t now)
{
    if (!g_sync.barrier_active(now)) {
        dispatch_host_packet(packet);
        return;
    }
    uint8_t frame[20];
    const uint8_t length = packet_encode(packet, frame, sizeof(frame));
    if (length > 0U) (void)g_boot_queue.push(frame, length, now);
}

static void service_audio_control(uint32_t now)
{
    if (g_sync.should_send(now)) send_sync(now);

    if (!g_sync.barrier_active(now) && g_boot_queue.fill() > 0U) {
        uint8_t frame[20];
        uint8_t length = 0U;
        uint32_t accepted_ms = 0U;
        if (g_boot_queue.pop(frame, length, accepted_ms)) {
            (void)accepted_ms;
            Serial1.write(frame, length);
        }
    }

    while (Serial1.available()) {
        const uint8_t byte = static_cast<uint8_t>(Serial1.read());
        if (parser_feed(&g_uart_parser, byte, &g_uart_pkt)) {
            if (g_uart_pkt.type == PKT_AUDIO_CONTROL_SYNC_ACK &&
                g_uart_pkt.len == 8U) {
                const simple_kvm::audio::SyncTuple ack{
                    read_u32(&g_uart_pkt.payload[0]),
                    read_u32(&g_uart_pkt.payload[4])};
                (void)g_sync.ack(ack);
            }
            uint8_t frame[20];
            const uint8_t length = packet_encode(&g_uart_pkt, frame, sizeof(frame));
            if (length > 0U) Serial.write(frame, length);
        }
    }

    const uint8_t alt = simple_kvm::audio::bp1::usb_audio_alt();
    if (g_last_audio_alt == 1U && alt == 0U) {
        Packet end{};
        end.type = PKT_AUDIO_SESSION_END;
        end.len = 7U;
        write_u32(&end.payload[0], simple_kvm::audio::bp1::audio_boot_nonce());
        const uint16_t session =
            simple_kvm::audio::bp1::audio_session_counter();
        end.payload[4] = static_cast<uint8_t>(session);
        end.payload[5] = static_cast<uint8_t>(session >> 8U);
        end.payload[6] = 0U;
        forward_packet(&end);
    }
    g_last_audio_alt = alt;
}
#endif

// ----- Setup / Loop ----------------------------------------------------------

void setup()
{
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, HIGH); // Active-Low → OFF

#ifdef SIMPLE_KVM_AUDIO
    const uint32_t reset_flags = RCC->CSR;
    const uint32_t boot_nonce = make_boot_nonce();
    simple_kvm::audio::bp1::set_audio_boot_nonce(boot_nonce);
    simple_kvm::audio::bp1::audio_spi_master_set_reset_reason(
        detect_reset_reason(reset_flags));
#endif
    // USB CDC (host side) – USB CDC: baud引数は無視される
    Serial.begin(UART_BAUD);

    // UART1 (BP2 side)  PA9=TX, PA10=RX
    Serial1.begin(UART_BAUD);

    parser_init(&g_parser);
#ifdef SIMPLE_KVM_AUDIO
    parser_init(&g_uart_parser);
    const simple_kvm::audio::SyncTuple sync{boot_nonce, boot_nonce ^ 0x51A7C3E9UL};
    g_sync.begin(millis(), sync);
    (void)simple_kvm::audio::bp1::audio_spi_master_begin();
#endif

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

    // ---- USB CDC → parse → UART1 forward ----------------------------------
    while (Serial.available()) {
        uint8_t b = (uint8_t)Serial.read();
        if (parser_feed(&g_parser, b, &g_pkt)) {
#ifdef SIMPLE_KVM_AUDIO
            accept_or_queue_host_packet(&g_pkt, now);
#else
            forward_packet(&g_pkt);
#endif
        }
        // parser_feed() returning false is normal for intermediate bytes;
        // only completed+validated packets return true. No error here.
    }

#ifdef SIMPLE_KVM_AUDIO
    service_audio_control(now);
    simple_kvm::audio::bp1::audio_spi_master_update_control_diagnostics(
        now, g_sync.tuple().request_id, g_sync.send_count(), g_sync.acked(),
        g_boot_queue.high_water(), g_boot_queue.overflow_count());
    simple_kvm::audio::bp1::audio_spi_master_note_usb_state(
        static_cast<uint8_t>(hUSBD_Device_CDC.dev_state),
        static_cast<uint8_t>(USBD_STATE_DEFAULT),
        static_cast<uint8_t>(USBD_STATE_SUSPENDED));
    simple_kvm::audio::bp1::audio_spi_master_poll(now);
#endif

    // TODO: UART1 → USB CDC passthrough for ACK / debug (future use)
    // while (Serial1.available()) { Serial.write(Serial1.read()); }
}
