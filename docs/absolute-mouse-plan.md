<!--
sessionId: 20260624-115212-2ba9
threadUrl: https://chatgpt.com/c/6a3bc4f5-7138-83ee-a494-379e31a2dd5a
bundle: C:\Users\choco\Documents\programming\simple-kvm\.codex\chatgpt-bridge\bundles\20260624-115212-2ba9.zip
capturedAt: 2026-06-24T12:19:53.952Z
-->

以下が最終版の Markdown 実装プランです。Codex にそのまま渡す前提で、実装順・変更ファイル・テスト観点を具体化しています。

編集# simple-kvm 絶対座標マウス対応 実装計画

## 1. Goal clarification

### 1.1 解決したい問題

simple-kvm には現在、次の 2 つのマウス操作上の問題がある。

1. SteamVR Desktop dashboard / OVR Advanced Settings などの VR 内 UI を操作しづらい

- 現在の BluePill #2 はターゲット PC から見ると相対マウスとして認識されている。
- 相対マウスは「現在の画面上の絶対位置」を USB HID report として送れない。
- SteamVR の Desktop dashboard など、Windows desktop cursor と座標対応する UI では、狙った UI 要素にカーソルを合わせづらい。
- ただし、OVR Advanced Settings の dashboard overlay は OpenVR overlay event 経路で操作されるため、absolute HID mouse だけで完全対応できるとは限らない。
2. KVM 開始時にターゲット PC 側のカーソル位置が毎回ずれる

- 現在の KVM focus mode は、ホスト側カーソルを VideoWidget 中央に warp し、中央からの差分を relative dx/dy としてターゲットに送る。
- ターゲット PC 側は「ホスト側でどこをクリックして KVM を開始したか」を知らない。
- そのため、simple-kvm の映像上でクリックした位置と、ターゲット PC 側の現在 cursor 位置が一致しない。
- 本来は、VideoWidget 上のクリック座標をターゲット desktop 座標に変換し、KVM 開始時にターゲット cursor をそこへ jump させたい。

### 1.2 実装ゴール

本実装の主要ゴールは、ターゲット Windows cursor を simple-kvm のキャプチャ映像上の座標へ同期できるようにすることである。

初期スコープでは次を実現する。

- `Relative` mode: 既存の中央 warp + relative mouse 動作を維持する。
- `Hybrid` mode: KVM 開始時だけ absolute cursor jump を行い、その後は relative mouse で操作する。
- `Absolute` mode: VideoWidget 内のホスト cursor 位置を継続的に absolute HID mouse report として送る。
- SteamVR Desktop dashboard / desktop overlay では `Absolute` mode により操作改善を狙う。
- OVR Advanced Settings の in-VR dashboard overlay 完全対応は保証しない。これは OpenVR overlay event injection が必要になる可能性があるため、今回の Done criteria から外す。

### 1.3 初期サポート条件

最初の Done criteria は次の環境に限定する。

```
Target OS: Windows
Target display: single monitor
Captured display: primary monitor
Target resolution: capture source と同一、初期想定 1920x1080
Windows DPI scaling: 100%
SteamVR: closed または Desktop dashboard のみ追加検証
```

multi-monitor、mixed DPI、non-primary monitor capture、SteamVR 側の cursor offset bug は Phase 後半または別フェーズで扱う。

## 2. Existing architecture summary

### 2.1 Host application

現在の Python GUI は以下の構成。

- `app/ui/mainwindow.py`

- `MainWindow`
- `VideoWidget(QLabel)`
- KVM focus mode 管理
- `mousePressEvent`, `mouseMoveEvent`, `mouseReleaseEvent`, `wheelEvent`
- `QCursor.setPos()` による中央固定
- `warp_pending` による synthetic mouse move 抑制
- `SerialComm.enqueue()` による packet 送信
- `app/core/protocol.py`

- `PKT_KEYBOARD = 0x01`
- `PKT_MOUSE = 0x02`
- `PKT_HEARTBEAT = 0xFF`
- `_build_packet()`
- `build_keyboard_report()`
- `build_mouse_report()`
- `build_heartbeat()`
- `app/core/input_hook.py`

- keyboard / mouse button state 管理
- Raw Input keyboard hook
- `app/core/serial_comm.py`

- Qt thread 上で COM port へ packet を送信
- queue size は 64
- `app/ui/settings_dialog.py`

- COM port
- capture device
- aspect ratio
- mouse speed

### 2.2 Current mouse behavior

現在の KVM focus mode は次の処理を行う。

```
VideoWidget click
  -> _kvm_click_timer start
  -> _activate_kvm_from_click()
  -> _set_kvm_active(True)
  -> self.setCursor(BlankCursor)
  -> _recompute_center()
  -> QCursor.setPos(center)

mouseMoveEvent
  -> warp_pending なら無視
  -> global_pos - center から dx/dy
  -> mouse_speed multiplier
  -> build_mouse_report(buttons, dx, dy)
  -> QCursor.setPos(center)
```

この設計は FPS / ゲーム用途の relative mouse と相性がよい一方、desktop / overlay UI 操作には不向き。

### 2.3 Current serial protocol

現在の packet format:

```
[0xAA] [TYPE] [LEN] [PAYLOAD × LEN] [CRC-8]
CRC-8-CCITT over TYPE + LEN + PAYLOAD
```

既存 type:

```
0x01 PKT_KEYBOARD  LEN=8
0x02 PKT_MOUSE     LEN=5  [buttons, dx, dy, wheel_v, wheel_h]
0xFF PKT_HEARTBEAT LEN=0
```

`PKT_MOUSE` は relative only。

### 2.4 Firmware architecture

現在の firmware は以下。

- `firmware/common/packet_parser.h`
- `firmware/common/packet_parser.cpp`

- CRC-8 検証
- payload 最大 16 bytes
- 50 ms parser timeout
- `firmware/bluepill1/main.cpp`

- USB CDC → UART forwarding
- `firmware/bluepill2/main.cpp`

- UART1 から packet を受信
- `PKT_KEYBOARD` を keyboard HID report として送信
- `PKT_MOUSE` を relative mouse HID report として送信
- `firmware/bluepill2/hid_handler.h`
- `firmware/bluepill2/hid_handler.cpp`

- keyboard report validation
- mouse report validation
- `firmware/bluepill2/usbd_hid_composite_patch.c`
- `firmware/bluepill2/usbd_hid_composite_patch.h`

- STM32duino 内蔵 HID Composite を patch
- 現在は 2 interface 構成

- Interface 0: Boot Keyboard
- Interface 1: Relative Mouse
- `USB_COMPOSITE_HID_CONFIG_DESC_SIZ = 59`
- `bNumInterfaces = 2`
- mouse endpoint / keyboard endpoint を open
- `USBD_HID_MOUSE_SendReport()`
- `USBD_HID_KEYBOARD_SendReport()`
- `USBD_HID_DataIn()` で busy state を解除

### 2.5 Firmware feasibility

BluePill #2 / STM32F103C8 で絶対座標 mouse report を追加することは実現可能と判断する。

ただし重要な制約がある。

- STM32duino 標準の `Mouse.move()` API は relative mouse 前提。
- absolute mouse / digitizer 用の高水準 API は使わない。
- 現在のリポジトリが既に行っている `usbd_hid_composite_patch.*` の patch 方式を拡張する。
- 既存 relative mouse interface に Report ID を追加して混在させる案は、既存 report format を壊すリスクがある。
- 推奨は 3rd HID interface 追加。

- Interface 0: Keyboard
- Interface 1: Relative Mouse
- Interface 2: Absolute Mouse / Absolute Pointer

## 3. Design decisions

### 3.1 Mouse modes

UI と内部設定では、次の 3 mode を使う。

```
relative
hybrid
absolute
```

#### relative

既存動作。

```
KVM active:
  hide cursor
  warp host cursor to VideoWidget center
  send relative dx/dy via PKT_MOUSE
```

#### hybrid

初期実装の本命。

```
KVM activation:
  activation click position -> source video coordinate -> HID absolute coordinate
  send PKT_MOUSE_ABS once

After activation:
  existing relative mode
  center warp remains enabled
```

目的:

- 「KVM 開始時に target cursor が毎回ずれる」問題を解消する。
- 既存の relative 操作感を維持する。
- SteamVR 以外の通常 KVM 用途にも有用。

#### absolute

Desktop / SteamVR Desktop dashboard 向け。

```
KVM active:
  do not hide host cursor by default
  do not warp to center
  VideoWidget local cursor position -> source video coordinate -> HID absolute coordinate
  send PKT_MOUSE_ABS on move / press / release
```

注意:

- FPS / relative mouse 前提アプリには不向き。
- mouse speed multiplier は適用しない。
- wheel は既存 `PKT_MOUSE` で送る。
- keyboard は既存通り転送する。

### 3.2 UI naming

避ける名称:

```
OVR Mode
SteamVR Mode
```

理由:

- OVR Advanced Settings の dashboard overlay は OpenVR overlay event 経路で操作される。
- absolute HID mouse は Windows cursor を動かすもので、OpenVR overlay event を直接注入しない。

推奨名称:

```
Mouse Mode
- Relative
- Hybrid: jump on activation, then relative
- Absolute: desktop / overlay helper
```

追加 setting:

```
Firmware supports absolute HID
Jump cursor on KVM activation
Fallback relative jump
```

ただし UI を増やしすぎないため、初期は次の最小構成にする。

- `Mouse Mode`

- Relative
- Hybrid
- Absolute
- `Firmware supports absolute HID`

- checkbox
- default false
- `Mouse Speed`

- 既存 relative mode 用
- `Aspect Ratio`

- 既存

`Jump cursor on KVM activation` は `Hybrid` mode に内包してよい。将来必要になったら独立設定化する。

### 3.3 Protocol extension

新 packet:

```
PKT_MOUSE_ABS = 0x03
LEN = 5
Payload = [buttons, x_lo, x_hi, y_lo, y_hi]
```

値域:

```
buttons: bit0=Left, bit1=Right, bit2=Middle
x: uint16 little-endian, 0..32767
y: uint16 little-endian, 0..32767
```

初期値域は `0..32767` を採用する。Windows absolute mouse の一般的な normalized coordinate として `0..65535` も候補だが、HID descriptor 側の logical max と一致させるため、初期実装は `0..32767` に統一する。将来 `0..65535` へ変える場合は protocol version または descriptor variant を分ける。

### 3.4 Backward compatibility

既存 firmware は `PKT_MOUSE_ABS` を知らない。現状の BP2 は unknown packet type で error blink する可能性がある。

したがって Host 側は次を守る。

- `input/firmware_abs_supported = false` を default にする。
- false の場合、`PKT_MOUSE_ABS` を送らない。
- user が明示的に true にした場合のみ `hybrid` / `absolute` で absolute packet を送る。
- `absolute` mode 選択時に firmware unsupported なら warning を表示し、実動作は `relative` または no-op に fallback する。

将来的には firmware capability handshake を追加できるが、Phase 2/3 の初期スコープでは手動 setting でよい。

### 3.5 Coordinate mapping

Host 側で次の座標変換を行う。

```
VideoWidget local coordinate
  -> displayed video rectangle coordinate
  -> source image coordinate
  -> HID absolute coordinate
```

source size は `VideoWidget._pixmap.width() / height()` または capture constant から取得する。現行 capture は README と settings 上では 1920x1080 前提だが、将来の可変解像度に備えて、実 frame の pixmap size を source of truth とする。

#### KeepAspectRatio

```
scale  = min(widget_w / source_w, widget_h / source_h)
disp_w = source_w * scale
disp_h = source_h * scale
x0     = (widget_w - disp_w) / 2
y0     = (widget_h - disp_h) / 2
```

```
video_x = clamp(local_x - x0, 0, disp_w - 1)
video_y = clamp(local_y - y0, 0, disp_h - 1)

src_x = video_x * (source_w - 1) / max(1, disp_w - 1)
src_y = video_y * (source_h - 1) / max(1, disp_h - 1)

hid_x = round(src_x * 32767 / max(1, source_w - 1))
hid_y = round(src_y * 32767 / max(1, source_h - 1))
```

黒帯をクリックした場合は、最近傍の映像端へ clamp する。

#### IgnoreAspectRatio / Stretch to Fill

```
disp_w = widget_w
disp_h = widget_h
x0 = 0
y0 = 0
```

同じ式で source 座標へ変換する。

#### HiDPI / DPR

現行 `VideoWidget._update_scaled_pixmap()` は `devicePixelRatioF()` を使い、scaled pixmap に DPR を設定している。

Qt の mouse event local coordinate と widget size は通常 logical pixel で揃うため、座標変換では DPR を直接掛けない。DPR を二重適用するとズレる。

TDD ではこの方針を明示的にテストする。

## 4. Files likely to change

### 4.1 Python host

#### `app/core/protocol.py`

追加:

- `PKT_MOUSE_ABS = 0x03`
- `HID_ABS_MAX = 32767`
- `build_mouse_abs_report(buttons: int, x: int, y: int) -> bytes`

要件:

- buttons は `0x07` に mask。
- x/y は `0..32767` に clamp。
- little-endian uint16。
- `_build_packet()` は既存のまま利用。
- 既存 `build_mouse_report()` の挙動を変えない。

#### `app/core/coordinates.py` 新規

純粋関数を置く。

想定 API:

```
@dataclass(frozen=True)
class Size2D:
    width: int
    height: int

@dataclass(frozen=True)
class Point2D:
    x: float
    y: float

@dataclass(frozen=True)
class VideoMapping:
    source_size: Size2D
    widget_size: Size2D
    displayed_origin: Point2D
    displayed_size: Size2D
    aspect_mode: str

@dataclass(frozen=True)
class MappedPoint:
    local_x: float
    local_y: float
    source_x: float
    source_y: float
    hid_x: int
    hid_y: int
    clamped: bool

def compute_video_mapping(source_size, widget_size, aspect_mode) -> VideoMapping:
    ...

def map_widget_point_to_hid(local_x, local_y, mapping, hid_max=32767) -> MappedPoint:
    ...
```

ここでは Qt 型に依存させない。pytest で直接検証できるようにする。

#### `app/core/mouse_modes.py` 新規

KVM mouse mode の判断ロジックを分離する。

想定定義:

```
class MouseMode(str, Enum):
    RELATIVE = "relative"
    HYBRID = "hybrid"
    ABSOLUTE = "absolute"

@dataclass(frozen=True)
class MouseModeConfig:
    mode: MouseMode
    firmware_abs_supported: bool
    fallback_relative_jump: bool = False
```

補助関数:

```
def normalize_mouse_mode(value: str) -> MouseMode:
    ...

def should_warp_cursor(config: MouseModeConfig) -> bool:
    # relative/hybrid: true
    # absolute: false
    ...

def should_hide_host_cursor(config: MouseModeConfig) -> bool:
    # relative/hybrid: true
    # absolute: false by default
    ...

def can_send_absolute(config: MouseModeConfig) -> bool:
    ...
```

必要に応じて、MainWindow 側に残る event 処理を薄くするための helper を追加する。

#### `app/ui/mainwindow.py`

修正内容:

- `build_mouse_abs_report` import 追加。
- `coordinates.py` の helper import 追加。
- `mouse_modes.py` の mode 定義 import 追加。
- settings 値追加:

- `_mouse_mode`
- `_firmware_abs_supported`
- `_fallback_relative_jump`
- KVM activation click position を保持:

- `_pending_kvm_activation_global_pos`
- または `_pending_kvm_activation_local_pos`
- `mousePressEvent()` の inactive branch で、クリック位置を保存してから timer start。
- `_activate_kvm_from_click()` / `_set_kvm_active(True)` で mode に応じた処理を分岐。
- `relative`:

- 既存挙動を維持。
- `hybrid`:

- firmware_abs_supported が true なら、KVM 開始直後に保存済み click position から `PKT_MOUSE_ABS` を 1 回送る。
- その後は既存通り center warp + relative。
- `absolute`:

- center warp しない。
- host cursor を hide しない。
- `mouseMoveEvent()` で VideoWidget local coordinate から absolute packet を送る。
- `mousePressEvent()` / `mouseReleaseEvent()` で buttons + current absolute coordinate を送る。
- wheel は既存 `build_mouse_report(buttons, 0, 0, wheel_v)` で送る。
- `_set_kvm_active(False)`:

- keyboard release は既存通り。
- relative mouse release packet は既存通り送る。
- absolute supported の場合は button release absolute packet も必要なら送る。ただし current coordinate がない場合は送らなくてよい。
- `fullscreen` transition:

- `relative` / `hybrid` の場合のみ `_recompute_center()` と warp を行う。
- `absolute` の場合は cursor center recompute は不要。
- `focusOutEvent` / `_on_focus_changed` は既存通り KVM deactivate。
- status bar message に mode を含める。

注意:

- 既存の `warp_pending` logic は `relative` / `hybrid` のみに適用する。
- `absolute` では `warp_pending` を使わない。
- `absolute` では `mouse_speed` を適用しない。
- `absolute` では move event の送信頻度が高くなる可能性があるため、同一座標の重複送信を抑制する。

- `_last_abs_x`
- `_last_abs_y`
- `_last_abs_buttons`

#### `app/ui/settings_dialog.py`

追加 UI:

- Mouse Mode combo:

- `Relative`
- `Hybrid: jump on activation, then relative`
- `Absolute: desktop / overlay helper`
- Firmware supports absolute HID checkbox:

- default false
- tooltip で「Phase 3 firmware を書き込んだ場合のみ有効化」と説明する。

`get_values()` の戻り値を拡張する。

既存呼び出し側との整合を取るため、tuple ではなく dataclass 化してもよい。

推奨:

```
@dataclass(frozen=True)
class SettingsValues:
    port: str
    device: str
    aspect: str
    mouse_speed: float
    mouse_mode: str
    firmware_abs_supported: bool
```

ただし変更範囲を抑えるなら tuple 拡張でもよい。

#### `app/core/serial_comm.py`

原則変更不要。

ただし `absolute` mode で packet 数が増えるため、queue overflow が見える場合は以下を検討する。

- queue size 64 → 128
- move packet の coalescing
- 同一 absolute coordinate の送信抑制

初期実装では `mainwindow.py` 側の重複抑制で対応する。

### 4.2 Firmware common

#### `firmware/common/packet_parser.h`

追加:

```
#define PKT_MOUSE_ABS 0x03u

#define PKT_LEN_MOUSE_ABS 5u
```

`PKT_MAX_PAYLOAD = 16` は変更不要。

#### `firmware/common/packet_parser.cpp`

変更不要。

parser は unknown type を type として通し、payload length も最大 16 まで扱えるため、Phase 2/3 では constant 追加だけでよい。

### 4.3 Firmware BluePill #2

#### `firmware/bluepill2/hid_handler.h`

追加:

```
typedef struct __attribute__((packed)) {
    uint8_t buttons;
    uint16_t x;
    uint16_t y;
} KVMMouseAbsReport;

bool validate_mouse_abs_report(const uint8_t *payload, uint8_t len);
```

button bitmask は relative mouse と同じ。

#### `firmware/bluepill2/hid_handler.cpp`

追加 validation:

```
bool validate_mouse_abs_report(const uint8_t *payload, uint8_t len)
{
    if (len < 5) return false;
    if (payload[0] & 0xF8) return false;

    uint16_t x = payload[1] | (payload[2] << 8);
    uint16_t y = payload[3] | (payload[4] << 8);

    if (x > 32767) return false;
    if (y > 32767) return false;

    return true;
}
```

#### `firmware/bluepill2/main.cpp`

追加:

- `hid_send_mouse_abs(const Packet *p)`
- switch に `case PKT_MOUSE_ABS`

処理:

```
static void hid_send_mouse_abs(const Packet *p)
{
    if (p->len != PKT_LEN_MOUSE_ABS) return;
    if (!validate_mouse_abs_report(p->payload, p->len)) {
        g_err_count = 6;
        return;
    }

    uint8_t report[5];
    report[0] = p->payload[0]; // buttons
    report[1] = p->payload[1]; // x lo
    report[2] = p->payload[2]; // x hi
    report[3] = p->payload[3]; // y lo
    report[4] = p->payload[4]; // y hi

    USBD_HID_ABS_MOUSE_SendReport(...);
}
```

実際の関数名は patch 側に合わせる。

#### `firmware/bluepill2/usbd_hid_composite_patch.h`

3rd interface を追加する。

追加定義例:

```
#define HID_KEYBOARD_INTERFACE        0x00U
#define HID_MOUSE_INTERFACE           0x01U
#define HID_ABS_MOUSE_INTERFACE       0x02U

#define USB_COMPOSITE_HID_CONFIG_DESC_SIZ 84U

#define HID_ABS_MOUSE_REPORT_DESC_SIZE  54U  // 実 descriptor 長に合わせる
#define HID_ABS_MOUSE_EPIN_SIZE         0x08U
```

endpoint address は既存 `HID_KEYBOARD_EPIN_ADDR`, `HID_MOUSE_EPIN_ADDR` と衝突しない値にする。

既存 framework の `usbd_ep_conf.h` に定義がなければ、patch header 内で安全に define する。

例:

```
#ifndef HID_ABS_MOUSE_EPIN_ADDR
#define HID_ABS_MOUSE_EPIN_ADDR 0x83U
#endif
```

ただし既存 endpoint address を確認し、重複しないことを必須にする。

`USBD_HID_HandleTypeDef` に absolute 用 state を追加する。

```
HID_StateTypeDef AbsMousestate;
```

send function prototype 追加:

```
uint8_t USBD_HID_ABS_MOUSE_SendReport(USBD_HandleTypeDef *pdev,
                                      uint8_t *report,
                                      uint16_t len);
```

#### `firmware/bluepill2/usbd_hid_composite_patch.c`

大きな変更対象。

##### Config descriptor

現在:

```
USB_COMPOSITE_HID_CONFIG_DESC_SIZ = 59
bNumInterfaces = 2
Keyboard interface block = 25 bytes
Mouse interface block = 25 bytes
```

変更後:

```
USB_COMPOSITE_HID_CONFIG_DESC_SIZ = 84
bNumInterfaces = 3
Keyboard interface block
Relative Mouse interface block
Absolute Mouse interface block
```

各 config descriptor array を更新する。

対象:

- `USBD_HID_CfgFSDesc`
- `USBD_HID_CfgHSDesc`
- `USBD_HID_OtherSpeedCfgDesc`

BluePill は full-speed だが、既存コードが HS / OtherSpeed も持っているため、3 つとも整合させる。

##### HID descriptor object

追加:

```
__ALIGN_BEGIN static uint8_t USBD_ABS_MOUSE_HID_Desc[USB_HID_DESC_SIZ] __ALIGN_END = {
  ...
  HID_ABS_MOUSE_REPORT_DESC_SIZE,
  0x00
};
```

##### Absolute mouse report descriptor

初期案は Generic Desktop Mouse として実装する。

Report format:

```
[buttons: 8bit][x: uint16 LE][y: uint16 LE]
```

Descriptor 方針:

```
Usage Page (Generic Desktop)
Usage (Mouse)
Collection (Application)
  Usage (Pointer)
  Collection (Physical)
    Usage Page (Button)
    Usage Minimum (1)
    Usage Maximum (3)
    Logical Minimum (0)
    Logical Maximum (1)
    Report Count (3)
    Report Size (1)
    Input (Data,Var,Abs)
    Report Count (1)
    Report Size (5)
    Input (Const,Array,Abs)
    Usage Page (Generic Desktop)
    Usage (X)
    Usage (Y)
    Logical Minimum (0)
    Logical Maximum (32767)
    Physical Minimum (0)
    Physical Maximum (32767)
    Report Size (16)
    Report Count (2)
    Input (Data,Var,Abs)
  End Collection
End Collection
```

重要:

- `Input` は X/Y で `Abs`。
- Relative mouse descriptor は既存のまま維持する。
- 既存 relative mouse に Report ID を追加しない。
- absolute mouse 用に別 interface / endpoint を使う。

##### Setup routing

現在:

```
if wIndex == HID_KEYBOARD_INTERFACE:
    keyboard setup
else:
    mouse setup
```

変更後:

```
if wIndex == HID_KEYBOARD_INTERFACE:
    keyboard setup
else if wIndex == HID_MOUSE_INTERFACE:
    mouse setup
else if wIndex == HID_ABS_MOUSE_INTERFACE:
    abs mouse setup
else:
    USBD_CtlError
```

`USBD_HID_ABS_MOUSE_Setup()` を追加し、GET_DESCRIPTOR で absolute report descriptor / HID descriptor を返す。

##### Init / DeInit

`USBD_HID_Init()`:

- absolute endpoint の interval 設定を追加。
- `USBD_LL_OpenEP()` で `HID_ABS_MOUSE_EPIN_ADDR` を open。
- `pdev->ep_in[...].is_used = 1U`
- `hhid->AbsMousestate = HID_IDLE`

`USBD_HID_DeInit()`:

- absolute endpoint close を追加。

##### SendReport

追加:

```
uint8_t USBD_HID_ABS_MOUSE_SendReport(...)
{
    if configured and AbsMousestate == HID_IDLE:
        AbsMousestate = HID_BUSY
        USBD_LL_Transmit(pdev, HID_ABS_MOUSE_EPIN_ADDR, report, len)
}
```

##### DataIn

追加:

```
if epnum == (HID_ABS_MOUSE_EPIN_ADDR & 0x7F):
    AbsMousestate = HID_IDLE;
```

##### Descriptor size checks

C 側で可能なら static assert 的に array size と macro を一致させる。

C89/C99 compatibility が不明なら、最低限コメントと `tests/test_firmware_static.py` で検証する。

#### `firmware/bluepill2/usbd_desc_patch.c`

descriptor cache 対策: **ユーザー決定により VID/PID/Product string は現行の Logitech emulation (046D:C52B) を維持**する。Phase 3 で descriptor cache と衝突した場合は `bcdDevice` のみを bump する (例: 24.00 → 24.01)。VID / PID / Product string には触らない。

Phase 3 で実施すること:

- `bcdDevice` を bump する (1 回のみ。3 interface 対応の絶対マウスビルドであることを示すバージョンアップ)。
- `USBD_VID` / `USBD_PID` / Product string は現行値を維持。

開発中に Windows descriptor cache で問題が出た場合の回避手順 (README / docs/setup.md に明記):

1. BP2 を抜く
2. デバイスマネージャ → 表示 → デバイスを表示 をオフ → 該当の「Logitech Unifying Receiver」をアンインストール (ドライバも削除)
3. BP2 を別の USB ポートに挿す

本番運用では絶対マウスビルド後も VID/PID/Product string を維持するため、ターゲット PC のドライバが再要求されることはない。

### 4.4 Docs

#### `docs/protocol.md`

追加:

- `PKT_MOUSE_ABS = 0x03`
- payload layout
- coordinate range
- endian
- backward compatibility
- old firmware では送らないこと
- `PKT_MOUSE` と `PKT_MOUSE_ABS` の使い分け

現行 docs の再同期ルールには「受信中に `0xAA` が現れた場合は再同期」とあるが、実装では `PS_PAYLOAD` 中は 0xAA で再同期しない。この既存不整合も修正する。

正しくは:

```
PS_TYPE / PS_LEN 中の 0xAA は新 packet start として再同期する。
PS_PAYLOAD 中の 0xAA は payload byte として扱う。
checksum mismatch または 50 ms timeout で復帰する。
```

#### `README.md`

追加:

- Mouse modes

- Relative
- Hybrid
- Absolute
- Absolute HID firmware requirement
- SteamVR Desktop dashboard では改善を狙えるが、OVR Advanced Settings dashboard overlay 完全対応は保証しないこと
- 初期制限

- single monitor
- primary display
- DPI 100%
- firmware flashing 後に Windows descriptor cache で問題が出る場合の対策

- device uninstall
- USB port change
- bcdDevice / PID change

#### `docs/setup.md`

追加:

- Phase 3 firmware を BP2 に書き込んだ後、Settings で `Firmware supports absolute HID` を有効化する手順。
- Windows Device Manager / USBView 等で Keyboard + Relative Mouse + Absolute Mouse が見えることを確認する手順。

## 5. Phase-by-phase implementation plan

## Phase 1: Host-side only provisional support

### 5.1 Purpose

ファームウェア変更なしで、座標変換・UI・mode 設計を先に導入する。
この Phase では absolute HID packet はデフォルトでは送らない。

目的:

- 座標変換ロジックを TDD で固める。
- mouse mode 設定を入れる。
- `hybrid` / `absolute` の host 側分岐を準備する。
- 旧 firmware で既存 relative mode が壊れないことを保証する。
- optional fallback として relative jump 連射を評価できるようにする。

### 5.2 Files to modify

- `app/core/coordinates.py` 新規
- `app/core/mouse_modes.py` 新規
- `app/ui/mainwindow.py`
- `app/ui/settings_dialog.py`
- `README.md`
- `tests/test_coordinates.py` 新規
- `tests/test_mouse_modes.py` 新規
- `tests/test_settings_values.py` 新規

### 5.3 Implementation steps

#### Step 1: Add coordinate mapping pure module

Create `app/core/coordinates.py`.

実装する関数:

- `compute_video_mapping(source_size, widget_size, aspect_mode)`
- `map_widget_point_to_source(...)`
- `map_widget_point_to_hid(...)`

`aspect_mode` は `"keep"` / `"fill"` の文字列でよい。

この段階では Qt 依存を入れない。

#### Step 2: Add tests for coordinate mapping

Create `tests/test_coordinates.py`.

必須 test cases:

1. `1920x1080 source`, `1920x1080 widget`, keep

- `(0,0) -> hid(0,0)`
- `(960,540) -> around (16384,16384)`
- `(1919,1079) -> (32767,32767)`
2. `1920x1080 source`, `1280x720 widget`, keep

- aspect 一致なので黒帯なし。
- center mapping が正しい。
3. `1920x1080 source`, `1000x1000 widget`, keep

- displayed rect は `1000x562.5` 相当。
- top/bottom は letterbox。
- 黒帯上部クリックは `source_y=0` に clamp。
- 黒帯下部クリックは `source_y=1079` に clamp。
4. `1920x1080 source`, `1000x1000 widget`, fill

- widget 全域を source に線形 mapping。
- 黒帯なし。
5. DPR 二重適用禁止

- 関数入力は logical pixel 前提。
- DPR を引数に取らない、または取っても使わない設計にする。

#### Step 3: Add mouse mode pure module

Create `app/core/mouse_modes.py`.

実装するもの:

- `MouseMode`
- `MouseModeConfig`
- `normalize_mouse_mode()`
- `can_send_absolute()`
- `should_warp_cursor()`
- `should_hide_host_cursor()`

#### Step 4: Add tests for mode behavior

Create `tests/test_mouse_modes.py`.

必須 test cases:

- invalid setting value は `relative` に fallback。
- `relative` は warp true / hide cursor true / can_send_absolute false。
- `hybrid` + firmware_abs false は can_send_absolute false。
- `hybrid` + firmware_abs true は can_send_absolute true。
- `absolute` + firmware_abs true は warp false / hide cursor false。
- `absolute` + firmware_abs false は can_send_absolute false。

#### Step 5: Extend settings dialog

`app/ui/settings_dialog.py` を修正。

追加 UI:

- Mouse Mode combo
- Firmware supports absolute HID checkbox

`get_values()` の返却値を拡張する。

推奨は dataclass 化だが、既存変更を小さくするなら tuple 拡張でよい。

#### Step 6: Extend MainWindow settings

`app/ui/mainwindow.py` に以下を追加。

保存 key:

```
input/mouse_mode
input/firmware_abs_supported
input/fallback_relative_jump
```

default:

```
input/mouse_mode = "relative"
input/firmware_abs_supported = false
input/fallback_relative_jump = false
```

`_save_settings()` / `_load_settings()` / `_open_settings()` を更新。

#### Step 7: Preserve relative behavior

`relative` mode では既存挙動を完全維持する。

- cursor hide
- center warp
- `warp_pending`
- `mouse_speed`
- `build_mouse_report`

この時点の regression test は GUI 自動化ではなく、manual smoke でよい。

#### Step 8: Prepare hybrid activation position storage

`mousePressEvent()` の inactive branch で、KVM 開始クリック位置を保存する。

```
self._pending_kvm_activation_global_pos = event.globalPosition().toPoint()
self._pending_kvm_activation_local_pos = self._video_widget.mapFromGlobal(...)
```

timer callback `_activate_kvm_from_click()` で利用する。

Phase 1 では `firmware_abs_supported=false` なので absolute packet は送らない。

#### Step 9: Optional relative-jump fallback

ファームウェア未対応でも暫定的に cursor jump したい場合の fallback。

ただし default false。

方式:

1. 目的地 source coordinate と target cursor current coordinate の差分が分からないため、厳密 jump はできない。
2. したがって fallback は「画面左上へ十分大きく relative 移動してから、目的地まで relative 移動する」という粗い方式になる。
3. これは OS pointer acceleration の影響を受け、時間もかかる。
4. 操作感が悪い可能性が高いため、実験機能扱い。

結論:

- Phase 1 で実装してもよいが、default off。
- Codex には「可能なら実装、ただし本命ではない」と指示する。
- まずは座標変換と UI のみで止めてもよい。

### 5.4 Phase 1 risks

| Risk | Detail | Mitigation |
| --- | --- | --- |
| Relative mode regression | `mainwindow.py` の分岐追加で既存操作が壊れる | `relative` path を最小変更にする |
| Settings tuple breakage | `get_values()` の戻り値変更で呼び出し側が壊れる | dataclass 化または全 call site 同時更新 |
| DPR 誤適用 | HiDPI で座標がずれる | pure test で DPR を使わない方針を固定 |
| Fallback relative jump の操作感 | acceleration により不正確 | default off / experimental |
| Absolute mode 選択時の旧 firmware | unknown packet を送ると BP2 error | firmware_abs_supported false では送らない |

### 5.5 Phase 1 test strategy

Unit tests:

```
python -m pytest tests/test_coordinates.py -q
python -m pytest tests/test_mouse_modes.py -q
python -m pytest tests/test_settings_values.py -q
python -m pytest -q
```

Manual smoke:

- app 起動。
- Settings が開く。
- Mouse Mode が保存・復元される。
- Relative mode で既存 KVM 操作が壊れない。
- Fullscreen enter/exit が壊れない。
- Esc で KVM release できる。

## Phase 2: Protocol extension

### 6.1 Purpose

Host / firmware common に `PKT_MOUSE_ABS` を定義し、packet encode / parse / docs を揃える。
この Phase では BP2 が absolute HID をまだ送れなくてもよい。

### 6.2 Files to modify

- `app/core/protocol.py`
- `firmware/common/packet_parser.h`
- `docs/protocol.md`
- `README.md`
- `tests/test_protocol.py` 新規
- `tests/test_docs_protocol_sync.py` 新規

### 6.3 Implementation steps

#### Step 1: Add `PKT_MOUSE_ABS` to Python protocol

`app/core/protocol.py`:

```
PKT_MOUSE_ABS = 0x03
HID_ABS_MAX = 32767
```

Add:

```
def build_mouse_abs_report(buttons: int, x: int, y: int) -> bytes:
    x = max(0, min(HID_ABS_MAX, x))
    y = max(0, min(HID_ABS_MAX, y))
    payload = bytes([
        buttons & 0x07,
        x & 0xFF,
        (x >> 8) & 0xFF,
        y & 0xFF,
        (y >> 8) & 0xFF,
    ])
    return _build_packet(PKT_MOUSE_ABS, payload)
```

#### Step 2: Add protocol tests

`tests/test_protocol.py`.

Test cases:

- `build_mouse_abs_report(0, 0, 0)` packet structure。
- `build_mouse_abs_report(1, 32767, 32767)` payload endian。
- x/y negative clamp to 0。
- x/y > 32767 clamp to 32767。
- buttons mask to 0x07。
- CRC known value。
- existing `build_mouse_report()` regression:

- dx/dy clamp remains ±127。
- packet type remains 0x02。
- length remains 5。

#### Step 3: Add firmware constants

`firmware/common/packet_parser.h`:

```
#define PKT_MOUSE_ABS 0x03u
#define PKT_LEN_MOUSE_ABS 5u
```

No parser logic change.

#### Step 4: Update docs

`docs/protocol.md`:

Add type table row:

```
0x03 PKT_MOUSE_ABS LEN=5 HID absolute mouse report
```

Add section:

```
## 絶対マウスペイロード（LEN = 5）

Byte 0: buttons
Byte 1: x low
Byte 2: x high
Byte 3: y low
Byte 4: y high

x/y: uint16 little-endian, 0..32767
```

Clarify:

- `PKT_MOUSE` は relative。
- `PKT_MOUSE_ABS` は absolute。
- `PKT_MOUSE_ABS` は Phase 3 firmware でのみ使用。
- 旧 firmware へ送ってはいけない。

Also fix existing resync description to match parser implementation.

#### Step 5: Wire Host absolute packet send

`mainwindow.py` に Phase 1 で準備した mode 分岐へ `build_mouse_abs_report()` を接続する。

`hybrid`:

```
activation click local pos
  -> map_widget_point_to_hid
  -> build_mouse_abs_report(current buttons, hid_x, hid_y)
  -> enqueue
  -> then relative warp
```

`absolute`:

```
mouseMoveEvent:
  if KVM active and can_send_absolute:
      local pos -> hid
      if changed:
          enqueue abs packet
```

`mousePressEvent` / `mouseReleaseEvent`:

```
update button state
send abs packet at current local position
```

If `firmware_abs_supported` false:

- do not send absolute packet.
- status bar warning:

- `Absolute HID firmware not enabled; falling back to relative input`
- mode behavior:

- `hybrid` behaves as `relative`
- `absolute` should either refuse activation or behave as `relative`
- 推奨は `absolute` activation 時に relative fallback して warning を出す。

### 6.4 Phase 2 risks

| Risk | Detail | Mitigation |
| --- | --- | --- |
| Old firmware receives unknown packet | BP2 error blink | `firmware_abs_supported` gate |
| Protocol docs drift | docs と code が不一致 | docs sync test |
| CRC mismatch | host と firmware CRC の差 | known value tests |
| Queue overflow | absolute move packets が多い | duplicate suppression |

### 6.5 Phase 2 test strategy

Unit tests:

```
python -m pytest tests/test_protocol.py -q
python -m pytest tests/test_coordinates.py -q
python -m pytest tests/test_mouse_modes.py -q
python -m pytest tests/test_docs_protocol_sync.py -q
python -m pytest -q
```

Manual with old firmware:

- `firmware_abs_supported=false`
- Relative mode works.
- Hybrid mode does not send unknown packet.
- Absolute mode warns / falls back.
- BP2 error blink does not occur.

## Phase 3: Firmware extension

### 7.1 Purpose

BluePill #2 をターゲット PC から以下の composite HID として見せる。

```
Interface 0: Boot Keyboard
Interface 1: Relative Mouse
Interface 2: Absolute Mouse / Absolute Pointer
```

Host から `PKT_MOUSE_ABS` を受け取り、absolute mouse endpoint へ 5-byte HID report を送る。

### 7.2 Files to modify

- `firmware/common/packet_parser.h`
- `firmware/bluepill2/hid_handler.h`
- `firmware/bluepill2/hid_handler.cpp`
- `firmware/bluepill2/main.cpp`
- `firmware/bluepill2/usbd_hid_composite_patch.h`
- `firmware/bluepill2/usbd_hid_composite_patch.c`
- `firmware/bluepill2/usbd_desc_patch.c`
- `platformio.ini`
- `docs/setup.md`
- `README.md`
- `tests/test_firmware_static.py` 新規

### 7.3 Implementation steps

#### Step 1: Add absolute report struct and validation

`hid_handler.h`:

```
typedef struct __attribute__((packed)) {
    uint8_t buttons;
    uint16_t x;
    uint16_t y;
} KVMMouseAbsReport;

bool validate_mouse_abs_report(const uint8_t *payload, uint8_t len);
```

`hid_handler.cpp`:

- len check
- button mask check
- x/y max check

#### Step 2: Add BP2 packet handling

`main.cpp`:

- `hid_send_mouse_abs()`
- switch case:

```
case PKT_MOUSE_ABS:
    hid_send_mouse_abs(&g_pkt);
    break;
```

Report format to USB:

```
report[0] = buttons
report[1] = x_lo
report[2] = x_hi
report[3] = y_lo
report[4] = y_hi
```

#### Step 3: Extend HID handle state

`usbd_hid_composite_patch.h`:

```
typedef struct {
  uint32_t Protocol;
  uint32_t IdleState;
  uint32_t AltSetting;
  HID_StateTypeDef Mousestate;
  HID_StateTypeDef Keyboardstate;
  HID_StateTypeDef AbsMousestate;
} USBD_HID_HandleTypeDef;
```

#### Step 4: Define 3rd interface and endpoint

Add macros:

```
#define HID_ABS_MOUSE_INTERFACE 0x02U
#define HID_ABS_MOUSE_EPIN_SIZE 0x08U
#define HID_ABS_MOUSE_REPORT_DESC_SIZE <actual>
#ifndef HID_ABS_MOUSE_EPIN_ADDR
#define HID_ABS_MOUSE_EPIN_ADDR 0x83U
#endif
```

Endpoint address must not collide with existing keyboard/mouse endpoints.

Codex must inspect included `usbd_ep_conf.h` definitions during implementation. If existing endpoint addresses already use `0x81` and `0x82`, use `0x83`. If not, choose a free interrupt IN endpoint.

#### Step 5: Update config descriptors

`USB_COMPOSITE_HID_CONFIG_DESC_SIZ`:

```
59 -> 84
```

`bNumInterfaces`:

```
0x02 -> 0x03
```

Append absolute mouse block to each descriptor:

- FS
- HS
- OtherSpeed

Each block:

```
Interface descriptor: 9 bytes
HID descriptor: 9 bytes
Endpoint descriptor: 7 bytes
Total: 25 bytes
```

#### Step 6: Add absolute HID descriptor

Add:

```
USBD_ABS_MOUSE_HID_Desc
HID_ABS_MOUSE_ReportDesc
```

Report descriptor must match 5-byte report:

```
buttons: 3 bits + 5 bits padding
x: 16 bits absolute
y: 16 bits absolute
```

Use `Logical Maximum 32767`.

#### Step 7: Add setup handler

Add function:

```
static uint8_t USBD_HID_ABS_MOUSE_Setup(USBD_HandleTypeDef *pdev,
                                        USBD_SetupReqTypedef *req);
```

In `USBD_COMPOSITE_HID_Setup()`:

```
uint8_t iface = req->wIndex & 0x00FF;

if (iface == HID_KEYBOARD_INTERFACE) ...
else if (iface == HID_MOUSE_INTERFACE) ...
else if (iface == HID_ABS_MOUSE_INTERFACE) ...
else error
```

The absolute setup handler mirrors mouse setup but returns absolute descriptors.

#### Step 8: Open / close absolute endpoint

`USBD_HID_Init()`:

- set interval for absolute endpoint
- open endpoint
- mark `is_used`
- set `AbsMousestate = HID_IDLE`

`USBD_HID_DeInit()`:

- close absolute endpoint
- mark unused if existing code does so

#### Step 9: Add send function

Add:

```
uint8_t USBD_HID_ABS_MOUSE_SendReport(USBD_HandleTypeDef *pdev,
                                      uint8_t *report,
                                      uint16_t len)
```

Use `AbsMousestate`, `HID_ABS_MOUSE_EPIN_ADDR`.

#### Step 10: DataIn busy release

`USBD_HID_DataIn()`:

```
if epnum == keyboard:
    Keyboardstate = HID_IDLE
else if epnum == relative mouse:
    Mousestate = HID_IDLE
else if epnum == absolute mouse:
    AbsMousestate = HID_IDLE
```

#### Step 11: Descriptor cache strategy

Update `usbd_desc_patch.c`.

Minimum:

- increment `bcdDevice`.

Recommended during development:

- change Product string to indicate absolute variant, unless Logitech emulation must be preserved.

Also document Windows cleanup steps:

- unplug BP2
- Device Manager hidden devices uninstall
- plug into different USB port
- or change PID / bcdDevice

#### Step 12: PlatformIO build

Ensure `pio run -e bluepill2` passes.

No new library dependency should be added.

### 7.4 Phase 3 risks

| Risk | Detail | Mitigation |
| --- | --- | --- |
| USB enumeration failure | Config descriptor length / bNumInterfaces mismatch | static tests + USBView |
| Endpoint collision | Existing endpoint addr already used | inspect `usbd_ep_conf.h`; static test uniqueness |
| Busy state stuck | DataIn does not clear AbsMousestate | DataIn branch test / manual |
| Windows descriptor cache | Old descriptor cached for same VID/PID | bcdDevice/PID/Product change |
| Report descriptor mismatch | Host expects different report length | descriptor length static test |
| Existing relative mouse breaks | Shared interface modified accidentally | keep relative interface untouched |
| OVRAS not improved | OpenVR overlay event path | document limitation |
| Multi-monitor mismatch | Windows absolute mapping uses virtual desktop / primary | initial single-monitor scope |

### 7.5 Phase 3 test strategy

#### Static tests

Create `tests/test_firmware_static.py`.

Test by reading firmware files as text.

Check:

- `PKT_MOUSE_ABS` exists in `packet_parser.h`
- `PKT_LEN_MOUSE_ABS` exists
- `KVMMouseAbsReport` exists
- `validate_mouse_abs_report` exists
- `case PKT_MOUSE_ABS` exists in `bluepill2/main.cpp`
- `HID_ABS_MOUSE_INTERFACE` exists
- `HID_ABS_MOUSE_EPIN_ADDR` exists
- `HID_ABS_MOUSE_ReportDesc` exists
- `USBD_HID_ABS_MOUSE_SendReport` exists
- `AbsMousestate` exists
- `bNumInterfaces` is 3
- config descriptor size is 84
- setup routing includes absolute interface
- DataIn clears AbsMousestate

#### Build tests

Local:

```
pio run -e bluepill1
pio run -e bluepill2
```

CI optional:

```
- run: python -m pytest -q
- run: pio run -e bluepill1
- run: pio run -e bluepill2
```

If CI does not have PlatformIO, document local firmware build as required.

#### USB enumeration tests

On Windows target PC:

1. Flash BP2 Phase 3 firmware.
2. Plug BP2 into target PC.
3. Confirm enumeration:

- one keyboard interface
- one relative mouse interface
- one absolute mouse / HID-compliant mouse interface
4. Use Device Manager / USBView / UsbTreeView to inspect:

- bNumInterfaces = 3
- endpoint count
- report descriptor for absolute interface
5. If old descriptor appears:

- change USB port
- uninstall hidden device
- bump bcdDevice / PID

#### Functional HID tests

With a small host test command or temporary debug UI:

- Send absolute `(0,0)`:

- cursor moves to top-left.
- Send absolute `(32767,0)`:

- cursor moves to top-right.
- Send absolute `(0,32767)`:

- cursor moves to bottom-left.
- Send absolute `(32767,32767)`:

- cursor moves to bottom-right.
- Send absolute center:

- cursor moves to screen center.
- Send button down/up at center:

- click occurs at center.

#### App integration tests

Target condition:

```
single monitor
primary display
DPI 100%
capture resolution == desktop resolution
```

Test:

- Relative mode:

- existing operation unchanged.
- Hybrid mode:

- click VideoWidget at visible target button.
- KVM starts.
- target cursor jumps to corresponding desktop coordinate.
- relative movement continues normally.
- Absolute mode:

- host cursor moves inside VideoWidget.
- target cursor follows.
- click on desktop icon / button works.
- wheel scroll works via relative wheel packet.
- Fullscreen:

- same tests in fullscreen.
- KeepAspectRatio:

- black bar click clamps to video edge.
- StretchToFill:

- full widget maps linearly.

#### SteamVR validation

Not required for base Done criteria, but useful.

Conditions:

- single monitor
- primary display
- DPI 100%
- SteamVR Desktop dashboard

Tests:

- Relative mode baseline:

- record cursor alignment difficulty.
- Absolute mode:

- verify desktop cursor follows VideoWidget coordinate.
- verify UI click target improves.
- Hybrid mode:

- verify initial cursor position is corrected.
- OVR Advanced Settings:

- experimental only.
- document whether absolute HID affects interaction.
- do not block release on failure.

## 8. TDD plan

### 8.1 Red-Green-Refactor order

#### TDD Batch 1: Coordinates

1. Write failing `tests/test_coordinates.py`.
2. Implement `app/core/coordinates.py`.
3. Refactor until no Qt dependency remains.

#### TDD Batch 2: Protocol

1. Write failing `tests/test_protocol.py`.
2. Add `PKT_MOUSE_ABS` and builder.
3. Verify old packet tests still pass.

#### TDD Batch 3: Mouse modes

1. Write failing `tests/test_mouse_modes.py`.
2. Implement `app/core/mouse_modes.py`.
3. Wire mode decisions into `mainwindow.py`.

#### TDD Batch 4: Settings

1. Write failing `tests/test_settings_values.py`.
2. Update SettingsDialog and MainWindow settings save/load.
3. Verify invalid setting fallback.

#### TDD Batch 5: Firmware static

1. Write failing `tests/test_firmware_static.py`.
2. Add firmware constants / structs / routing / descriptor symbols.
3. Build with PlatformIO.

#### TDD Batch 6: Docs sync

1. Write failing `tests/test_docs_protocol_sync.py`.
2. Update docs.
3. Ensure protocol docs mention limitations and packet layout.

### 8.2 Tests to add

```
tests/test_protocol.py
tests/test_coordinates.py
tests/test_mouse_modes.py
tests/test_settings_values.py
tests/test_firmware_static.py
tests/test_docs_protocol_sync.py
```

### 8.3 CI update

Current project has pytest dependency in `pyproject.toml`. Add pytest execution to CI or local `test_ci.ps1`.

Minimum:

```
python -m pytest -q
```

Optional firmware build:

```
pio run -e bluepill1
pio run -e bluepill2
```

## 9. Detailed acceptance criteria

### 9.1 Phase 1 done criteria

- `app/core/coordinates.py` exists and has unit tests.
- `app/core/mouse_modes.py` exists and has unit tests.
- Settings UI includes Mouse Mode and Firmware supports absolute HID.
- Settings persist and restore.
- Relative mode behaves exactly as before.
- Absolute packet is not sent unless firmware support is enabled.
- KVM focus / Esc release / fullscreen behavior still works.

### 9.2 Phase 2 done criteria

- `PKT_MOUSE_ABS = 0x03` exists in Python and firmware constants.
- `build_mouse_abs_report()` emits correct packet and CRC.
- `docs/protocol.md` documents absolute packet.
- Host can generate absolute packets but gates them behind firmware support setting.
- Old firmware does not receive unknown absolute packets by default.
- All pytest tests pass.

### 9.3 Phase 3 done criteria

- BP2 firmware builds.
- USB descriptor enumerates as 3-interface HID composite.
- Keyboard interface still works.
- Relative mouse interface still works.
- Absolute mouse interface accepts 5-byte reports.
- Windows cursor moves to top-left / center / bottom-right via absolute reports.
- Hybrid mode corrects cursor initial position on KVM activation.
- Absolute mode tracks VideoWidget cursor position on target desktop.
- README and setup docs describe firmware requirement and known limitations.

## 10. Risk register

### 10.1 High risks

#### USB descriptor enumeration failure

Cause:

- `wTotalLength` mismatch
- `bNumInterfaces` mismatch
- report descriptor length mismatch
- endpoint address collision

Mitigation:

- static tests
- PlatformIO build
- USBView / UsbTreeView inspection
- increment bcdDevice / PID during development

#### Existing relative mouse regression

Cause:

- changing existing relative mouse interface
- adding Report ID to existing interface
- modifying report length

Mitigation:

- do not add Report ID to existing relative interface
- use separate absolute interface
- keep `PKT_MOUSE` and `HID_MOUSE_ReportDesc` unchanged unless necessary

#### Windows absolute mapping mismatch

Cause:

- multi-monitor
- DPI scaling
- non-primary display
- virtual desktop mapping

Mitigation:

- initial scope single monitor / DPI 100%
- document limitation
- later add calibration:

- target monitor origin
- virtual desktop width/height
- per-monitor offset

#### OVR Advanced Settings not fixed

Cause:

- OVRAS dashboard overlay uses OpenVR overlay mouse events, not direct Windows HID cursor.

Mitigation:

- do not call feature "OVR mode"
- document limitation
- treat OVRAS as experimental validation
- if required later, design separate target-side OpenVR helper

### 10.2 Medium risks

#### Serial queue overflow

Cause:

- absolute mode sends many mouse move packets.

Mitigation:

- suppress duplicate absolute packets
- optionally throttle to 125 Hz or lower
- optionally increase queue size

#### Host cursor UX in absolute mode

Cause:

- if cursor hidden, user loses local position reference.
- if cursor visible, KVM focus feels different.

Mitigation:

- absolute mode does not hide cursor by default.
- relative / hybrid retain hidden cursor.

#### Fullscreen interactions

Cause:

- fullscreen transition currently recomputes center and restores KVM state.

Mitigation:

- only call center/warp logic for relative/hybrid.
- absolute mode only updates mapping based on current widget size.

### 10.3 Low risks

#### Mouse speed confusion

Cause:

- speed applies to relative dx/dy, but not absolute coordinate.

Mitigation:

- Settings label / tooltip:

- "Mouse Speed applies to Relative and Hybrid movement only."

#### Horizontal wheel

Existing docs say horizontal wheel may be unsupported. Absolute work does not need to solve this.

## 11. Future work

### 11.1 Capability handshake

Add protocol packet:

```
PKT_CAPS_REQUEST
PKT_CAPS_RESPONSE
```

Could report:

- protocol version
- absolute HID support
- firmware build date
- descriptor variant

Not needed for initial implementation.

### 11.2 Calibration

Add per-target calibration:

```
capture_width
capture_height
target_virtual_desktop_width
target_virtual_desktop_height
target_monitor_origin_x
target_monitor_origin_y
target_monitor_width
target_monitor_height
```

This is required for robust multi-monitor / mixed DPI support.

### 11.3 Digitizer variant

If Generic Desktop absolute mouse does not move Windows cursor as desired, try a separate firmware descriptor variant:

- Digitizer Tablet
- Touchscreen
- Pen

This should be a separate experimental branch, not the first implementation.

### 11.4 Target-side helper

For OVR Advanced Settings / OpenVR dashboard overlay complete support, consider a target-side helper that can interact with OpenVR overlay event APIs or virtual controller input. This is outside the current BP2 HID-only architecture.

## 12. Codex implementation order

Codex should implement in this exact order.

1. Add `tests/test_coordinates.py`.
2. Add `app/core/coordinates.py`.
3. Add `tests/test_protocol.py`.
4. Add `PKT_MOUSE_ABS` and `build_mouse_abs_report()` to `app/core/protocol.py`.
5. Add `tests/test_mouse_modes.py`.
6. Add `app/core/mouse_modes.py`.
7. Add settings tests.
8. Update `settings_dialog.py`.
9. Update `mainwindow.py` with mouse mode branches, keeping relative path as unchanged as possible.
10. Update `docs/protocol.md` and README for Phase 1/2.
11. Run pytest.
12. Add firmware static tests.
13. Add `PKT_MOUSE_ABS` firmware constants.
14. Add `KVMMouseAbsReport` and validation.
15. Add BP2 packet handling.
16. Extend HID composite patch to 3 interfaces.
17. Update descriptor cache strategy.
18. Build `pio run -e bluepill2`.
19. Update docs/setup.
20. Perform manual USB enumeration and cursor movement tests.

## 13. ユーザー決定事項 (2026-06-24)

実装前に確認した事項と決定。

1. **BluePill #2 の VID/PID/Product string**

   - 決定: 現行の Logitech emulation (046D:C52B) を維持する。**変更しない**。
   - 理由: ターゲット PC 側でのドライバ互換性を保つため。
   - 対策: descriptor cache 問題時は `bcdDevice` のみ bump し、VID/PID/Product string は触らない。
   - 影響範囲: Phase 3 で `usbd_desc_patch.c` を編集する際は `bcdDevice` インクリメントのみ。`USBD_VID` / `USBD_PID` / Product string は現行値を維持。
2. **初期対応の target 環境**

   - 決定: single monitor / primary display / DPI 100% / capture 解像度 = desktop 解像度 に限定。
   - 理由: multi-monitor / mixed DPI / non-primary capture は Windows absolute coordinate mapping が別問題になるため、初期スコープでは扱わない。
3. **`Absolute` mode で host cursor を表示するか**

   - 決定: 表示する (hide しない)。
   - 理由: host cursor 位置そのものが target cursor の absolute 入力になるため、hide すると入力源を見失う。
4. **OVR Advanced Settings (OVRAS) の Done criteria 範囲**

   - 決定: **OVRAS の VR 内ダッシュボードオーバーレイ完全対応は Done criteria から除外**。
   - 含める: ターゲット Windows デスクトップ上の absolute カーソル位置同期 (HID 絶対マウスで解決可能)。
   - 含める: SteamVR Desktop dashboard (VR 内に Windows desktop を映す機能) での absolute カーソル追従。Windows カーソル位置を見るので改善する。
   - 除外する: OVRAS の VR 内ダッシュボードオーバーレイ。これは OpenVR overlay event 経路でレンダリング・マウス入力されており、HID 絶対マウスだけでは完全解決しない可能性がある。
   - 実装後の位置づけ: リリース後に OVRAS で改善が見られたらラッキー、されなくてもリリースはブロックしない。
   - 理由: OVRAS の VR 内オーバーレイ完全対応には OpenVR overlay event injection が必要な可能性があり、現在の BluePill 2 個 + シリアルというアーキテクチャの範囲を超えるため。

## 14. Final recommendation

この実装は進めてよい。
ただし、目的を 「OVR 完全対応」ではなく「captured desktop coordinate と target Windows cursor の absolute alignment」 と定義すること。

OVRAS (OVR Advanced Settings) の VR 内ダッシュボードオーバーレイ完全対応は今回の Done criteria から除外する (ユーザー決定 2026-06-24、§13.4 参照)。VR 内ダッシュボードオーバーレイは OpenVR overlay event 経路でレンダリング・マウス入力されており、HID 絶対マウスだけでは完全解決しない可能性がある。SteamVR Desktop dashboard (VR 内に Windows desktop を映す機能) での absolute カーソル追従は Done criteria に含める (Windows カーソル位置を見るので改善する)。

最初に完成させるべき実用機能は `Hybrid` mode。

```
KVM 開始時に VideoWidget 上のクリック位置へ target cursor を absolute jump
その後は既存 relative mouse 操作
```

これにより、最も不快な「KVM 開始時のカーソル位置ズレ」を最小リスクで解消できる。

次に `Absolute` mode を完成させる。

```
VideoWidget 内の host cursor 位置を target cursor absolute position として同期
```

これにより、Windows desktop / SteamVR Desktop dashboard の操作性改善を狙う。

ファームウェアは既存 relative mouse を壊さないため、3rd HID interface 追加方式を採用する。既存 relative mouse interface に Report ID を混ぜる方式は採用しない。
