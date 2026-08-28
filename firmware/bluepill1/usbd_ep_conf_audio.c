#if defined(HAL_PCD_MODULE_ENABLED) && defined(USBCON) && defined(SIMPLE_KVM_AUDIO)
#include "usbd_ep_conf.h"

/* The USB LL loop configures the first DEV_NUM_EP + 1 entries.  CDC OUT is
 * entry six because EP2 is bidirectional; the composite class configures that
 * final direction explicitly before opening it. */
const ep_desc_t ep_def[] = {
  {0x00U,       PMA_EP0_OUT_ADDR,   PCD_SNG_BUF},
  {0x80U,       PMA_EP0_IN_ADDR,    PCD_SNG_BUF},
  {AUDIO_OUT_EP, PMA_AUDIO_OUT_ADDR, PCD_DBL_BUF},
  {CDC_IN_EP,   PMA_CDC_IN_ADDR,    PCD_SNG_BUF},
  {CDC_CMD_EP,  PMA_CDC_CMD_ADDR,   PCD_SNG_BUF},
  {CDC_OUT_EP,  PMA_CDC_OUT_ADDR,   PCD_SNG_BUF},
};
#endif
