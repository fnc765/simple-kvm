# シリアルプロトコル仕様書

## 概要

ホストPC ↔ BluePill #1（USB CDC）、BluePill #1 ↔ BluePill #2（UART）で**同一プロトコル**を使用します。
BluePill #1 はパケットの検証後、そのまま UART へ転送します。

---

## パケットフォーマット

```
 Offset  Size  Field     Description
 ------  ----  --------  --------------------------------------------------
    0      1   START     固定値 0xAA（同期マーカー）
    1      1   TYPE      パケット種別（下記参照）
    2      1   LEN       ペイロードのバイト数
    3..    LEN PAYLOAD   種別ごとのデータ
  3+LEN    1   CRC-8     CRC-8-CCITT (polynomial 0x07, init 0x00)
                         計算範囲: TYPE + LEN + PAYLOAD
```

エスケープ処理は不要です。CRC-8 不一致のパケットはサイレントに廃棄されます。

---

## TYPE 定義

| 値     | 名称                | LEN | 説明                        |
|--------|---------------------|-----|-----------------------------|
| `0x01` | `PKT_KEYBOARD`      | 8   | HID Boot Keyboard Report    |
| `0x02` | `PKT_MOUSE`         | 5   | HID Mouse Report（相対座標）|
| `0x03` | `PKT_MOUSE_ABS`     | 5   | HID Absolute Mouse Report（絶対座標、Phase 3 firmware 必須）|
| `0xFF` | `PKT_HEARTBEAT`     | 0   | 死活監視（ペイロードなし）  |

---

## キーボードペイロード（LEN = 8）

HID Boot Keyboard Report と同じレイアウトです。

| Byte | フィールド  | 説明                                                   |
|------|-------------|--------------------------------------------------------|
| 0    | `modifier`  | 修飾キービットマスク（下記参照）                       |
| 1    | `reserved`  | 常に `0x00`                                            |
| 2–7  | `keys[0..5]`| 同時押しキーの HID Usage ID（空スロット = `0x00`）     |

### MODIFIER ビット定義

| Bit | キー        |
|-----|-------------|
| 0   | Left Ctrl   |
| 1   | Left Shift  |
| 2   | Left Alt    |
| 3   | Left GUI    |
| 4   | Right Ctrl  |
| 5   | Right Shift |
| 6   | Right Alt   |
| 7   | Right GUI   |

---

## マウスペイロード（LEN = 5）

| Byte | フィールド  | 説明                                             |
|------|-------------|--------------------------------------------------|
| 0    | `buttons`   | bit0=左ボタン, bit1=右, bit2=中（押下中=1）      |
| 1    | `dx`        | 相対 X 移動量 int8（-127..+127）                 |
| 2    | `dy`        | 相対 Y 移動量 int8（-127..+127）                 |
| 3    | `wheel_v`   | 垂直スクロール int8（上=+1, 下=-1）              |
| 4    | `wheel_h`   | 水平スクロール int8。STM32duino 内蔵 HID Composite は水平スクロール非対応のため、BP2 では破棄されます |

`PKT_MOUSE` は **Phase 1〜2 までの既存ファームウェアで動作**します。

---

## 絶対マウスペイロード（LEN = 5、TYPE = 0x03）

`PKT_MOUSE_ABS` は HID 絶対座標マウス用の 5 バイトペイロードで、ターゲット PC
の Windows カーソルを simple-kvm の VideoWidget 上の座標に直接対応付けます。

| Byte | フィールド  | 説明                                              |
|------|-------------|---------------------------------------------------|
| 0    | `buttons`   | bit0=左ボタン, bit1=右, bit2=中（押下中=1）       |
| 1    | `x_lo`      | 絶対 X 座標 (uint16 little-endian) 下位バイト    |
| 2    | `x_hi`      | 絶対 X 座標 上位バイト                            |
| 3    | `y_lo`      | 絶対 Y 座標 下位バイト                            |
| 4    | `y_hi`      | 絶対 Y 座標 上位バイト                            |

座標範囲:

- `x`, `y`: **0..32767** の uint16 little-endian
- 範囲外の値は `0` / `32767` にクランプされます
- ボタンは `PKT_MOUSE` と同じ `0x07` マスク

### ファームウェア要件

`PKT_MOUSE_ABS` を使うには **Phase 3 firmware**（3-interface HID composite
firmware：Keyboard / Relative Mouse / Absolute Mouse）が必要です。
現行 (Phase 1〜2) の BP2 firmware はこのパケットタイプを未知として破棄し、
エラーブリンクを起こす可能性があります。

**旧ファームウェアが書き込まれた BP2 には絶対に `PKT_MOUSE_ABS` を送らないでください。**
ホスト側 Settings の **「Firmware supports absolute HID」** がオンの時だけ送信されます
（オフのときは自動的に `relative` モードにフォールバックします）。

### SteamVR / OVR 対応について

- ✅ **SteamVR Desktop dashboard**（VR 内に Windows desktop を映す機能）：
  `PKT_MOUSE_ABS` によって Windows カーソル位置が VideoWidget に同期されるため、
  ダッシュボード上の UI 要素へのクリック精度が向上します。
- ❌ **OVR Advanced Settings (OVRAS) の VR 内ダッシュボードオーバーレイ**：
  これは OpenVR overlay event 経路でレンダリング・マウス入力されており、
  HID 絶対マウスだけでは完全対応しません（OpenVR overlay event injection が
  必要になる可能性があり、本プロジェクトの範囲外）。

---

## CRC-8-CCITT 計算

CRC-8-CCITT はテーブルルックアップ方式で計算します（多項式 0x07、初期値 0x00）。
計算範囲は TYPE + LEN + PAYLOAD です。

```
例: 'A' キー押下（Shift なし）
  packet: AA  01  08  00 00 04 00 00 00 00 00  CR
          ST  TY  LN  [---- 8 bytes payload ----]

  CRC-8 計算対象: 01 08 00 00 04 00 00 00 00 00
  CRC-8 結果    : 0x38
```

CRC-8 テーブル（256 エントリ）をあらかじめ計算し、1 バイトずつ `crc = table[crc ^ byte]` で更新します。

---

## 再同期ルール

1. LEN > 16 のパケットは即座に廃棄
2. パケット受信中に 50 ms のタイムアウトが発生したらステートをリセット
3. 受信中に `0xAA` が現れた場合は新たなパケットの開始として再同期
