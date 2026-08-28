/** Complete BP1 CDC + UAC1 endpoint/PMA layout, force-included by PlatformIO. */
#ifndef SIMPLE_KVM_BP1_AUDIO_EP_CONF_OVERRIDE_H
#define SIMPLE_KVM_BP1_AUDIO_EP_CONF_OVERRIDE_H

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

#define AUDIO_OUT_EP                    0x01U
#define AUDIO_OUT_PACKET_SIZE           0x60U
#define CDC_OUT_EP                      0x02U
#define CDC_IN_EP                       0x82U
#define CDC_CMD_EP                      0x83U
#define CDC_DATA_HS_MAX_PACKET_SIZE     USB_HS_MAX_PACKET_SIZE
#define CDC_DATA_FS_MAX_PACKET_SIZE     USB_FS_MAX_PACKET_SIZE
#define CDC_CMD_PACKET_SIZE             8U
#define DEV_NUM_EP                      0x04U

#if defined(USB)
#define PMA_EP0_OUT_ADDR                32U
#define PMA_EP0_IN_ADDR                 96U
#define PMA_AUDIO_OUT_ADDR              (160U | (256UL << 16U))
#define PMA_CDC_OUT_ADDR                352U
#define PMA_CDC_IN_ADDR                 416U
#define PMA_CDC_CMD_ADDR                480U
#endif

/* BP1 has six directional entries across four physical endpoint registers. */
extern const ep_desc_t ep_def[];
#define __USBD_EP_CONF_H
#endif
#endif
