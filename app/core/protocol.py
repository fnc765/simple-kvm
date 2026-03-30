"""
protocol.py – KVM serial packet encoder.

Packet format:
  [0xAA] [TYPE] [LEN] [PAYLOAD × LEN] [CHECKSUM]
  CHECKSUM = TYPE ^ LEN ^ PAYLOAD[0] ^ ... ^ PAYLOAD[LEN-1]
"""

PKT_START     = 0xAA
PKT_KEYBOARD  = 0x01
PKT_MOUSE     = 0x02
PKT_HEARTBEAT = 0xFF


def _build_packet(pkt_type: int, payload: bytes) -> bytes:
    """Assemble a framed packet with checksum."""
    length = len(payload)
    if length > 255:
        raise ValueError(f"Payload too large: {length} bytes (max 255)")
    checksum = pkt_type ^ length
    for b in payload:
        checksum ^= b
    checksum &= 0xFF
    return bytes([PKT_START, pkt_type, length]) + payload + bytes([checksum])


def build_keyboard_report(modifier: int, keys: list[int]) -> bytes:
    """
    Build a PKT_KEYBOARD packet.

    Args:
        modifier: HID modifier bitmask (LCtrl=0x01, LShift=0x02, LAlt=0x04,
                  LGUI=0x08, RCtrl=0x10, RShift=0x20, RAlt=0x40, RGUI=0x80)
        keys:     List of up to 6 HID Usage IDs (0x00 = empty slot).

    Returns:
        Framed 12-byte packet (3 header + 8 payload + 1 checksum).
    """
    padded = (list(keys) + [0, 0, 0, 0, 0, 0])[:6]
    payload = bytes([modifier & 0xFF, 0x00] + padded)
    return _build_packet(PKT_KEYBOARD, payload)


def build_mouse_report(
    buttons: int,
    dx: int,
    dy: int,
    wheel_v: int = 0,
    wheel_h: int = 0,
) -> bytes:
    """
    Build a PKT_MOUSE packet.

    Args:
        buttons: Button bitmask (bit0=Left, bit1=Right, bit2=Middle)
        dx:      Relative X movement, clamped to [-127, 127]
        dy:      Relative Y movement, clamped to [-127, 127]
        wheel_v: Vertical scroll, clamped to [-127, 127]
        wheel_h: Horizontal scroll, clamped to [-127, 127]

    Returns:
        Framed 9-byte packet (3 header + 5 payload + 1 checksum).
    """
    dx      = max(-127, min(127, dx))
    dy      = max(-127, min(127, dy))
    wheel_v = max(-127, min(127, wheel_v))
    wheel_h = max(-127, min(127, wheel_h))

    payload = bytes([
        buttons & 0x07,  # clamp to 3 valid button bits
        dx      & 0xFF,
        dy      & 0xFF,
        wheel_v & 0xFF,
        wheel_h & 0xFF,
    ])
    return _build_packet(PKT_MOUSE, payload)


def build_heartbeat() -> bytes:
    """Build a PKT_HEARTBEAT packet (no payload)."""
    return _build_packet(PKT_HEARTBEAT, b"")
