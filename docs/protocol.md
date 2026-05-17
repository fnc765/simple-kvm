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

| 値     | 名称            | LEN | 説明                        |
|--------|-----------------|-----|-----------------------------|
| `0x01` | `PKT_KEYBOARD`  | 8   | HID Boot Keyboard Report    |
| `0x02` | `PKT_MOUSE`     | 5   | HID Mouse Report（相対座標）|
| `0xFF` | `PKT_HEARTBEAT` | 0   | 死活監視（ペイロードなし）  |

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
