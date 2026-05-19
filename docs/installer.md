# simple-kvm ビルド手順

Windows 向けのインストーラー（`simple-kvm-x64-setup.exe`）を作成する手順です。

---

## 前提環境

- **Windows 10 / 11 (x64)**
- **Python 3.11 以上**
- **Git**（任意、ソース取得用）

---

## 1. リポジトリの取得

```powershell
git clone https://github.com/fnchoco/simple-kvm.git
cd simple-kvm
```

---

## 2. 依存関係のインストール

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r app/requirements.txt
pip install pyinstaller
```

---

## 3. PyInstaller で EXE をビルド

```powershell
pyinstaller --onedir --windowed --noupx --clean simple-kvm.spec
```

出力先: `dist/simple-kvm/`

### ビルド検証

```powershell
# 起動テスト
.\dist\simple-kvm\simple-kvm.exe
```

### トラブルシューティング

| 症状 | 対処法 |
|------|--------|
| `ModuleNotFoundError: PySide6.QtCore` | `.spec` の `hiddenimports` にモジュールを追加 |
| `av.error.FFmpegError` (codec not found) | `.spec` で `av.codec` / `av.format` が `hiddenimports` に含まれているか確認。`--collect-all av` を試す |
| キャプチャデバイスが表示されない | `pygrabber` が正しくバンドルされているか確認 |
| ウィンドウが表示されない | 一度 `--console` でビルドし、標準エラー出力を確認 |
| アンチウイルスにブロックされる | `--noupx` が有効か確認。コード署名を検討 |

---

## 4. Inno Setup でインストーラーを作成

### Inno Setup のインストール

[Inno Setup ダウンロードページ](https://jrsoftware.org/isdl.php) からインストーラーを入手するか：

```powershell
choco install innosetup -y
```

### インストーラーのビルド

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

出力先: `Output/simple-kvm-0.1.0-x64-setup.exe`

---

## 5. CI/CD（GitHub Actions）

`v*` タグをプッシュすると、GitHub Actions で自動ビルドが実行されます。

```powershell
git tag v0.1.0
git push origin v0.1.0
```

手動実行も可能: GitHub リポジトリ → Actions → Build Windows Installer → Run workflow

---

## 6. 配布前チェックリスト

- [ ] `simple-kvm-x64-setup.exe` をクリーンな Windows 環境でインストール
- [ ] 管理者権限プロンプトが表示されること
- [ ] `%PROGRAMFILES%\simple-kvm\` にインストールされること
- [ ] スタートメニュー・デスクトップショートカットから起動できること
- [ ] アプリが正常に起動し、メインウィンドウが表示されること
- [ ] アンインストーラーが正常動作すること
- [ ] [VirusTotal](https://www.virustotal.com) で誤検知チェック
