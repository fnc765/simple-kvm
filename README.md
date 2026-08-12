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
│   │   ├── amical_bridge.py # Amical音声入力→ローマ字HID変換
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

#### インストーラー版（推奨）

[Releases](https://github.com/fnchoco/simple-kvm/releases) から `simple-kvm-x64-setup.exe` をダウンロードして実行してください。

#### ソースから実行（開発者向け）

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
5. ターゲットへ **Ctrl+Alt+Delete** を送る場合は、Esc でKVMフォーカスを解除してから **Input → Send Special Keys → Ctrl+Alt+Delete** を選択します
   - この機能は既存のキーボードHIDレポートを使用するため、BluePillファームウェアの更新は不要です
6. Amical音声入力を転送する場合は **Input → Amical Romaji Forwarding** をオンにします
   - KVMフォーカス中にF9を押して話し、離すと、日本語の文字起こしがローマ字としてターゲットへ入力されます
   - Enterは自動送信されません。内容を確認して手動で送信してください

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
- **マウスカーソル速度調整**: Settings ダイアログの「Mouse Speed」スライダーで、マウス移動速度を 0.5x 〜 2.0x の範囲で 0.1 刻みに調整できます
- **特殊キー送信**: Input → Send Special Keys から Ctrl+Alt+Delete をターゲットへ送信できます。押下・解放は1つの送信シーケンスとして処理されます
- **Amicalローマ字転送**: AmicalのF9音声入力結果をホスト側でローマ字化し、英数字とスペースのHIDキー入力としてターゲットへ送信します。ターゲット側の受信ソフトやIMEは不要です
  - F9を離してから15秒以内に届いたAmicalの貼り付けを処理し、1回につき最大1,000文字を送信します
- **マウスモード切替** (Phase 1〜2 ホスト側のみ): Settings ダイアログの「Mouse Mode」で以下を選択できます
  - **Relative** (既定): 既存挙動。カーソルを画面中央へ固定し相対 dx/dy を送る
  - **Hybrid**: KVM 開始時に VideoWidget 上のクリック座標へターゲットカーソルをジャンプさせた後、Relative と同じ動作
  - **Absolute**: VideoWidget 内のホストカーソル位置をそのままターゲット PC の絶対座標として送信
  - **「Firmware supports absolute HID」** チェックボックス: 旧ファームウェア (Phase 1〜2) ではオフのまま。Phase 3 firmware を書き込んだ BP2 を使うときだけオンにする
- **設定の永続化**: COM ポート、キャプチャデバイス、アスペクト比、マウス速度、マウスモード、ファームウェア abs サポート設定は自動的に保存され、次回起動時に復元されます。起動時に前回のデバイスが存在すれば自動接続されます

> **Note**: `Hybrid` / `Absolute` モードを使うには **Phase 3 firmware** が BP2 に書き込まれている必要があります。Phase 1〜2 の現行 firmware では「Firmware supports absolute HID」をオンにしないでください（unknown packet としてエラーブリンクします）。Phase 3 firmware は別 PR で提供予定です。

> **SteamVR / OVR 対応**: `Absolute` モードは SteamVR Desktop dashboard (VR 内に Windows desktop を映す機能) での操作性を改善します。OVR Advanced Settings (OVRAS) の VR 内ダッシュボードオーバーレイは OpenVR overlay event 経路で動作するため、本プロジェクトの HID-only 範囲では完全対応しません。

---

## パケットプロトコル

```
[0xAA] [TYPE] [LEN] [PAYLOAD × LEN] [CRC-8-CCITT]
CRC-8-CCITT = table-lookup over TYPE + LEN + PAYLOAD (polynomial 0x07, init 0x00)

TYPE 0x01: Keyboard  (LEN=8) – HID Boot Keyboard Report
TYPE 0x02: Mouse     (LEN=5) – [buttons, dx, dy, wheel_v, wheel_h] (相対座標)
TYPE 0x03: Mouse Abs (LEN=5) – [buttons, x_lo, x_hi, y_lo, y_hi] (絶対座標 0..32767、Phase 3 firmware 必須)
TYPE 0xFF: Heartbeat (LEN=0)
```

詳細は [docs/protocol.md](docs/protocol.md) を参照してください。

---

## ライセンス

本プロジェクトのコードはMIT Licenseです。Amicalローマ字転送ではGPL-3.0-or-laterの`pykakasi`を利用します。配布物に含まれる第三者ソフトウェアについては[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)を参照してください。

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
