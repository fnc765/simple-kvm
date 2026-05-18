# セットアップ手順

ファームウェアのビルドと書き込みには **PlatformIO** を使用します。Arduino IDE には対応していません。

---

## 1. 必要なツールのインストール

### PlatformIO Core

```powershell
pip install platformio
```

または [公式インストールガイド](https://docs.platformio.org/en/latest/core/installation/index.html) を参照してください。

### ST-Link ドライバ

BluePill への書き込みには ST-Link デバッガが必要です。
[STSW-LINK009](https://www.st.com/ja/development-tools/stsw-link009.html) から ST-Link ドライバをインストールしてください。

---

## 2. ファームウェアのビルドと書き込み

### 2-1. ボード設定（platformio.ini に記述済み）

プロジェクトの `platformio.ini` に両環境の設定が含まれています。主な設定:

| 環境 | USB 機能 | ウォッチドッグ | ビルドフラグ |
|------|----------|----------------|--------------|
| bluepill1 | CDC Serial | あり (4 秒) | `-D PIO_FRAMEWORK_ARDUINO_ENABLE_CDC` |
| bluepill2 | HID Composite (内蔵) | あり (4 秒) | `-D USBCON -D USBD_USE_HID_COMPOSITE` |

いずれの環境も `upload_protocol = stlink` です。

### 2-2. ビルド

プロジェクトルートで実行:

```powershell
# 両方のファームウェアをビルド
pio run

# 環境を指定してビルド
pio run -e bluepill1
pio run -e bluepill2
```

### 2-3. 書き込み

BluePill を ST-Link で接続した状態で:

```powershell
# bluepill1 を書き込み
pio run -e bluepill1 --target upload

# bluepill2 を書き込み
pio run -e bluepill2 --target upload
```

### 2-4. ビルド成功時の目安

| 環境 | RAM 使用 | Flash 使用 |
|------|----------|------------|
| bluepill1 | ~22% (4.5KB) | ~42% (27KB) |
| bluepill2 | ~18% (3.7KB) | ~36% (23KB) |

### 2-5. BP2 の USB 設定について

BP2 は STM32duino フレームワークに内蔵された HID Composite (`USBD_USE_HID_COMPOSITE`) を使用します。
旧 libmaple 向けの外部ライブラリ `USBComposite_stm32f1` (arpruss) は不要です。

BP2 の HID Composite は 4 バイトのマウスレポート `[buttons, dx, dy, wheel_v]` を送信します。
水平スクロール（wheel_h）は STM32duino 内蔵 HID Composite が非サポートのため、受信しても破棄されます。

---

## 3. UART 配線

| BluePill #1 | → | BluePill #2 |
|-------------|----|-------------|
| PA9 (TX1) | → | PA10 (RX1) |
| PA10 (RX1) | ← | PA9 (TX1) |
| GND | ↔ | GND |

両ボード間は**クロス接続**（TX ↔ RX）してください。

---

## 4. Python アプリのセットアップ

### 4-1. 依存パッケージのインストール

```powershell
cd app
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 4-2. アプリの起動

```powershell
cd app
.venv\Scripts\activate
python main.py
```

### 4-3. 設定手順

1. File → Settings を開く
2. **Serial Port**: BluePill #1 が接続されている COM ポートを選択
   - デバイスマネージャで「ポート (COM と LPT)」→「STMicroelectronics Virtual COM Port」を確認
3. **Capture Device**: HDMI キャプチャドングルのデバイス番号を選択
   - PC に他のカメラがある場合は Device 1 以降になることがあります
4. OK をクリック → 映像が表示されます

---

## 5. 動作確認

### KVM フォーカスモードの使い方

- VideoWidget（映像エリア）をクリック → KVM フォーカスモード ON
  - マウスカーソルが非表示になります
  - キーボード・マウス操作がターゲット PC へ転送されます
- **Esc キー** を押す → フォーカスモード解除

### 全画面表示の使い方

全画面表示に切り替えると、映像が画面全体に最大化され、没入型の KVM 操作が可能です。

| 操作 | 動作 |
|------|------|
| **F11** キー | 全画面 ON/OFF 切替 |
| **View → Toggle Fullscreen** | メニューから全画面切替 |
| 映像エリアを**ダブルクリック** | 全画面 ON/OFF 切替 |
| **Esc** キー（全画面中） | 全画面解除（KVM モード中は 1 回目で KVM 解除 → 2 回目で全画面解除） |

**全画面時の表示**:
- メニューバー・ステータスバーが非表示になります
- FPS が左上に緑色でオーバーレイ表示されます
- 「Press ESC to exit fullscreen」のヒントが 3 秒間表示されます
- 全画面解除時に元のウィンドウサイズ・位置が復元されます

**アスペクト比の設定**:
- File → Settings の「Aspect Ratio」で以下を選択できます
  - **Maintain Aspect Ratio**: アスペクト比を維持（黒帯が表示される場合があります）
  - **Stretch to Fill**: 画面全体に引き伸ばして表示

### LED インジケータ

| ボード | LED パターン | 意味 |
|--------|-------------|------|
| BP1 | 1 秒周期点滅 | 正常動作中（ウォッチドッグ生存確認） |
| BP2 | パケット受信時にトグル | 入力受信中 |

---

## 6. トラブルシューティング

| 症状 | 確認事項 |
|------|---------|
| COM ポートが見えない | BP1 の USB ケーブルを抜き差し。ビルドフラグ `PIO_FRAMEWORK_ARDUINO_ENABLE_CDC` が有効か確認 |
| ターゲット PC で HID が認識されない | BP2 のビルドフラグ `USBD_USE_HID_COMPOSITE` が有効か確認。書き込み後 3 秒間のエニュメレーション待機が完了するまで待つ |
| 映像が表示されない | Device インデックスを変更して試す。他のカメラアプリを終了する |
| キー入力が届かない | UART クロス接続（PA9↔PA10）を確認 |
| 偽チップ（64 KB Flash）エラー | `platformio.ini` の `board` を `bluepill_f103c6` に変更して試す |
| ファームウェアがハングする | ウォッチドッグ（4 秒）が作動しているか確認。電源投入後 5 秒以上経過しても LED が点滅しない場合はリセット |

---

## インストール済みパッケージ（動作確認済み）

| パッケージ | バージョン |
|-----------|-----------|
| PySide6 | 6.11.0 |
| opencv-python | 4.13.0.92 |
| pyserial | 3.5 |
