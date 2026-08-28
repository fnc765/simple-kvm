/** Complete BP2 HID x3 + UAC1 endpoint/PMA layout, force-included by PlatformIO. */
#ifndef SIMPLE_KVM_BP2_AUDIO_EP_CONF_OVERRIDE_H
#define SIMPLE_KVM_BP2_AUDIO_EP_CONF_OVERRIDE_H

#ifdef USBCON
#include <stdint.h>
#include "usbd_def.h"

typedef struct {
  uint32_t ep_adress;
  uint32_t ep_size;
#if defined(USB)
  uint32_t ep_kind;
#endif
} ep_desc_t;

#define HID_MOUSE_EPIN_ADDR             0x81U
#define HID_KEYBOARD_EPIN_ADDR          0x82U
#define HID_ABS_MOUSE_EPIN_ADDR         0x83U
#define AUDIO_MIC_EPIN_ADDR             0x84U
#define HID_MOUSE_EPIN_SIZE             0x08U
#define HID_KEYBOARD_EPIN_SIZE          0x08U
#define HID_ABS_MOUSE_EPIN_SIZE         0x08U
#define AUDIO_MIC_EPIN_SIZE             0x60U
#define DEV_NUM_EP                      0x05U

#if defined(USB)
#define PMA_EP0_OUT_ADDR                40U
#define PMA_EP0_IN_ADDR                 104U
#define PMA_MOUSE_IN_ADDR               168U
#define PMA_KEYBOARD_IN_ADDR            176U
#define PMA_ABS_MOUSE_IN_ADDR           184U
#define PMA_AUDIO_IN_ADDR               (192U | (288UL << 16U))
#endif

extern const ep_desc_t ep_def[DEV_NUM_EP + 1U];
#define __USBD_EP_CONF_H
#endif
#endif
