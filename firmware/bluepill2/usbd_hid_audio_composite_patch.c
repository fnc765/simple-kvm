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
  uint8_t alt;
  uint8_t tx_index;
  uint8_t packet[2][AUDIO_MIC_EPIN_SIZE];
} AudioMicUsbState;

static AudioMicUsbState g_audio_mic;

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
    (void)USBD_LL_OpenEP(pdev, AUDIO_MIC_EPIN_ADDR, USBD_EP_TYPE_ISOC,
                         AUDIO_MIC_EPIN_SIZE);
    pdev->ep_in[AUDIO_MIC_EPIN_ADDR & 0x0FU].is_used = 1U;
    pdev->ep_in[AUDIO_MIC_EPIN_ADDR & 0x0FU].bInterval = 1U;
    g_audio_mic.alt = 1U;
    bp2_audio_mic_on_alt(1U);
    bp2_audio_mic_fill_packet(g_audio_mic.packet[0], AUDIO_MIC_EPIN_SIZE);
    (void)USBD_LL_Transmit(pdev, AUDIO_MIC_EPIN_ADDR,
                           g_audio_mic.packet[0], AUDIO_MIC_EPIN_SIZE);
  }
  return (uint8_t)USBD_OK;
}

static uint8_t audio_init(USBD_HandleTypeDef *pdev, uint8_t cfgidx)
{
  const uint8_t result = SIMPLE_KVM_HID_ONLY_CLASS.Init(pdev, cfgidx);
  g_audio_mic.alt = 0U;
  g_audio_mic.tx_index = 0U;
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
    g_audio_mic.tx_index ^= 1U;
    bp2_audio_mic_fill_packet(g_audio_mic.packet[g_audio_mic.tx_index],
                              AUDIO_MIC_EPIN_SIZE);
    (void)USBD_LL_Transmit(pdev, AUDIO_MIC_EPIN_ADDR,
                           g_audio_mic.packet[g_audio_mic.tx_index],
                           AUDIO_MIC_EPIN_SIZE);
  }
  return (uint8_t)USBD_OK;
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
