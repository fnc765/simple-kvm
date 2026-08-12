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
| bluepill2 | HID Composite 3-interface (Phase 3) | あり (4 秒) | `-D USBCON -D USBD_USE_HID_COMPOSITE` |

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
| bluepill2 | ~18% (3.7KB) | ~40% (25.4KB) |

### 2-5. BP2 の USB 設定について

BP2 は STM32duino フレームワークに内蔵された HID Composite (`USBD_USE_HID_COMPOSITE`) を使用します。
旧 libmaple 向けの外部ライブラリ `USBComposite_stm32f1` (arpruss) は不要です。

BP2 の HID Composite は **3 つの HID インターフェース**を露出します (Phase 3 ファームウェア):

| Interface | Class | Protocol | Report |
|-----------|-------|----------|--------|
| 0 (Keyboard) | HID | Boot Keyboard (LED 出力付き) | 8 バイト入力 + 1 バイト出力 (LED) |
| 1 (Mouse)    | HID | Boot Mouse (5-byte relative) | `[buttons, dx, dy, wheel_v, wheel_h]` |
| 2 (Abs Mouse) | HID | Generic Desktop Mouse (absolute) | `[buttons, x_lo, x_hi, y_lo, y_hi]` |

絶対座標マウスを使うには、ホスト側 Settings の **「Firmware supports absolute HID」** チェックボックスをオンにしてください。オフのときは absolute HID 用のパケット (`PKT_MOUSE_ABS`) は送られないので、レガシーフレームウェア (Phase 1〜2) でも問題なく動作します。

水平スクロール (wheel_h) は STM32duino 内蔵 HID Composite が非サポートのため、受信しても破棄されます。

---

## 3. UART 配線

| BluePill #1 | → | BluePill #2 |
|-------------|----|-------------|
| PA9 (TX1) | → | PA10 (RX1) |
| PA10 (RX1) | ← | PA9 (TX1) |
| GND | ↔ | GND |

両ボード間は**クロス接続**（TX ↔ RX）してください。

---

## 3.5. Windows descriptor cache について (Phase 3 firmware)

Phase 3 BP2 firmware は **3-interface HID composite** (Keyboard + Relative Mouse + Absolute Mouse) を公開します。インターフェース数が変わるので、Windows が古い 2-interface ディスクリプタをキャッシュしていると、初回接続時に「不明な USB デバイス」になることがあります。

Phase 3 firmware を書き込んだ後、ターゲット PC で以下を試してください:

1. **USB ポートを差し替える** — 別ポートに挿すと Windows が新しいディスクリプタを読み直す
2. **デバイス マネージャー → デバイスを表示 (非表示デバイスを含む) → 該当の "Logitech USB Receiver" (046D:C52B) をアンインストール** して再挿す
3. **bcdDevice の bump** — `usbd_desc_patch.c` の `0x01, /* bcdDevice rel. 24.01 */` をさらに `0x02` などに上げて再ビルド (VID/PID/Product string は変えません)

VID/PID/Product string (`046D:C52B` / `Logitech` / `USB Receiver`) は Logitech Unifying Receiver エミュレーション維持のため、Phase 3 firmware でも変更しません。bcdDevice のみが 24.00 → 24.01 に bump されています。

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
4. **Aspect Ratio**: 映像のアスペクト比モードを選択
   - **Maintain Aspect Ratio**: アスペクト比を維持（黒帯あり）
   - **Stretch to Fill**: 画面全体に引き伸ばし
5. **Mouse Speed**: マウスカーソル速度を 0.5x 〜 2.0x の範囲で調整（0.1 刻み）
6. OK をクリック → 映像が表示されます

> **設定は自動的に保存**され、次回起動時に復元されます。
> COM ポートとキャプチャデバイスが前回と同じ状態で接続されていれば、起動時に自動接続されます。

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

### マウスカーソル速度の調整

ターゲット PC 上のマウスカーソル感度を調整できます。

- File → Settings の「Mouse Speed」スライダーで調整
- スライダーを右に動かすほどカーソルが速く動きます
- 設定値は即座に反映され、次回起動時も維持されます

### Amical音声入力の転送

AmicalがホストPC上で生成した日本語の文字起こしを、ローマ字のUSB HIDキー入力としてターゲットPCへ転送できます。

1. **Input → Amical Romaji Forwarding** をオンにする
2. 映像エリアをクリックしてKVMフォーカスモードに入る
3. F9を押しながら話し、F9を離す
4. ターゲットPCへのローマ字入力が完了してから、必要に応じてEnterを押す

この機能は次の仕様です。

- F9はAmical専用になり、ターゲットPCへは転送されません
- 漢字・ひらがな・カタカナはローマ字へ変換されます
- 英数字とスペースだけを送信し、句読点や記号は除外します
- Enterは自動送信しません
- ターゲットPC側の受信ヘルパーやIMEは不要です
- Esc、KVMフォーカス解除、切断、または新しいF9操作で送信中の文章をキャンセルできます
- Amicalを使わない場合は設定をオフにするとF9が通常どおりターゲットへ転送されます

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
| Amicalの文章が転送されない | Input → Amical Romaji Forwardingがオンか、KVMフォーカス中か、シリアル接続済みかを確認 |
| 偽チップ（64 KB Flash）エラー | `platformio.ini` の `board` を `bluepill_f103c6` に変更して試す |
| ファームウェアがハングする | ウォッチドッグ（4 秒）が作動しているか確認。電源投入後 5 秒以上経過しても LED が点滅しない場合はリセット |

---

## インストール済みパッケージ（動作確認済み）

| パッケージ | バージョン |
|-----------|-----------|
| PySide6 | 6.11.0 |
| opencv-python | 4.13.0.92 |
| pyserial | 3.5 |
| pykakasi | 2.3.0 |
