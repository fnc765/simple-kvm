#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>
#include "hid_report_queue.h"
#include "../../firmware/common/packet_parser.h"
// The compiler-specific packing attribute is irrelevant to these byte-only
// reports. Validation and all forwarding/queue/timeout functions stay real.
#ifdef _MSC_VER
#define __attribute__(value)
#endif
#include "../../firmware/bluepill2/hid_handler.cpp"
#ifdef _MSC_VER
#undef __attribute__
#endif

static constexpr uint8_t USBD_STATE_CONFIGURED = 1U, USBD_OK = 0U, USBD_BUSY = 1U;
struct Device { uint8_t dev_state = USBD_STATE_CONFIGURED; };
static Device hUSBD_Device_HID;
static uint8_t g_err_count = 0U;
static bool idle[3] = {true, true, true};
static uint8_t send_status[3] = {};
using Report = std::array<uint8_t, 8>;
static std::vector<Report> sent[3];
static uint8_t send(unsigned interface_index, const uint8_t* data, uint16_t length)
{
  if (send_status[interface_index] != USBD_OK) return send_status[interface_index];
  Report copy{};
  std::memcpy(copy.data(), data, length);
  sent[interface_index].push_back(copy);
  return USBD_OK;
}
static bool HID_Composite_keyboard_isIdle() { return idle[0]; }
static bool HID_Composite_mouse_isIdle() { return idle[1]; }
static bool HID_Composite_abs_mouse_isIdle() { return idle[2]; }
static uint8_t USBD_HID_KEYBOARD_SendReport(Device*, uint8_t* p, uint16_t n) { return send(0, p, n); }
static uint8_t USBD_HID_MOUSE_SendReport(Device*, uint8_t* p, uint16_t n) { return send(1, p, n); }
static uint8_t USBD_HID_ABS_MOUSE_SendReport(Device*, uint8_t* p, uint16_t n) { return send(2, p, n); }
namespace simple_kvm::audio::bp2 {
struct Diagnostics { void note_hid_result(unsigned, bool, bool) {} };
static Diagnostics& audio_receive_pipeline() { static Diagnostics d; return d; }
}
namespace legacy_hid {
#include "bp2_hid_fixture.h"
}
namespace audio_hid {
#define SIMPLE_KVM_AUDIO 1
#include "bp2_hid_fixture.h"
#undef SIMPLE_KVM_AUDIO
}

struct Forwarder {
  void (*keyboard)(const Packet*);
  void (*mouse)(const Packet*);
  void (*absolute)(const Packet*);
  void (*activity)(uint32_t);
  void (*timeout)(uint32_t);
  void (*abs_service)();
  void (*queued_service)();
  void (*abs_clear)();
  simple_kvm::HidReportQueue* keyboard_queue;
  simple_kvm::HidReportQueue* mouse_queue;
  uint8_t* abs_count;
  uint8_t* abs_head;
  bool* abs_inflight;
  uint8_t (*abs_reports)[PKT_LEN_MOUSE_ABS];
};
#define FORWARDER(ns) Forwarder{ns::hid_send_keyboard, ns::hid_send_mouse, ns::hid_send_mouse_abs, ns::hid_note_uart_activity, ns::hid_input_timeout_service, ns::abs_mouse_service, ns::hid_queued_service, ns::abs_queue_clear, &ns::g_keyboard_queue, &ns::g_mouse_queue, &ns::g_abs_count, &ns::g_abs_head, &ns::g_abs_head_inflight, ns::g_abs_queue}
#define HID_CHECK(condition) do { if (!(condition)) { std::fprintf(stderr, "BP2_HID_FAIL line=%d condition=%s\n", __LINE__, #condition); return 1; } } while (0)
static void clear_sent() { for (auto& reports : sent) reports.clear(); }
static void pump(const Forwarder& f) { f.abs_service(); f.queued_service(); f.abs_service(); }
static void reset(const Forwarder& f)
{
  f.keyboard_queue->clear(); f.mouse_queue->clear(); f.abs_clear(); f.activity(0U);
  for (unsigned i = 0; i < 3; ++i) { idle[i] = true; send_status[i] = USBD_OK; }
  hUSBD_Device_HID.dev_state = USBD_STATE_CONFIGURED;
  clear_sent();
}
static void hold(const Forwarder& f)
{
  Packet keyboard{PKT_KEYBOARD, PKT_LEN_KEYBOARD, {2, 0, 4}};
  Packet mouse{PKT_MOUSE, PKT_LEN_MOUSE, {1, 3, 4, 1}};
  Packet absolute{PKT_MOUSE_ABS, PKT_LEN_MOUSE_ABS, {1, 0, 16, 0, 32}};
  f.keyboard(&keyboard); f.mouse(&mouse); f.absolute(&absolute); pump(f);
}
static bool neutral(unsigned index)
{
  if (sent[index].size() != 1U) return false;
  if (index == 2U) return sent[index][0][0] == 0U;
  return std::all_of(sent[index][0].begin(), sent[index][0].end(), [](uint8_t b) { return b == 0U; });
}

static int run_forwarder(const Forwarder& f)
{
  // Boundary, BUSY after an idle check, retry, preserved absolute position,
  // and a single neutral transaction for each uninterrupted UART outage.
  reset(f); hold(f); clear_sent(); f.timeout(2500U); pump(f);
  for (auto& reports : sent) HID_CHECK(reports.empty());
  for (auto& value : send_status) value = USBD_BUSY;
  f.timeout(2501U); pump(f);
  HID_CHECK(f.keyboard_queue->size() == 1U && f.mouse_queue->size() == 1U && *f.abs_count == 1U);
  for (auto& value : send_status) value = USBD_OK;
  pump(f);
  for (unsigned i = 0; i < 3; ++i) HID_CHECK(neutral(i));
  HID_CHECK(sent[2][0][2] == 16U && sent[2][0][4] == 32U);
  f.timeout(9000U); pump(f);
  for (unsigned i = 0; i < 3; ++i) HID_CHECK(sent[i].size() == 1U);

  // Periodic valid traffic must not release a long drag/modifier hold.
  reset(f); hold(f); clear_sent();
  for (uint32_t now = 1000U; now <= 6000U; now += 1000U) { f.activity(now); f.timeout(now); pump(f); }
  for (auto& reports : sent) HID_CHECK(reports.empty());
  f.timeout(8501U); pump(f);
  for (unsigned i = 0; i < 3; ++i) HID_CHECK(neutral(i));

  // Discard obsolete queued key/button history, including a full absolute
  // FIFO, without changing the buffer already owned by the USB peripheral.
  reset(f); hold(f); clear_sent();
  Packet absolute{PKT_MOUSE_ABS, PKT_LEN_MOUSE_ABS, {1, 10, 16, 20, 32}};
  f.absolute(&absolute); f.abs_service(); clear_sent(); idle[2] = false;
  Report inflight{}; std::memcpy(inflight.data(), f.abs_reports[*f.abs_head], 5);
  for (uint8_t i = 0; i < 32U; ++i) {
    Packet key{PKT_KEYBOARD, PKT_LEN_KEYBOARD, {2, 0, 4}};
    Packet mouse{PKT_MOUSE, PKT_LEN_MOUSE, {static_cast<uint8_t>(1U + i % 2U), 9, 8, 7}};
    absolute.payload[0] = static_cast<uint8_t>(1U + i % 2U);
    f.keyboard(&key); f.mouse(&mouse); f.absolute(&absolute);
  }
  f.timeout(2501U);
  HID_CHECK(*f.abs_count == 2U && *f.abs_inflight);
  HID_CHECK(std::memcmp(inflight.data(), f.abs_reports[*f.abs_head], 5) == 0);
  HID_CHECK(f.keyboard_queue->size() == 1U && f.mouse_queue->size() == 1U);
  idle[2] = true; pump(f);
  for (unsigned i = 0; i < 3; ++i) HID_CHECK(neutral(i));

  // Fresh traffic after an outage follows a pending release rather than
  // cancelling it or allowing an old held state to replay afterwards.
  reset(f); hold(f); clear_sent(); f.timeout(2501U); f.activity(2600U);
  Packet fresh{PKT_KEYBOARD, PKT_LEN_KEYBOARD, {0, 0, 5}}; f.keyboard(&fresh);
  pump(f); pump(f);
  HID_CHECK(sent[0].size() == 2U && sent[0][0] == Report{} && sent[0][1][2] == 5U);

  // millis() rollover must retain the same >2500 ms boundary.
  reset(f); hold(f); clear_sent(); const uint32_t last = 0xFFFFFF00U; f.activity(last);
  f.timeout(static_cast<uint32_t>(last + 2500U)); pump(f); HID_CHECK(sent[0].empty());
  f.timeout(static_cast<uint32_t>(last + 2501U)); pump(f);
  for (unsigned i = 0; i < 3; ++i) HID_CHECK(neutral(i));

  // The UART coordinate is unchanged; only the USB origin is encoded as
  // (1,0). Apply it equally to move/down/up and leave other edges untouched.
  for (uint8_t buttons = 0; buttons < 8U; ++buttons) {
    reset(f); Packet origin{PKT_MOUSE_ABS, PKT_LEN_MOUSE_ABS, {buttons, 0, 0, 0, 0}};
    f.absolute(&origin); pump(f);
    HID_CHECK(sent[2].size() == 1U && sent[2][0][0] == buttons && sent[2][0][1] == 1U && sent[2][0][3] == 0U);
    HID_CHECK(origin.payload[1] == 0U);
  }
  reset(f); Packet edge{PKT_MOUSE_ABS, PKT_LEN_MOUSE_ABS, {0, 0, 0, 1, 0}};
  f.absolute(&edge); pump(f); HID_CHECK(sent[2][0][1] == 0U && sent[2][0][3] == 1U);

  reset(f); hold(f); clear_sent(); f.timeout(2501U);
  hUSBD_Device_HID.dev_state = 0U; pump(f);
  hUSBD_Device_HID.dev_state = USBD_STATE_CONFIGURED; pump(f);
  for (auto& reports : sent) HID_CHECK(reports.empty());

  reset(f); Packet invalid{PKT_MOUSE_ABS, PKT_LEN_MOUSE_ABS, {0, 0, 128, 0, 0}};
  f.absolute(&invalid); invalid.type = PKT_KEYBOARD; invalid.len = 7U; f.keyboard(&invalid);
  invalid.type = PKT_MOUSE; invalid.len = 4U; f.mouse(&invalid); pump(f);
  for (auto& reports : sent) HID_CHECK(reports.empty());

  // A previously released absolute pointer must not warp back to its old
  // position when only relative input later times out.
  reset(f); Packet released_position{PKT_MOUSE_ABS, PKT_LEN_MOUSE_ABS, {0, 0, 16, 0, 32}};
  f.absolute(&released_position); pump(f); clear_sent();
  f.timeout(2501U); pump(f); HID_CHECK(sent[2].empty());

  // If an absolute release is queued but unsent, the watchdog must still
  // release the delivered hold, at the delivered position, after discarding
  // the newer queued position.
  reset(f); hold(f); clear_sent();
  Packet pending_release{PKT_MOUSE_ABS, PKT_LEN_MOUSE_ABS, {0, 30, 64, 40, 64}};
  f.absolute(&pending_release); f.timeout(2501U); pump(f);
  HID_CHECK(neutral(2) && sent[2][0][1] == 0U && sent[2][0][2] == 16U && sent[2][0][4] == 32U);
  return 0;
}

int run_bp2_hid_tests()
{
  if (run_forwarder(FORWARDER(legacy_hid)) || run_forwarder(FORWARDER(audio_hid))) return 1;
  std::printf("BP2_HID_PASS profiles=2 cases_per_profile=10\n");
  return 0;
}
