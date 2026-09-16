"""Select project USB patches without relying on duplicate-symbol link order."""

Import("env")


profile = env.GetProjectOption("custom_usb_patch")

common_stock_sources = (
    "/usbdevice/src/usbd_ep_conf.c",
    "/usbdevice/src/usbd_desc.c",
)
profile_stock_sources = {
    "bp1_audio": common_stock_sources + ("/usbdevice/src/cdc/usbd_cdc.c",),
    "bp2": common_stock_sources +
           ("/usbdevice/src/hid/usbd_hid_composite.c",),
}


def replace_stock_usb(node):
    path = node.srcnode().get_abspath().replace("\\", "/").lower()
    if any(path.endswith(suffix) for suffix in profile_stock_sources[profile]):
        return None
    return node


env.AddBuildMiddleware(replace_stock_usb)
