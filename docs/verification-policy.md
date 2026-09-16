# Verification execution policy

検証入口は、デバイスへ接続する前に `tools/verification_policy.py` の
preflight hookを呼び出し、次のリマインドをログへ出します。

```text
intermediate verification <= 60 seconds; final integration >= 300 seconds
```

## 時間区分

- `intermediate`（既定値）: 途中確認。計画時間は最大60秒。
- `final-integration`: 最後の統合確認だけに使用。計画時間は最低300秒（5分）。

`SIMPLE_KVM_VERIFICATION_STAGE` で区分を指定します。60秒を超える中間確認や、
5分未満の最終統合確認は、デバイスを開く前に非0終了します。

## 実行例

短い確認:

```powershell
$env:SIMPLE_KVM_VERIFICATION_STAGE = "intermediate"
$env:BP_E2E_RUN_SECONDS = "30"
$env:BP_E2E_EXCLUSIVE = "1"
$env:BP_E2E_RENDER_MIX = "0"
$env:BP_E2E_CAPTURE_MIX = "0"
$env:BP_E2E_RAW = "0"
.venv\Scripts\python.exe tools/audio_test/_bp_e2e_hid3_continuous.py
```

最後の統合確認:

```powershell
$env:SIMPLE_KVM_VERIFICATION_STAGE = "final-integration"
$env:BP_E2E_RUN_SECONDS = "300"
.venv\Scripts\python.exe tools/audio_test/_bp_e2e_hid3_continuous.py
```

最終統合確認の成功markerは `HID3_CONTINUOUS_PASS` です。中間確認は
`HID3_INTERMEDIATE_PASS` として記録し、リリース合格へ読み替えません。

pytest、native unit、ELF audit、保存波形解析、HID loopback、Audio/HID smokeの
各入口も同じhookを表示します。pytestは実時間が60秒を超えた場合も失敗します。
