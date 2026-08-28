/**
  ******************************************************************************
  * @file    usbd_ep_conf_patch.h
  * @brief   Compatibility note for the endpoint configuration override
  *
  * The active PlatformIO override is usbd_ep_conf_override.h.  It is
  * force-included for every bluepill2 translation unit so STM32duino's
  * low-level USB initializer and the project patch use the same endpoint count.
  *
  * Changes:
  *   - HID_MOUSE_EPIN_SIZE: 0x04 → 0x08 (8-byte mouse endpoint for 5-byte report)
  *   - DEV_NUM_EP: 0x03 -> 0x04 (EP0 plus three HID IN endpoints)
  *   - PMA buffer addresses include the absolute-mouse endpoint
  *
  * Original source:
  *   ~/.platformio/packages/framework-arduinoststm32/libraries/USBDevice/inc/usbd_ep_conf.h
  ******************************************************************************
  */

#ifndef __USBD_EP_CONF_PATCH_H
#define __USBD_EP_CONF_PATCH_H

#ifdef USBCON

/*
 * Kept as a named compatibility/documentation header for existing references.
 * New code should include usbd_ep_conf.h normally; platformio.ini injects the
 * complete project override before STM32duino's stock header is parsed.
 */

#endif /* USBCON */
#endif /* __USBD_EP_CONF_PATCH_H */
