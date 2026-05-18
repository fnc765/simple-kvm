/**
  ******************************************************************************
  * @file    usbd_hid_composite_patch.h
  * @brief   Patch: HID Composite header for Logitech Unifying Receiver emulation
  *
  * Changes from original usbd_hid_composite.h:
  *   - Interface order swapped: Keyboard=0x00, Mouse=0x01
  *   - HID_MOUSE_REPORT_DESC_SIZE: 74→76 (5-byte mouse report)
  *   - HID_KEYBOARD_REPORT_DESC_SIZE: 45→61 (Boot Keyboard with LED output)
  *   - #ifndef guards for HID_MOUSE_EPIN_SIZE and HID_FS_BINTERVAL
  *
  * Original source:
  *   ~/.platformio/packages/framework-arduinoststm32/libraries/USBDevice/src/hid/usbd_hid_composite.h
  ******************************************************************************
  */

/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __USB_HID_COMPOSITE_PATCH_H
#define __USB_HID_COMPOSITE_PATCH_H

#ifdef USBCON
#ifdef USBD_USE_HID_COMPOSITE

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/
#include "usbd_ioreq.h"
#include "usbd_ep_conf.h"

/* Override endpoint sizes: usbd_ep_conf.h defines these unconditionally */
#ifdef HID_MOUSE_EPIN_SIZE
#undef HID_MOUSE_EPIN_SIZE
#endif
#define HID_MOUSE_EPIN_SIZE           0x08U

#ifdef HID_FS_BINTERVAL
#undef HID_FS_BINTERVAL
#endif
#define HID_FS_BINTERVAL              0x08U

/** @defgroup USBD_HID_Exported_Defines
  * @{
  */
/* PATCHED: Keyboard is interface 0, Mouse is interface 1 */
#define HID_MOUSE_INTERFACE           0x01U
#define HID_KEYBOARD_INTERFACE        0x00U

#define USB_COMPOSITE_HID_CONFIG_DESC_SIZ       59U
#define USB_HID_DESC_SIZ              9U
/* PATCHED: 5-byte mouse report (buttons + X + Y + wheel_v + wheel_h) */
#define HID_MOUSE_REPORT_DESC_SIZE    76U
/* PATCHED: Boot Keyboard with LED output (67 bytes) */
#define HID_KEYBOARD_REPORT_DESC_SIZE 67U

#define HID_DESCRIPTOR_TYPE           0x21
#define HID_REPORT_DESC               0x22

#ifndef HID_HS_BINTERVAL
#define HID_HS_BINTERVAL              0x07U
#endif /* HID_HS_BINTERVAL */

#define HID_REQ_SET_PROTOCOL          0x0BU
#define HID_REQ_GET_PROTOCOL          0x03U

#define HID_REQ_SET_IDLE              0x0AU
#define HID_REQ_GET_IDLE              0x02U

#define HID_REQ_SET_REPORT            0x09U
#define HID_REQ_GET_REPORT            0x01U
/**
  * @}
  */


/** @defgroup USBD_CORE_Exported_TypesDefinitions
  * @{
  */
typedef enum {
  HID_IDLE = 0,
  HID_BUSY,
} HID_StateTypeDef;


typedef struct {
  uint32_t             Protocol;
  uint32_t             IdleState;
  uint32_t             AltSetting;
  HID_StateTypeDef     Mousestate;
  HID_StateTypeDef     Keyboardstate;
} USBD_HID_HandleTypeDef;

/*
 * HID Class specification version 1.1
 * 6.2.1 HID Descriptor
 */

typedef struct {
  uint8_t           bLength;
  uint8_t           bDescriptorType;
  uint16_t          bcdHID;
  uint8_t           bCountryCode;
  uint8_t           bNumDescriptors;
  uint8_t           bHIDDescriptorType;
  uint16_t          wItemLength;
} __PACKED USBD_HIDDescTypeDef;

/**
  * @}
  */



/** @defgroup USBD_CORE_Exported_Macros
  * @{
  */

/**
  * @}
  */

/** @defgroup USBD_CORE_Exported_Variables
  * @{
  */

extern USBD_ClassTypeDef  USBD_COMPOSITE_HID;
#define USBD_COMPOSITE_HID_CLASS    &USBD_COMPOSITE_HID
/**
  * @}
  */

/** @defgroup USB_CORE_Exported_Functions
  * @{
  */
#ifdef USE_USBD_COMPOSITE
uint8_t USBD_HID_MOUSE_SendReport(USBD_HandleTypeDef *pdev,
                                  uint8_t *report,
                                  uint16_t len,
                                  uint8_t ClassId);
uint8_t USBD_HID_KEYBOARD_SendReport(USBD_HandleTypeDef *pdev,
                                     uint8_t *report,
                                     uint16_t len,
                                     uint8_t ClassId);
#else
uint8_t USBD_HID_MOUSE_SendReport(USBD_HandleTypeDef *pdev,
                                  uint8_t *report,
                                  uint16_t len);
uint8_t USBD_HID_KEYBOARD_SendReport(USBD_HandleTypeDef *pdev,
                                     uint8_t *report,
                                     uint16_t len);
#endif /* USE_USBD_COMPOSITE */

uint32_t USBD_HID_GetPollingInterval(USBD_HandleTypeDef *pdev);

#ifdef __cplusplus
}
#endif

#endif /* USBD_USE_HID_COMPOSITE */
#endif /* USBCON */
#endif /* __USB_HID_COMPOSITE_PATCH_H */
/************************ (C) COPYRIGHT STMicroelectronics *****END OF FILE****/
