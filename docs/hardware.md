# ハードウェア構成・配線図

## システム構成図

```
┌─────────────────────────────────────────────────────────────────────┐
│  ホスト PC                                                           │
│                                                                     │
│  [アプリ (main.py)]──USB CDC──>[BluePill #1]──UART──>[BluePill #2]──USB (HID)──>[ターゲット PC]
│                                                                     │
│  [OpenCV]<──USB (UVC)──[HDMI キャプチャドングル]<──HDMI──[ターゲット PC]
└─────────────────────────────────────────────────────────────────────┘
```

---

## 配線詳細

### BluePill #1 ↔ BluePill #2 UART 接続

```
BluePill #1          BluePill #2
-----------          -----------
PA9  (TX1) ─────────► PA10 (RX1)
PA10 (RX1) ◄───────── PA9  (TX1)   [ACK 用: 現時点では未使用]
GND        ────────── GND
```

> **重要**: TX→RX のクロス接続を確認してください。同じピンを直結すると通信しません。

### BluePill #1 ↔ ホスト PC

```
BluePill #1
-----------
PA11 (USB D-)  ─── USB コネクタ D-  ─── ホスト PC USB
PA12 (USB D+)  ─── USB コネクタ D+
5V (VBUS)      ─── USB コネクタ VBUS（給電元: ホスト PC）
GND            ─── USB コネクタ GND
```

### BluePill #2 ↔ ターゲット PC

```
BluePill #2
-----------
PA11 (USB D-)  ─── USB コネクタ D-  ─── ターゲット PC USB
PA12 (USB D+)  ─── USB コネクタ D+
5V (VBUS)      ─── USB コネクタ VBUS（給電元: ターゲット PC）
GND            ─── USB コネクタ GND
```

> **重要**: BluePill #1 の 5V と BluePill #2 の 5V を直接つなわないでください。
> それぞれのボードは独立した USB 電源から給電します。

---

## ピン一覧

### BluePill #1

| ピン    | 機能       | 接続先 |
|---------|------------|--------|
| PA11    | USB D-     | ホスト PC USB |
| PA12    | USB D+     | ホスト PC USB |
| PA9     | UART1 TX   | BP2 PA10 |
| PA10    | UART1 RX   | BP2 PA9  |
| PC13    | LED (A-Lo) | 内蔵 LED |
| 5V      | 給電       | ホスト PC USB VBUS |
| GND     | GND        | BP2 GND, USB GND |

### BluePill #2

| ピン    | 機能       | 接続先 |
|---------|------------|--------|
| PA11    | USB D-     | ターゲット PC USB |
| PA12    | USB D+     | ターゲット PC USB |
| PA10    | UART1 RX   | BP1 PA9  |
| PA9     | UART1 TX   | BP1 PA10 |
| PC13    | LED (A-Lo) | 内蔵 LED |
| 5V      | 給電       | ターゲット PC USB VBUS |
| GND     | GND        | BP1 GND, USB GND |

---

## 部品リスト

| 部品                  | 数量 | 備考 |
|-----------------------|------|------|
| BluePill (STM32F103C8) | 2   | 正規品推奨（128 KB Flash）|
| USB A-miniB ケーブル  | 2    | BluePill へのフラッシュ・電源供給 |
| HDMI キャプチャドングル | 1  | UVC 対応（USB 接続）|
| HDMI ケーブル         | 1    | ターゲット PC → キャプチャドング |
| ジャンパワイヤ（M-M）  | 4本  | UART 接続用 |

---

## ロジックレベル・電源メモ

- BP1–BP2 間の UART は両方 3.3 V ロジックの STM32 同士のためレベル変換不要
- 5 V ピンに誤接続すると STM32 が破損するため注意
- 偽 BluePill（CS32F103C8）は Flash が 64 KB と認識される場合があり、
  STLink 書き込みが必要になることがあります
