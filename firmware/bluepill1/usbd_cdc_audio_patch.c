/** CDC ACM + UAC1 mono speaker class for Blue Pill 1. */
#if defined(USBCON) && defined(USBD_USE_CDC) && defined(SIMPLE_KVM_AUDIO)

#include "usbd_cdc.h"
#include "usbd_ctlreq.h"
#include "usbd_desc.h"
#include "usbd_ep_conf.h"
#include "audio_usb_out.h"

#define AUDIO_CONTROL_INTERFACE  0x02U
#define AUDIO_STREAM_INTERFACE   0x03U

const uint8_t simple_kvm_bp1_audio_config_descriptor[174] = {
  0x09, 0x02, 0xAE, 0x00, 0x04, 0x01, 0x00, 0x80, 0x32,

  /* CDC IAD, control interface 0 and data interface 1. */
  0x08, 0x0B, 0x00, 0x02, 0x02, 0x02, 0x01, 0x00,
  0x09, 0x04, 0x00, 0x00, 0x01, 0x02, 0x02, 0x01, 0x00,
  0x05, 0x24, 0x00, 0x10, 0x01,
  0x05, 0x24, 0x01, 0x00, 0x01,
  0x04, 0x24, 0x02, 0x02,
  0x05, 0x24, 0x06, 0x00, 0x01,
  0x07, 0x05, 0x83, 0x03, 0x08, 0x00, 0x10,
  0x09, 0x04, 0x01, 0x00, 0x02, 0x0A, 0x00, 0x00, 0x00,
  0x07, 0x05, 0x02, 0x02, 0x40, 0x00, 0x00,
  0x07, 0x05, 0x82, 0x02, 0x40, 0x00, 0x00,

  /* Audio IAD and Audio Control interface 2. */
  0x08, 0x0B, 0x02, 0x02, 0x01, 0x00, 0x00, 0x00,
  0x09, 0x04, 0x02, 0x00, 0x00, 0x01, 0x01, 0x00, 0x00,
  0x09, 0x24, 0x01, 0x00, 0x01, 0x1E, 0x00, 0x01, 0x03,
  0x0C, 0x24, 0x02, 0x01, 0x01, 0x01, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00,
  0x09, 0x24, 0x03, 0x02, 0x01, 0x03, 0x00, 0x01, 0x00,

  /* Audio Streaming interface 3, alt 0/1, fixed mono PCM16 48 kHz. */
  0x09, 0x04, 0x03, 0x00, 0x00, 0x01, 0x02, 0x00, 0x00,
  0x09, 0x04, 0x03, 0x01, 0x01, 0x01, 0x02, 0x00, 0x00,
  0x07, 0x24, 0x01, 0x01, 0x01, 0x01, 0x00,
  0x0B, 0x24, 0x02, 0x01, 0x01, 0x02, 0x10, 0x01, 0x80, 0xBB, 0x00,
  0x09, 0x05, 0x01, 0x0D, 0x60, 0x00, 0x01, 0x00, 0x00,
  0x07, 0x25, 0x01, 0x00, 0x00, 0x00, 0x00,
};

static const uint8_t kDeviceQualifier[10] = {
  0x0A, 0x06, 0x00, 0x02, 0xEF, 0x02, 0x01, 0x40, 0x01, 0x00,
};

typedef struct {
  uint8_t alt;
  uint8_t rx_index;
  uint8_t packet[2][AUDIO_OUT_PACKET_SIZE];
} AudioOutUsbState;

static USBD_CDC_HandleTypeDef g_cdc;
static AudioOutUsbState g_audio_out;

static uint8_t *audio_get_config(uint16_t *length)
{
  *length = (uint16_t)sizeof(simple_kvm_bp1_audio_config_descriptor);
  return (uint8_t *)(uintptr_t)simple_kvm_bp1_audio_config_descriptor;
}

static uint8_t *audio_get_qualifier(uint16_t *length)
{
  *length = (uint16_t)sizeof(kDeviceQualifier);
  return (uint8_t *)(uintptr_t)kDeviceQualifier;
}

static void audio_close(USBD_HandleTypeDef *pdev)
{
  if (g_audio_out.alt != 0U) {
    (void)USBD_LL_CloseEP(pdev, AUDIO_OUT_EP);
    pdev->ep_out[AUDIO_OUT_EP & 0x0FU].is_used = 0U;
  }
  g_audio_out.alt = 0U;
  g_audio_out.rx_index = 0U;
  bp1_audio_usb_on_alt(0U);
}

static uint8_t audio_set_alt(USBD_HandleTypeDef *pdev, uint8_t alt)
{
  if (alt > 1U) {
    return (uint8_t)USBD_FAIL;
  }
  if (g_audio_out.alt == alt) {
    return (uint8_t)USBD_OK;
  }
  audio_close(pdev);
  if (alt == 1U) {
    (void)USBD_LL_OpenEP(pdev, AUDIO_OUT_EP, USBD_EP_TYPE_ISOC,
                         AUDIO_OUT_PACKET_SIZE);
    pdev->ep_out[AUDIO_OUT_EP & 0x0FU].is_used = 1U;
    pdev->ep_out[AUDIO_OUT_EP & 0x0FU].bInterval = 1U;
    g_audio_out.alt = 1U;
    bp1_audio_usb_on_alt(1U);
    (void)USBD_LL_PrepareReceive(pdev, AUDIO_OUT_EP,
                                 g_audio_out.packet[0],
                                 AUDIO_OUT_PACKET_SIZE);
  }
  return (uint8_t)USBD_OK;
}

static uint8_t cdc_audio_init(USBD_HandleTypeDef *pdev, uint8_t cfgidx)
{
  USBD_CDC_ItfTypeDef *interface;
  (void)cfgidx;
  (void)USBD_memset(&g_cdc, 0, sizeof(g_cdc));
  g_cdc.CmdOpCode = 0xFFU;
  pdev->pClassDataCmsit[pdev->classId] = &g_cdc;
  pdev->pClassData = &g_cdc;

  /* The stock LL table loop has one entry fewer than this bidirectional EP2
   * layout.  Configure the sixth directional PMA entry explicitly. */
  (void)HAL_PCDEx_PMAConfig((PCD_HandleTypeDef *)pdev->pData, CDC_OUT_EP,
                            PCD_SNG_BUF, PMA_CDC_OUT_ADDR);

  (void)USBD_LL_OpenEP(pdev, CDC_IN_EP, USBD_EP_TYPE_BULK,
                       CDC_DATA_FS_MAX_PACKET_SIZE);
  (void)USBD_LL_OpenEP(pdev, CDC_OUT_EP, USBD_EP_TYPE_BULK,
                       CDC_DATA_FS_MAX_PACKET_SIZE);
  (void)USBD_LL_OpenEP(pdev, CDC_CMD_EP, USBD_EP_TYPE_INTR,
                       CDC_CMD_PACKET_SIZE);
  pdev->ep_in[CDC_IN_EP & 0x0FU].is_used = 1U;
  pdev->ep_out[CDC_OUT_EP & 0x0FU].is_used = 1U;
  pdev->ep_in[CDC_CMD_EP & 0x0FU].is_used = 1U;
  pdev->ep_in[CDC_CMD_EP & 0x0FU].bInterval = 16U;

  interface = (USBD_CDC_ItfTypeDef *)pdev->pUserData[pdev->classId];
  if (interface == NULL || interface->Init() != 0 || g_cdc.RxBuffer == NULL) {
    return (uint8_t)USBD_FAIL;
  }
  (void)USBD_LL_PrepareReceive(pdev, CDC_OUT_EP, g_cdc.RxBuffer,
                               CDC_DATA_FS_MAX_PACKET_SIZE);
  g_audio_out.alt = 0U;
  g_audio_out.rx_index = 0U;
  return (uint8_t)USBD_OK;
}

static uint8_t cdc_audio_deinit(USBD_HandleTypeDef *pdev, uint8_t cfgidx)
{
  USBD_CDC_ItfTypeDef *interface;
  (void)cfgidx;
  audio_close(pdev);
  (void)USBD_LL_CloseEP(pdev, CDC_IN_EP);
  (void)USBD_LL_CloseEP(pdev, CDC_OUT_EP);
  (void)USBD_LL_CloseEP(pdev, CDC_CMD_EP);
  pdev->ep_in[CDC_IN_EP & 0x0FU].is_used = 0U;
  pdev->ep_out[CDC_OUT_EP & 0x0FU].is_used = 0U;
  pdev->ep_in[CDC_CMD_EP & 0x0FU].is_used = 0U;
  interface = (USBD_CDC_ItfTypeDef *)pdev->pUserData[pdev->classId];
  if (interface != NULL) {
    (void)interface->DeInit();
  }
  pdev->pClassDataCmsit[pdev->classId] = NULL;
  pdev->pClassData = NULL;
  return (uint8_t)USBD_OK;
}

static uint8_t cdc_setup(USBD_HandleTypeDef *pdev, USBD_SetupReqTypedef *req)
{
  USBD_CDC_ItfTypeDef *interface =
      (USBD_CDC_ItfTypeDef *)pdev->pUserData[pdev->classId];
  uint16_t status = 0U;
  uint8_t alt = 0U;
  if (interface == NULL) {
    return (uint8_t)USBD_FAIL;
  }
  if ((req->bmRequest & USB_REQ_TYPE_MASK) == USB_REQ_TYPE_CLASS) {
    if (req->wLength != 0U) {
      if ((req->bmRequest & 0x80U) != 0U) {
        (void)interface->Control(req->bRequest, (uint8_t *)g_cdc.data,
                                 req->wLength);
        (void)USBD_CtlSendData(pdev, (uint8_t *)g_cdc.data,
                               MIN(CDC_REQ_MAX_DATA_SIZE, req->wLength));
      } else {
        g_cdc.CmdOpCode = req->bRequest;
        g_cdc.CmdLength = (uint8_t)MIN(req->wLength, USB_MAX_EP0_SIZE);
        (void)USBD_CtlPrepareRx(pdev, (uint8_t *)g_cdc.data,
                                g_cdc.CmdLength);
      }
    } else {
      (void)interface->Control(req->bRequest, (uint8_t *)req, 0U);
    }
    return (uint8_t)USBD_OK;
  }
  if ((req->bmRequest & USB_REQ_TYPE_MASK) == USB_REQ_TYPE_STANDARD) {
    switch (req->bRequest) {
      case USB_REQ_GET_STATUS:
        (void)USBD_CtlSendData(pdev, (uint8_t *)&status, 2U);
        return (uint8_t)USBD_OK;
      case USB_REQ_GET_INTERFACE:
        (void)USBD_CtlSendData(pdev, &alt, 1U);
        return (uint8_t)USBD_OK;
      case USB_REQ_SET_INTERFACE:
      case USB_REQ_CLEAR_FEATURE:
        return (uint8_t)USBD_OK;
      default:
        break;
    }
  }
  USBD_CtlError(pdev, req);
  return (uint8_t)USBD_FAIL;
}

static uint8_t audio_setup(USBD_HandleTypeDef *pdev, USBD_SetupReqTypedef *req)
{
  const uint8_t interface_number = (uint8_t)(req->wIndex & 0xFFU);
  uint16_t status = 0U;
  if ((req->bmRequest & USB_REQ_TYPE_MASK) == USB_REQ_TYPE_STANDARD) {
    switch (req->bRequest) {
      case USB_REQ_GET_STATUS:
        (void)USBD_CtlSendData(pdev, (uint8_t *)&status, 2U);
        return (uint8_t)USBD_OK;
      case USB_REQ_GET_INTERFACE: {
        uint8_t alt = interface_number == AUDIO_STREAM_INTERFACE
                          ? g_audio_out.alt
                          : 0U;
        (void)USBD_CtlSendData(pdev, &alt, 1U);
        return (uint8_t)USBD_OK;
      }
      case USB_REQ_SET_INTERFACE:
        if (interface_number == AUDIO_STREAM_INTERFACE &&
            audio_set_alt(pdev, (uint8_t)req->wValue) == (uint8_t)USBD_OK) {
          return (uint8_t)USBD_OK;
        }
        break;
      default:
        break;
    }
  }
  USBD_CtlError(pdev, req);
  return (uint8_t)USBD_FAIL;
}

static uint8_t cdc_audio_setup(USBD_HandleTypeDef *pdev,
                               USBD_SetupReqTypedef *req)
{
  const uint8_t interface_number = (uint8_t)(req->wIndex & 0xFFU);
  return interface_number >= AUDIO_CONTROL_INTERFACE
             ? audio_setup(pdev, req)
             : cdc_setup(pdev, req);
}

static uint8_t cdc_audio_ep0_ready(USBD_HandleTypeDef *pdev)
{
  USBD_CDC_ItfTypeDef *interface =
      (USBD_CDC_ItfTypeDef *)pdev->pUserData[pdev->classId];
  if (interface != NULL && g_cdc.CmdOpCode != 0xFFU) {
    (void)interface->Control(g_cdc.CmdOpCode, (uint8_t *)g_cdc.data,
                             g_cdc.CmdLength);
    g_cdc.CmdOpCode = 0xFFU;
  }
  return (uint8_t)USBD_OK;
}

static uint8_t cdc_audio_datain(USBD_HandleTypeDef *pdev, uint8_t epnum)
{
  PCD_HandleTypeDef *hpcd = (PCD_HandleTypeDef *)pdev->pData;
  if ((epnum & 0x7FU) != (CDC_IN_EP & 0x7FU)) {
    return (uint8_t)USBD_OK;
  }
  if ((pdev->ep_in[epnum & 0x0FU].total_length > 0U) &&
      ((pdev->ep_in[epnum & 0x0FU].total_length %
        hpcd->IN_ep[epnum & 0x0FU].maxpacket) == 0U)) {
    pdev->ep_in[epnum & 0x0FU].total_length = 0U;
    (void)USBD_LL_Transmit(pdev, epnum, NULL, 0U);
  } else {
    USBD_CDC_ItfTypeDef *interface =
        (USBD_CDC_ItfTypeDef *)pdev->pUserData[pdev->classId];
    g_cdc.TxState = 0U;
    if (interface != NULL && interface->TransmitCplt != NULL) {
      (void)interface->TransmitCplt(g_cdc.TxBuffer, &g_cdc.TxLength, epnum);
    }
  }
  return (uint8_t)USBD_OK;
}

static uint8_t cdc_audio_dataout(USBD_HandleTypeDef *pdev, uint8_t epnum)
{
  if ((epnum & 0x7FU) == (AUDIO_OUT_EP & 0x7FU)) {
    const uint32_t received = USBD_LL_GetRxDataSize(pdev, epnum);
    if (g_audio_out.alt == 1U) {
      bp1_audio_usb_receive_packet(g_audio_out.packet[g_audio_out.rx_index],
                                   (uint16_t)received);
      g_audio_out.rx_index ^= 1U;
      (void)USBD_LL_PrepareReceive(
          pdev, AUDIO_OUT_EP, g_audio_out.packet[g_audio_out.rx_index],
          AUDIO_OUT_PACKET_SIZE);
    }
    return (uint8_t)USBD_OK;
  }
  if ((epnum & 0x7FU) == (CDC_OUT_EP & 0x7FU)) {
    USBD_CDC_ItfTypeDef *interface =
        (USBD_CDC_ItfTypeDef *)pdev->pUserData[pdev->classId];
    g_cdc.RxLength = USBD_LL_GetRxDataSize(pdev, epnum);
    if (interface != NULL) {
      (void)interface->Receive(g_cdc.RxBuffer, &g_cdc.RxLength);
    }
    return (uint8_t)USBD_OK;
  }
  return (uint8_t)USBD_FAIL;
}

USBD_ClassTypeDef USBD_CDC = {
  cdc_audio_init,
  cdc_audio_deinit,
  cdc_audio_setup,
  NULL,
  cdc_audio_ep0_ready,
  cdc_audio_datain,
  cdc_audio_dataout,
  NULL,
  NULL,
  NULL,
  audio_get_config,
  audio_get_config,
  audio_get_config,
  audio_get_qualifier,
};

uint8_t USBD_CDC_RegisterInterface(USBD_HandleTypeDef *pdev,
                                   USBD_CDC_ItfTypeDef *fops)
{
  if (fops == NULL) {
    return (uint8_t)USBD_FAIL;
  }
  pdev->pUserData[pdev->classId] = fops;
  return (uint8_t)USBD_OK;
}

uint8_t USBD_CDC_SetTxBuffer(USBD_HandleTypeDef *pdev, uint8_t *buffer,
                             uint32_t length)
{
  USBD_CDC_HandleTypeDef *cdc =
      (USBD_CDC_HandleTypeDef *)pdev->pClassDataCmsit[pdev->classId];
  if (cdc == NULL) {
    return (uint8_t)USBD_FAIL;
  }
  cdc->TxBuffer = buffer;
  cdc->TxLength = length;
  return (uint8_t)USBD_OK;
}

uint8_t USBD_CDC_SetRxBuffer(USBD_HandleTypeDef *pdev, uint8_t *buffer)
{
  USBD_CDC_HandleTypeDef *cdc =
      (USBD_CDC_HandleTypeDef *)pdev->pClassDataCmsit[pdev->classId];
  if (cdc == NULL) {
    return (uint8_t)USBD_FAIL;
  }
  cdc->RxBuffer = buffer;
  return (uint8_t)USBD_OK;
}

uint8_t USBD_CDC_TransmitPacket(USBD_HandleTypeDef *pdev)
{
  USBD_CDC_HandleTypeDef *cdc =
      (USBD_CDC_HandleTypeDef *)pdev->pClassDataCmsit[pdev->classId];
  if (cdc == NULL) {
    return (uint8_t)USBD_FAIL;
  }
  if (cdc->TxState != 0U) {
    return (uint8_t)USBD_BUSY;
  }
  cdc->TxState = 1U;
  pdev->ep_in[CDC_IN_EP & 0x0FU].total_length = cdc->TxLength;
  (void)USBD_LL_Transmit(pdev, CDC_IN_EP, cdc->TxBuffer, cdc->TxLength);
  return (uint8_t)USBD_OK;
}

uint8_t USBD_CDC_ReceivePacket(USBD_HandleTypeDef *pdev)
{
  USBD_CDC_HandleTypeDef *cdc =
      (USBD_CDC_HandleTypeDef *)pdev->pClassDataCmsit[pdev->classId];
  if (cdc == NULL) {
    return (uint8_t)USBD_FAIL;
  }
  (void)USBD_LL_PrepareReceive(pdev, CDC_OUT_EP, cdc->RxBuffer,
                               CDC_DATA_FS_OUT_PACKET_SIZE);
  return (uint8_t)USBD_OK;
}

uint8_t USBD_CDC_ClearBuffer(USBD_HandleTypeDef *pdev)
{
  if (pdev->pClassDataCmsit[pdev->classId] == NULL) {
    return (uint8_t)USBD_FAIL;
  }
  (void)USBD_LL_PrepareReceive(pdev, CDC_OUT_EP, NULL, 0U);
  return (uint8_t)USBD_OK;
}

#endif
