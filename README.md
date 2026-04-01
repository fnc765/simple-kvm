# simple-kvm

BluePill × 2 + Python GUI による DIY KVM スイッチです。
ホスト PC のキーボード・マウス操作を USB HID としてターゲット PC へ転送し、
ターゲット PC の映像を HDMI キャプチャ経由でホスト PC に表示します。

---

## システム構成

```
[ホスト PC]
  │
  ├─ USB (CDC Serial) ──► [BluePill #1]
  │                              │
  │                           UART (115200 bps)
  │                              │
  │                              ▼
  │                       [BluePill #2] ──► USB (HID Keyboard + Mouse) ──► [ターゲット PC]
  │                                                                               │
  └─ USB (UVC) ◄── [HDMI キャプチャドングル] ◄──────── HDMI ────────────────────┘
```

---

## ファイル構成

```
simple-kvm/
├── firmware/
│   ├── bluepill1/          # USB CDC → UART ブリッジ
│   │   ├── bluepill1.ino
│   │   ├── packet_parser.h
│   │   └── packet_parser.cpp
│   └── bluepill2/          # UART → USB HID Composite
│       ├── bluepill2.ino
│       ├── packet_parser.h
│       ├── packet_parser.cpp
│       └── hid_handler.h
├── app/
│   ├── main.py             # エントリポイント
│   ├── requirements.txt
│   ├── core/
│   │   ├── capture.py      # OpenCV キャプチャスレッド
│   │   ├── input_hook.py   # 入力状態管理
│   │   ├── keymap.py       # Qt.Key → HID Usage ID 変換
│   │   ├── protocol.py     # パケットエンコーダ
│   │   └── serial_comm.py  # シリアル通信スレッド
│   └── ui/
│       ├── mainwindow.py   # メインウィンドウ
│       └── settings_dialog.py
├── docs/
│   ├── protocol.md         # プロトコル仕様
│   ├── hardware.md         # 配線図・部品リスト
│   └── setup.md            # セットアップ手順
└── README.md
```

---

## クイックスタート

### ファームウェア

詳細は [docs/setup.md](docs/setup.md) を参照してください。

1. Arduino IDE に STM32duino ボードサポートを追加
2. **BP1**: `USB support = CDC (Serial)` で `firmware/bluepill1/bluepill1.ino` を書き込み
3. **BP2**: `USB support = No USB` + `USBComposite_stm32f1` ライブラリをインストールして `firmware/bluepill2/bluepill2.ino` を書き込み
4. PA9(TX)↔PA10(RX) をクロス接続し GND を共通化

### Python アプリ

```powershell
cd app
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

1. File → Settings で COM ポートとキャプチャデバイスを選択
   - **Detect Formats** ボタンでデバイスが対応する解像度・fps の組み合わせを一覧表示し、手動で選択できます
2. 映像エリアをクリックすると **KVM フォーカスモード** に入ります
3. **Esc** キーでフォーカスを解除します

---

## 映像表示・アプリ機能

- **ウィンドウリサイズ対応**: ウィンドウサイズに合わせて映像が自動的にスケールされます
- **HiDPI (高DPI) 対応**: Windows のディスプレイスケーリング設定（125%/150%/200% 等）に対応し、鮮明な映像を表示します
- **映像品質**: キャプチャに MJPEG フォーマットを使用し、1920×1080 で利用可能な最高 fps を自動選択します
- **キャプチャフォーマット選択**: Settings の「Detect Formats」ボタンでデバイスが対応する解像度×fps の組み合わせを一覧表示し、手動で選択できます

---

## パケットプロトコル

```
[0xAA] [TYPE] [LEN] [PAYLOAD × LEN] [CHECKSUM]
CHECKSUM = TYPE ^ LEN ^ PAYLOAD[0] ^ ... ^ PAYLOAD[LEN-1]

TYPE 0x01: Keyboard (LEN=8) – HID Boot Keyboard Report
TYPE 0x02: Mouse    (LEN=5) – [buttons, dx, dy, wheel_v, wheel_h]
TYPE 0xFF: Heartbeat (LEN=0)
```

詳細は [docs/protocol.md](docs/protocol.md) を参照してください。

---

## ライセンス

MIT License

---

## 注意事項

- BluePill の偽チップ（CS32F103C8）は Flash が 64 KB と認識される場合があります。
  STLink での書き込みを推奨します。
- BluePill #2 では USB CDC と USB HID を同時使用できません。
  デバッグ出力が必要な場合は Serial1（UART1）を使用してください。
- 本プロジェクトは個人の学習・実験目的です。
