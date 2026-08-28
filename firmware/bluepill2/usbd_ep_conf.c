/**
  ******************************************************************************
  * @file    usbd_ep_conf.c
  * @brief   PATCH: Endpoint configuration with 4 endpoints for the 3-interface
  *          HID composite (Keyboard + Relative Mouse + Absolute Mouse)
  *
  * The PlatformIO build middleware excludes the framework's usbd_ep_conf.c,
  * leaving this file as the single endpoint table provider.
  *
  * Original source:
  *   ~/.platformio/packages/framework-arduinoststm32/libraries/USBDevice/src/usbd_ep_conf.c
  ******************************************************************************
  */
#if defined(HAL_PCD_MODULE_ENABLED) && defined(USBCON)
/* Includes ------------------------------------------------------------------*/
#include "usbd_ep_conf.h"

#ifdef USBD_USE_CDC
const ep_desc_t ep_def[] = {
#ifdef USE_USB_HS
  {0x00,       CDC_DATA_HS_MAX_PACKET_SIZE},
  {0x80,       CDC_DATA_HS_MAX_PACKET_SIZE},
  {CDC_OUT_EP, CDC_DATA_HS_MAX_PACKET_SIZE},
  {CDC_IN_EP,  CDC_DATA_HS_MAX_PACKET_SIZE},
  {CDC_CMD_EP, CDC_CMD_PACKET_SIZE}
#else /* USE_USB_FS */
#ifdef USB_OTG_FS
  {0x00,       CDC_DATA_FS_MAX_PACKET_SIZE},
  {0x80,       CDC_DATA_FS_MAX_PACKET_SIZE},
  {CDC_OUT_EP, CDC_DATA_FS_MAX_PACKET_SIZE},
  {CDC_IN_EP,  CDC_DATA_FS_MAX_PACKET_SIZE},
  {CDC_CMD_EP, CDC_CMD_PACKET_SIZE}
#else
  {0x00,       PMA_EP0_OUT_ADDR, PCD_SNG_BUF},
  {0x80,       PMA_EP0_IN_ADDR,  PCD_SNG_BUF},
#ifndef USBD_CDC_USE_SINGLE_BUFFER
  {CDC_OUT_EP, PMA_CDC_OUT_ADDR, PCD_DBL_BUF},
#else
  {CDC_OUT_EP, PMA_CDC_OUT_ADDR, PCD_SNG_BUF},
#endif
  {CDC_IN_EP,  PMA_CDC_IN_ADDR,  PCD_SNG_BUF},
  {CDC_CMD_EP, PMA_CDC_CMD_ADDR, PCD_SNG_BUF}
#endif
#endif
};
#endif /* USBD_USE_CDC */

#ifdef USBD_USE_HID_COMPOSITE
/* PATCHED: EP0 OUT/IN + Keyboard + Relative Mouse + Absolute Mouse. */
#if !defined (USB)
#ifdef USE_USB_HS
  #define EP0_SIZE   USB_HS_MAX_PACKET_SIZE
#else
  #define EP0_SIZE   USB_FS_MAX_PACKET_SIZE
#endif
const ep_desc_t ep_def[] = {
  {0x00,                   EP0_SIZE},
  {0x80,                   EP0_SIZE},
  {HID_MOUSE_EPIN_ADDR,    HID_MOUSE_EPIN_SIZE},
  {HID_KEYBOARD_EPIN_ADDR, HID_KEYBOARD_EPIN_SIZE},
  {HID_ABS_MOUSE_EPIN_ADDR, HID_ABS_MOUSE_EPIN_SIZE},
};
#else
const ep_desc_t ep_def[] = {
  {0x00,                    PMA_EP0_OUT_ADDR,     PCD_SNG_BUF},
  {0x80,                    PMA_EP0_IN_ADDR,      PCD_SNG_BUF},
  {HID_MOUSE_EPIN_ADDR,     PMA_MOUSE_IN_ADDR,    PCD_SNG_BUF},
  {HID_KEYBOARD_EPIN_ADDR,  PMA_KEYBOARD_IN_ADDR, PCD_SNG_BUF},
  {HID_ABS_MOUSE_EPIN_ADDR, PMA_ABS_MOUSE_IN_ADDR, PCD_SNG_BUF},
#ifdef SIMPLE_KVM_AUDIO
  {AUDIO_MIC_EPIN_ADDR,     PMA_AUDIO_IN_ADDR,     PCD_DBL_BUF},
#endif
};
#endif
#endif /* USBD_USE_HID_COMPOSITE */

#endif /* HAL_PCD_MODULE_ENABLED && USBCON */
/************************ End of patched file *****END OF FILE****/
