# セットアップ手順

## 1. Arduino IDE の準備

### 1-1. STM32duino ボードマネージャの追加

1. Arduino IDE → ファイル → 環境設定
2. 追加のボードマネージャの URL に以下を追加:
   ```
   https://github.com/stm32duino/BoardManagerFiles/raw/main/package_stmicroelectronics_index.json
   ```
3. ツール → ボードマネージャ → `STM32 MCU based boards` をインストール

### 1-2. BluePill #1 のボード設定

| 項目 | 値 |
|------|-----|
| Board | `Generic STM32F103C series` |
| Board part number | `BluePill F103C8` |
| USB support | **CDC (Serial)** ← 必ずこれを選択 |
| Upload method | `STM32CubeProgrammer (DFU)` または `STLink` |
| Optimize | `Smallest (-Os)` |

### 1-3. BluePill #2 のボード設定

| 項目 | 値 |
|------|-----|
| Board | `Generic STM32F103C series` |
| Board part number | `BluePill F103C8` |
| USB support | **No USB** ← USBComposite ライブラリが管理するため |
| Upload method | `STM32CubeProgrammer (STLink)` |
| Optimize | `Smallest (-Os)` |

---

## 2. 必要ライブラリのインストール

### BluePill #2 用: USBComposite_stm32f1

Arduino IDE → スケッチ → ライブラリを管理 →
`USBComposite_stm32f1` で検索してインストール。

または手動インストール:
```
https://github.com/arpruss/USBComposite_stm32f1
```
上記から ZIP をダウンロードし、スケッチ → .ZIP 形式のライブラリをインストール。

---

## 3. ファームウェアの書き込み

### BluePill #1

1. `firmware/bluepill1/bluepill1.ino` を Arduino IDE で開く
2. ボード設定を **1-2** のとおり設定
3. BluePill を DFU モードで接続（BOOT0=1 でリセット）
4. スケッチ → マイコンボードに書き込む

### BluePill #2

1. `firmware/bluepill2/bluepill2.ino` を Arduino IDE で開く
2. ボード設定を **1-3** のとおり設定
3. STLink を接続して書き込む（USB HID として動作中は CDC が使えないため STLink 必須）
4. 書き込み後、USB をターゲット PC に接続するとデバイスマネージャに HID デバイスが現れます

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

### LED インジケータ

| ボード | LED パターン | 意味 |
|--------|-------------|------|
| BP1 | 1 秒周期点滅 | 正常動作中 |
| BP2 | パケット受信時にトグル | 入力受信中 |

---

## 6. トラブルシューティング

| 症状 | 確認事項 |
|------|---------|
| COM ポートが見えない | BP1 の USB support を CDC に設定して再書き込み |
| ターゲット PC で HID が認識されない | BP2 の USB support を No USB に設定して再書き込み |
| 映像が表示されない | Device インデックスを変更して試す。他のカメラアプリを終了する |
| キー入力が届かない | UART クロス接続（PA9↔PA10）を確認 |
| 偽チップ（64 KB Flash）エラー | STLink で書き込む。`Variant` を `BluePill F103C6` に変更して試す |

---

## PlatformIO によるビルド手順

### 必要なツール

- [PlatformIO Core](https://docs.platformio.org/en/latest/core/installation/index.html) のインストール
  ```powershell
  pip install platformio
  ```
- ST-Link デバッガー（書き込みに使用）

### ビルド

プロジェクトルートで実行：

```powershell
# 両方のファームウェアをビルド
pio run

# 環境を指定してビルド
pio run -e bluepill1
pio run -e bluepill2
```

### 書き込み

BluePill を ST-Link で接続した状態で：

```powershell
# bluepill1 を書き込み
pio run -e bluepill1 --target upload

# bluepill2 を書き込み
pio run -e bluepill2 --target upload
```

### ビルド成功時の目安

| 環境 | RAM使用 | Flash使用 |
|------|---------|-----------|
| bluepill1 | ~22% (4.5KB) | ~42% (27KB) |
| bluepill2 | ~18% (3.7KB) | ~36% (23KB) |

---

## Python ホストアプリの起動手順

### 必要な環境

- Python 3.11 以上

### 初回セットアップ

```powershell
cd app
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 起動

```powershell
cd app
.venv\Scripts\activate
python main.py
```

### 使い方

1. **Settings ダイアログ** (File > Settings) でシリアルポートと HDMI キャプチャデバイスを選択して OK
2. 映像エリアを **クリック** して KVM フォーカスモード入り（カーソルが消える）
3. KVM フォーカスモード中はキーボード・マウス入力がターゲット PC に転送される
4. **Esc キー** で KVM フォーカスモードを解除

### インストール済みパッケージ（動作確認済み）

| パッケージ | バージョン |
|-----------|-----------|
| PySide6 | 6.11.0 |
| opencv-python | 4.13.0.92 |
| pyserial | 3.5 |
