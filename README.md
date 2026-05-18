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
│   ├── common/              # 共通パケットパーサ（CRC-8 検証含む）
│   │   ├── packet_parser.h
│   │   └── packet_parser.cpp
│   ├── bluepill1/           # USB CDC → UART ブリッジ
│   │   └── main.cpp
│   └── bluepill2/           # UART → USB HID Composite
│       ├── main.cpp
│       ├── hid_handler.h
│       └── hid_handler.cpp
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

1. [PlatformIO Core](https://docs.platformio.org/en/latest/core/installation/index.html) をインストール
2. ST-Link デバッガを接続し、BluePill を ST-Link で接続
3. **BP1**: `pio run -e bluepill1 --target upload` で書き込み（USB CDC 有効、4 秒ウォッチドッグ付き）
4. **BP2**: `pio run -e bluepill2 --target upload` で書き込み（STM32duino 内蔵 HID Composite、4 秒ウォッチドッグ付き）
5. PA9(TX)↔PA10(RX) をクロス接続し GND を共通化

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
4. **F11** キー / **View → Toggle Fullscreen** / 映像エリアの**ダブルクリック** で全画面表示に切り替えられます
   - 全画面中も Esc でフォーカス解除 → もう一度 Esc で全画面解除（2段階）
   - 全画面解除時に元のウィンドウサイズ・位置が復元されます

---

## 映像表示・アプリ機能

- **ウィンドウリサイズ対応**: ウィンドウサイズに合わせて映像が自動的にスケールされます
- **HiDPI (高DPI) 対応**: Windows のディスプレイスケーリング設定（125%/150%/200% 等）に対応し、鮮明な映像を表示します
- **映像品質**: キャプチャに MJPEG フォーマットを使用し、1920×1080 で利用可能な最高 fps を自動選択します
- **キャプチャフォーマット選択**: Settings の「Detect Formats」ボタンでデバイスが対応する解像度×fps の組み合わせを一覧表示し、手動で選択できます
- **全画面表示 (Fullscreen)**:
  - F11 キー / View → Toggle Fullscreen / 映像エリアのダブルクリックで全画面切替
  - 全画面時はメニューバー・ステータスバーが非表示になり、FPS が左上にオーバーレイ表示されます
  - Esc キーで復帰（KVM フォーカスモード中は 1 回目で KVM 解除 → 2 回目で全画面解除）
  - 全画面解除時に元のウィンドウサイズ・位置が完全に復元されます
- **アスペクト比設定**: Settings ダイアログで「Maintain Aspect Ratio」（黒帯あり）と「Stretch to Fill」（画面全体に引き伸ばし）を切り替え可能

---

## パケットプロトコル

```
[0xAA] [TYPE] [LEN] [PAYLOAD × LEN] [CRC-8-CCITT]
CRC-8-CCITT = table-lookup over TYPE + LEN + PAYLOAD (polynomial 0x07, init 0x00)

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
- BluePill #2 は STM32duino フレームワーク内蔵の HID Composite で動作します。
  外部ライブラリ `USBComposite_stm32f1` は不要です。
- マウス水平スクロール（wheel_h）は STM32duino 内蔵 HID Composite が非サポート
  のため、BP2 でデータは破棄されます。
- 本プロジェクトは個人の学習・実験目的です。
