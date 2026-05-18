/**
  ******************************************************************************
  * @file    usbd_ep_conf_patch.h
  * @brief   Patch: Endpoint configuration overrides for C52B emulation
  *
  * This file documents the endpoint configuration changes needed.
  * Actual overrides are applied in usbd_hid_composite_patch.h via #undef/#define
  * after including the original usbd_ep_conf.h.
  *
  * Changes:
  *   - HID_MOUSE_EPIN_SIZE: 0x04 → 0x08 (8-byte mouse endpoint for 5-byte report)
  *   - PMA buffer addresses recalculated automatically via macro expansion
  *
  * Original source:
  *   ~/.platformio/packages/framework-arduinoststm32/libraries/USBDevice/inc/usbd_ep_conf.h
  ******************************************************************************
  */

#ifndef __USBD_EP_CONF_PATCH_H
#define __USBD_EP_CONF_PATCH_H

#ifdef USBCON

/*
 * The original usbd_ep_conf.h is included by usbd_hid_composite_patch.h.
 * Overrides are applied there via:
 *
 *   #include "usbd_ep_conf.h"
 *   #ifdef HID_MOUSE_EPIN_SIZE
 *   #undef HID_MOUSE_EPIN_SIZE
 *   #endif
 *   #define HID_MOUSE_EPIN_SIZE           0x08U
 *
 * This ensures HID_MOUSE_EPIN_SIZE=8 in the patched compilation unit.
 * The build flag -D HID_MOUSE_EPIN_SIZE=0x08 also provides a global default.
 */

#endif /* USBCON */
#endif /* __USBD_EP_CONF_PATCH_H */
