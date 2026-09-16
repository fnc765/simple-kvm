/** HID x3 + UAC1 mono microphone wrapper for the existing HID implementation. */
#if defined(USBCON) && defined(USBD_USE_HID_COMPOSITE) && defined(SIMPLE_KVM_AUDIO)

#include "usbd_hid_composite_patch.h"
#include "usbd_ctlreq.h"
#include "audio_usb_mic.h"
#include <string.h>

/* build_src_flags renames the existing HID-only class.  This translation unit
 * owns the public symbol registered by STM32duino's interface layer. */
#ifdef USBD_COMPOSITE_HID
#undef USBD_COMPOSITE_HID
#endif

#define AUDIO_CONTROL_INTERFACE   0x03U
#define AUDIO_STREAM_INTERFACE    0x04U

extern USBD_ClassTypeDef SIMPLE_KVM_HID_ONLY_CLASS;

#if defined(__GNUC__)
#define SIMPLE_KVM_AUDIO_DESCRIPTOR_USED \
  __attribute__((used, externally_visible))
#else
#define SIMPLE_KVM_AUDIO_DESCRIPTOR_USED
#endif

/* Plain byte literals are intentional: source and ELF descriptor audits read
 * this exact symbol without relying on preprocessor arithmetic. */
SIMPLE_KVM_AUDIO_DESCRIPTOR_USED
const uint8_t simple_kvm_bp2_audio_config_descriptor[183] = {
  0x09, 0x02, 0xB7, 0x00, 0x05, 0x01, 0x00, 0x80, 0x31,

  /* HID keyboard, interface 0, EP82. */
  0x09, 0x04, 0x00, 0x00, 0x01, 0x03, 0x01, 0x01, 0x00,
  0x09, 0x21, 0x11, 0x01, 0x00, 0x01, 0x22, 0x43, 0x00,
  0x07, 0x05, 0x82, 0x03, 0x08, 0x00, 0x08,

  /* HID relative mouse, interface 1, EP81. */
  0x09, 0x04, 0x01, 0x00, 0x01, 0x03, 0x01, 0x02, 0x00,
  0x09, 0x21, 0x11, 0x01, 0x00, 0x01, 0x22, 0x4C, 0x00,
  0x07, 0x05, 0x81, 0x03, 0x08, 0x00, 0x08,

  /* HID absolute mouse, interface 2, EP83. */
  0x09, 0x04, 0x02, 0x00, 0x01, 0x03, 0x01, 0x02, 0x00,
  0x09, 0x21, 0x11, 0x01, 0x00, 0x01, 0x22, 0x33, 0x00,
  0x07, 0x05, 0x83, 0x03, 0x08, 0x00, 0x08,

  /* Audio IAD and Audio Control interface 3. */
  0x08, 0x0B, 0x03, 0x02, 0x01, 0x00, 0x00, 0x00,
  0x09, 0x04, 0x03, 0x00, 0x00, 0x01, 0x01, 0x00, 0x00,
  0x09, 0x24, 0x01, 0x00, 0x01, 0x1E, 0x00, 0x01, 0x04,
  0x0C, 0x24, 0x02, 0x01, 0x01, 0x02, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00,
  0x09, 0x24, 0x03, 0x02, 0x01, 0x01, 0x00, 0x01, 0x00,

  /* Audio Streaming interface 4, alt 0/1, fixed mono PCM16 48 kHz. */
  0x09, 0x04, 0x04, 0x00, 0x00, 0x01, 0x02, 0x00, 0x00,
  0x09, 0x04, 0x04, 0x01, 0x01, 0x01, 0x02, 0x00, 0x00,
  0x07, 0x24, 0x01, 0x02, 0x01, 0x01, 0x00,
  0x0B, 0x24, 0x02, 0x01, 0x01, 0x02, 0x10, 0x01, 0x80, 0xBB, 0x00,
  0x09, 0x05, 0x84, 0x0D, 0x60, 0x00, 0x01, 0x00, 0x00,
  0x07, 0x25, 0x01, 0x00, 0x00, 0x00, 0x00,
};

static const uint8_t kDeviceQualifier[10] = {
  0x0A, 0x06, 0x00, 0x02, 0xEF, 0x02, 0x01, 0x40, 0x01, 0x00,
};

typedef struct {
  volatile uint8_t alt;
  volatile uint8_t tx_index;
  volatile uint8_t packet_state[2];
  uint8_t packet[2][AUDIO_MIC_EPIN_SIZE];
} AudioMicUsbState;

enum {
  AUDIO_PACKET_FREE = 0U,
  AUDIO_PACKET_FILLING = 1U,
  AUDIO_PACKET_READY = 2U,
  AUDIO_PACKET_INFLIGHT = 3U,
};

static AudioMicUsbState g_audio_mic;
static uint8_t g_audio_zero_packet[AUDIO_MIC_EPIN_SIZE];

static uint32_t audio_irq_save(void)
{
  const uint32_t primask = __get_PRIMASK();
  __disable_irq();
  return primask;
}

static void audio_irq_restore(uint32_t primask)
{
  __set_PRIMASK(primask);
}

static void __attribute__((noinline, noclone))
audio_copy_descriptor(uint8_t *destination, const uint8_t *source,
                      uint16_t length)
{
  memcpy(destination, source, length);
}

static uint8_t *audio_get_config(uint16_t *length)
{
  /* The STM32 USB core normalizes the descriptor type in-place after this
   * callback returns.  Keep the audited canonical image in flash and hand the
   * core a writable transfer copy instead of casting away const. */
  static uint8_t config_descriptor[sizeof(simple_kvm_bp2_audio_config_descriptor)];
  audio_copy_descriptor(config_descriptor,
                        simple_kvm_bp2_audio_config_descriptor,
                        (uint16_t)sizeof(config_descriptor));
  *length = (uint16_t)sizeof(simple_kvm_bp2_audio_config_descriptor);
  return config_descriptor;
}

/* Return a valid Other-Speed Configuration descriptor for USB 2.0 hosts.
 * The payload is shared with the full-speed image; only bDescriptorType
 * changes from Configuration (0x02) to Other-Speed Configuration (0x07). */
static uint8_t g_other_speed_descriptor[
    sizeof(simple_kvm_bp2_audio_config_descriptor)];

static uint8_t *audio_get_other_speed(uint16_t *length)
{
  audio_copy_descriptor(g_other_speed_descriptor,
                        simple_kvm_bp2_audio_config_descriptor,
                        (uint16_t)sizeof(g_other_speed_descriptor));
  g_other_speed_descriptor[1] = 0x07U;
  *length = (uint16_t)sizeof(g_other_speed_descriptor);
  return g_other_speed_descriptor;
}

static uint8_t *audio_get_qualifier(uint16_t *length)
{
  *length = (uint16_t)sizeof(kDeviceQualifier);
  return (uint8_t *)(uintptr_t)kDeviceQualifier;
}

static void audio_close(USBD_HandleTypeDef *pdev)
{
  if (g_audio_mic.alt != 0U) {
    (void)USBD_LL_CloseEP(pdev, AUDIO_MIC_EPIN_ADDR);
    pdev->ep_in[AUDIO_MIC_EPIN_ADDR & 0x0FU].is_used = 0U;
  }
  g_audio_mic.alt = 0U;
  g_audio_mic.tx_index = 0U;
  g_audio_mic.packet_state[0] = AUDIO_PACKET_FREE;
  g_audio_mic.packet_state[1] = AUDIO_PACKET_FREE;
  bp2_audio_mic_on_alt(0U);
}

static uint8_t audio_set_alt(USBD_HandleTypeDef *pdev, uint8_t alt)
{
  if (alt > 1U) {
    return (uint8_t)USBD_FAIL;
  }
  if (g_audio_mic.alt == alt) {
    return (uint8_t)USBD_OK;
  }
  audio_close(pdev);
  if (alt == 1U) {
    memset(g_audio_zero_packet, 0, sizeof(g_audio_zero_packet));
    memset(g_audio_mic.packet, 0, sizeof(g_audio_mic.packet));
    (void)USBD_LL_OpenEP(pdev, AUDIO_MIC_EPIN_ADDR, USBD_EP_TYPE_ISOC,
                         AUDIO_MIC_EPIN_SIZE);
    pdev->ep_in[AUDIO_MIC_EPIN_ADDR & 0x0FU].is_used = 1U;
    pdev->ep_in[AUDIO_MIC_EPIN_ADDR & 0x0FU].bInterval = 1U;
    g_audio_mic.alt = 1U;
    g_audio_mic.tx_index = 0U;
    g_audio_mic.packet_state[0] = AUDIO_PACKET_INFLIGHT;
    g_audio_mic.packet_state[1] = AUDIO_PACKET_FREE;
    bp2_audio_mic_on_alt(1U);
    /* Keep the SET_INTERFACE callback short.  The first packet is silence;
     * the main loop prepares the following packets outside USB IRQ context. */
    (void)USBD_LL_Transmit(pdev, AUDIO_MIC_EPIN_ADDR,
                           g_audio_zero_packet, AUDIO_MIC_EPIN_SIZE);
    bp2_audio_mic_note_packet();
  }
  return (uint8_t)USBD_OK;
}

static uint8_t audio_init(USBD_HandleTypeDef *pdev, uint8_t cfgidx)
{
  const uint8_t result = SIMPLE_KVM_HID_ONLY_CLASS.Init(pdev, cfgidx);
  g_audio_mic.alt = 0U;
  g_audio_mic.tx_index = 0U;
  g_audio_mic.packet_state[0] = AUDIO_PACKET_FREE;
  g_audio_mic.packet_state[1] = AUDIO_PACKET_FREE;
  return result;
}

static uint8_t audio_deinit(USBD_HandleTypeDef *pdev, uint8_t cfgidx)
{
  audio_close(pdev);
  return SIMPLE_KVM_HID_ONLY_CLASS.DeInit(pdev, cfgidx);
}

static uint8_t audio_setup(USBD_HandleTypeDef *pdev, USBD_SetupReqTypedef *req)
{
  const uint8_t interface_number = (uint8_t)(req->wIndex & 0xFFU);
  if (interface_number < AUDIO_CONTROL_INTERFACE) {
    return SIMPLE_KVM_HID_ONLY_CLASS.Setup(pdev, req);
  }
  if (interface_number > AUDIO_STREAM_INTERFACE) {
    USBD_CtlError(pdev, req);
    return (uint8_t)USBD_FAIL;
  }

  if ((req->bmRequest & USB_REQ_TYPE_MASK) == USB_REQ_TYPE_STANDARD) {
    uint16_t status = 0U;
    switch (req->bRequest) {
      case USB_REQ_GET_STATUS:
        (void)USBD_CtlSendData(pdev, (uint8_t *)&status, 2U);
        return (uint8_t)USBD_OK;
      case USB_REQ_GET_INTERFACE: {
        uint8_t alt = interface_number == AUDIO_STREAM_INTERFACE
                          ? g_audio_mic.alt
                          : 0U;
        (void)USBD_CtlSendData(pdev, &alt, 1U);
        return (uint8_t)USBD_OK;
      }
      case USB_REQ_SET_INTERFACE:
        if (interface_number == AUDIO_STREAM_INTERFACE) {
          const uint8_t result = audio_set_alt(pdev, (uint8_t)req->wValue);
          if (result == (uint8_t)USBD_OK) {
            return result;
          }
        }
        break;
      default:
        break;
    }
  }
  USBD_CtlError(pdev, req);
  return (uint8_t)USBD_FAIL;
}

static uint8_t audio_datain(USBD_HandleTypeDef *pdev, uint8_t epnum)
{
  if ((epnum & 0x7FU) != (AUDIO_MIC_EPIN_ADDR & 0x7FU)) {
    return SIMPLE_KVM_HID_ONLY_CLASS.DataIn(pdev, epnum);
  }
  if (g_audio_mic.alt == 1U) {
    const uint8_t current = g_audio_mic.tx_index;
    const uint8_t next = (uint8_t)(current ^ 1U);
    const uint32_t primask = audio_irq_save();
    g_audio_mic.packet_state[current] = AUDIO_PACKET_FREE;
    const uint8_t ready =
        g_audio_mic.packet_state[next] == AUDIO_PACKET_READY ? 1U : 0U;
    g_audio_mic.packet_state[next] = AUDIO_PACKET_INFLIGHT;
    g_audio_mic.tx_index = next;
    audio_irq_restore(primask);
    /* Audio rendering is deliberately not done here: this callback runs in
     * the USB IRQ shared by all three HID endpoints. */
    (void)USBD_LL_Transmit(pdev, AUDIO_MIC_EPIN_ADDR,
                           ready ? g_audio_mic.packet[next]
                                 : g_audio_zero_packet,
                           AUDIO_MIC_EPIN_SIZE);
    bp2_audio_mic_note_packet();
  }
  return (uint8_t)USBD_OK;
}

void bp2_audio_mic_service(void)
{
  if (g_audio_mic.alt != 1U) {
    return;
  }
  for (uint8_t index = 0U; index < 2U; ++index) {
    uint8_t claimed = 0U;
    uint32_t primask = audio_irq_save();
    if (g_audio_mic.alt == 1U &&
        g_audio_mic.packet_state[index] == AUDIO_PACKET_FREE) {
      g_audio_mic.packet_state[index] = AUDIO_PACKET_FILLING;
      claimed = 1U;
    }
    audio_irq_restore(primask);
    if (claimed == 0U) {
      continue;
    }

    bp2_audio_mic_fill_packet(g_audio_mic.packet[index], AUDIO_MIC_EPIN_SIZE);

    primask = audio_irq_save();
    if (g_audio_mic.alt == 1U &&
        g_audio_mic.packet_state[index] == AUDIO_PACKET_FILLING) {
      g_audio_mic.packet_state[index] = AUDIO_PACKET_READY;
    } else if (g_audio_mic.packet_state[index] == AUDIO_PACKET_FILLING) {
      g_audio_mic.packet_state[index] = AUDIO_PACKET_FREE;
    }
    audio_irq_restore(primask);
  }
}

static uint8_t audio_dataout(USBD_HandleTypeDef *pdev, uint8_t epnum)
{
  return SIMPLE_KVM_HID_ONLY_CLASS.DataOut != NULL
             ? SIMPLE_KVM_HID_ONLY_CLASS.DataOut(pdev, epnum)
             : (uint8_t)USBD_OK;
}

USBD_ClassTypeDef USBD_COMPOSITE_HID = {
  audio_init,
  audio_deinit,
  audio_setup,
  NULL,
  NULL,
  audio_datain,
  audio_dataout,
  NULL,
  NULL,
  NULL,
  audio_get_config,
  audio_get_config,
  audio_get_other_speed,
  audio_get_qualifier,
};

#endif
