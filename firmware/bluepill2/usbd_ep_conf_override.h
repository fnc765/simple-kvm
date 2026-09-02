/**
  ******************************************************************************
  * @file    usbd_ep_conf_override.h
  * @brief   Blue Pill 2 endpoint configuration for three HID interfaces
  *
  * This header is force-included for the complete bluepill2 environment.
  * STM32duino's stock HID-composite endpoint header defines only EP0..EP2;
  * forcing the matching four-endpoint definition here also makes the framework
  * USB low-level initializer configure EP3 and reserve its PMA descriptor.
  ******************************************************************************
  */

#ifndef SIMPLE_KVM_USBD_EP_CONF_OVERRIDE_H
#define SIMPLE_KVM_USBD_EP_CONF_OVERRIDE_H

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

#define HID_MOUSE_EPIN_ADDR            0x81U
#define HID_KEYBOARD_EPIN_ADDR         0x82U
#define HID_ABS_MOUSE_EPIN_ADDR        0x83U

#define HID_MOUSE_EPIN_SIZE            0x08U
#define HID_KEYBOARD_EPIN_SIZE         0x08U
#define HID_ABS_MOUSE_EPIN_SIZE        0x08U

/* EP0 plus three HID IN endpoints. */
#define DEV_NUM_EP                     0x04U

#if defined(USB)
/* Size in words, byte size divided by 2. */
#define PMA_EP0_OUT_ADDR               (8 * DEV_NUM_EP)
#define PMA_EP0_IN_ADDR                (PMA_EP0_OUT_ADDR + USB_MAX_EP0_SIZE)
#define PMA_MOUSE_IN_ADDR              (PMA_EP0_IN_ADDR + HID_MOUSE_EPIN_SIZE)
#define PMA_KEYBOARD_IN_ADDR           (PMA_MOUSE_IN_ADDR + HID_KEYBOARD_EPIN_SIZE)
#define PMA_ABS_MOUSE_IN_ADDR          (PMA_KEYBOARD_IN_ADDR + HID_ABS_MOUSE_EPIN_SIZE)
#endif

extern const ep_desc_t ep_def[DEV_NUM_EP + 1];

/* Prevent the stock three-endpoint header from replacing these definitions. */
#define __USBD_EP_CONF_H

#endif /* USBCON */
#endif /* SIMPLE_KVM_USBD_EP_CONF_OVERRIDE_H */
