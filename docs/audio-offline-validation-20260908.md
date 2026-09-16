# Audio probe オフライン修正・検証（2026-09-08）

対象: `codex/usb-audio-bridge`、ホスト側修正のベース `fe0b671`、前回の実機検証時点 `754975f`。
以下のオフライン追補は **2026-09-08時点** の記録であり、その時点では USB/COM オープン、
音声/HID送信、reset、flash、再列挙操作を実施していない。
前半は PC 上の検証ツールとテストの修正、追補では実機ログから特定した BP2 の session-timeout 復帰を
`firmware/common` に修正した。2026-09-08時点では修正後バイナリを実機へ書き込んでいない。

## 結論と証拠の境界

PC 側検証コードのバッファ範囲外アクセスを修正し、保存録音に見られる次周回PCM混入に対する送信ガードを追加した。
ソフトウェア上の再現・回帰テスト、全構成ビルド、ELF監査は合格。
ただし、2026-09-08時点では session-timeout 修正後の実機相関値改善、USBドライバの実際のカーソル挙動、
60分のAudio/HID同時動作は未検証であり、実機復旧済みとは扱わない（2026-09-16の追補結果は後述）。
以前の「BP2のリセットが必要」という説明だけでは、以下のホスト側異常を説明できない。

## 保存録音から確認したこと

入力: `.pio/bp2_e2e_capture.raw`（48 kHz、mono、signed PCM16 little-endian、480,000 sample / 960,000 byte）。
対応ログ: `logs/audio_baseline_retry_20260907_204632.log`。

SHA256（解析前後で一致）:

```text
08392CEE805A5881DBF9FE5208FD715222AABA982F1B4D9402D290E667D580DD
```

従来計算の再実行結果:

| 指標 | 値 | 判定 |
| --- | ---: | --- |
| preamble correlation | 0.9985635548 | PASS |
| PRBS aggregate correlation | 0.9967001287 | PASS |
| PRBS block p05 correlation | 0.9831287462 | **FAIL**（基準 0.995） |
| PRBS block数 | 250 | PASS |
| capture/source alignment jump | 0 / 0 | PASS |
| 録音時間 | 10.000秒 | PASS |

異常な連続4 sampleを参照波形と照合すると、14箇所で、本来の位置ではなく **38,400 sample先** のPCMと一致した。
38,400 は元の実行ログに記録されたWASAPI render bufferのフレーム数と一致する。
14箇所の次周回参照へのfit RMSは約0.23〜1.08 PCM count。本来位置へのRMSは約4,787〜14,605 countだった。
例: capture index 165481 からの4 sampleは source position 203232.9426 に一致し、通常推定位置との差は38400.0352 sample。
生録音の値の置換、異常sampleの除外、相関しきい値の緩和は行っていない。

これはホスト側リングの次周回データが混入したことを強く示すが、保存波形だけではWindows内部の原因までは確定できない。
「報告された空き領域とUSB転送完了位置とのずれ」は検証モデル上の仮説であり、Microsoft APIの一般的仕様として断定しない。

## 修正内容

### 送信バッファ

- 旧処理ではsignal終端後の `take == 0` の場合、すでに無音で満たしたpayloadへ無音を再度追加し、取得領域の **2倍** を `memmove` していた。
- `render_buffer.py` で取得frame数に正確に一致するpayloadを一度だけ生成し、長さ検証後にGetBufferする。
- コピー失敗時も取得済みpacketを解放する。
- timer-driven exclusiveでは1 scheduling period（現在4,800 frame）をガードとして残し、書き込みをUSB 1 ms相当の48 frame単位へ切り下げる。Start前の初期prefillは別扱い。
- ガードを置けない小さなbufferや不正なpaddingは明示的に失敗させる。

取得領域のサイズとframeのbyte幅については、Microsoftの[IAudioRenderClient::GetBuffer](https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudiorenderclient-getbuffer)および[IAudioClient::GetCurrentPadding](https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudioclient-getcurrentpadding)を参照。
ガードの有効性は、読み取りカーソルが1/6/47/48/4799 frame先行するモデルで検証した。旧policyで次周回PCM混入を再現し、新policyでは4周にわたり不一致0となる。
これは実際のUSBドライバ挙動を測定した結果ではない。
終端時の二重無音コピーと、終端前の次周回混入は別の問題として扱う。

### 録音バッファ

- ログ出力が常にfloat32 stereoを仮定し、mono float32の場合に読み過ぎる処理を除去。
- `capture_buffer.py` で実際の `nBlockAlign` とframe数に一致する範囲だけ読み取る。
- SILENT packetはdata pointerを参照せず、無音データを生成。非SILENTのNULLは明示的に失敗させる。
- packet previewと本処理で同じ安全に取得したbyte列を使用する。

packetのframe数・状態flagの契約はMicrosoftの[IAudioCaptureClient::GetBuffer](https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudiocaptureclient-getbuffer)を参照。

### 判定・オフライン解析

- 信号生成・相関・ASRC追跡を `waveform.py` に分離。既存の9計算関数はAST比較で変更なしを確認。
- `analyze_saved_capture.py` はUSB/serial/WASAPIモジュールを読み込まず、録音ファイルをread-onlyで解析する。
- 旧録音の不合格を保持。NaN/Infinity/欠損値、PRBS block不足、要求時間に満たない録音も不合格。
- 連続音声モードでは先頭の試験区間だけでなく録音全体の無音途絶を検査。相関追跡自体は最初のPRBS区間であり、全周回の完全な波形一致を保証するものではない。
- RMS/peak/全体無音検査をchunk処理にし、長時間録音の一括float64変換を回避。int16最小値のpeak計算も修正。
- live probeは不合格時にexit code 1。`--help` / 不正な引数はデバイス開始前に終了する。
- 保存波形専用markerは `AUDIO_OFFLINE_PASS/FAIL`。live/E2Eの合格markerとは分離する。

### 長時間実機ログからの BP2 session-timeout 修正

前回の `logs/hid3_continuous_60m_after_commit_20260908.log` は、試験プロセス自体は
3,600 秒・172,800,000 capture frames まで走ったが、約169.2 秒以降の録音が無音になった。
その時点の診断は、BP2 の `source_timeouts=10`、`stale_session_controls=3,431,778`、
`spi_crc/gap/short/overrun=0` であり、CRC破損ではなく session state の復帰失敗と整合する。
BP1 は alt=1 の同一 session を継続するため、受信タイムアウト後に新しい SESSION_START を送らない。

`SourceSessionState` に timeout-only の復帰ラッチを追加し、同じ認証済み boot nonce/session counter の
最初の PCM だけを再開として受け入れるようにした。明示的な SESSION_END、別 boot nonce、別 session counter
にはこのラッチを適用せず、従来どおり stale fail-closed とする。ネイティブ回帰テストでは、同一 session の
timeout→PCM復帰と、明示的 END 後の同一 session PCM拒否を別々に確認している。

## 実施した検証

| 検証 | 結果 |
| --- | --- |
| Python全テスト | **271 passed** |
| メモリcanary付き実コピー・録音読み出しテスト | PASS |
| 正常ASRC波形、±1000 ppm追跡 | PASS |
| 欠落・重複・次周回PCM・切断・NaN・無音途絶の検出 | PASS |
| C++ native（`/W4 /WX`） | **AUDIO_UNIT_PASS tests=2848** |
| 同C++テスト（MSVC AddressSanitizer付き） | **AUDIO_UNIT_PASS tests=2848**、検出エラーなし |
| ASRCドリフト -1000/-500/-100/0/+100/+500/+1000 ppm | 各24時間相当の加速simulation PASS（実時間soakではない） |
| BP1/BP2 × audio/legacy | **4構成ビルド成功**、ビルドログのwarning/errorなし |
| BP1 audio ELF | 0483:A1D0、descriptor 174 byte、PMA 488/512 byte、PASS |
| BP2 audio ELF | 046D:C52C、descriptor 183 byte、PMA 384/512 byte、PASS |
| legacyのlinked device descriptor | BP1 0483:5740 / BP2 046D:C52B、PASS |
| Python compileall、help、競合marker、git diff --check | PASS |
| 元の失敗録音の再判定 | **期待どおりFAIL**、exit 1、p05は0.9831287462のまま |

## 実機検証（修正前バイナリ）

`754975f` のホスト側修正後バイナリで、reset/flashなしに次を実施した。

| 試験 | 結果 |
| --- | --- |
| 10秒 exclusive audio | `AUDIO_SINGLE_HOST_PASS`、480,000 frames、PRBS p05 0.9999290839 |
| 20秒 Audio+HID smoke | `AUDIO_HID_SIMULTANEOUS_PASS`、keyboard make/break balanced |
| 60分 HID3 continuous | **FAIL**。約169.2秒以降無音、`continuous_unexpected_zero_run` |

この60分結果は今回の timeout-recovery 修正を含まないため、修正後の実機合格証拠ではない。
修正後 ELF はビルド・native 回帰・descriptor/PMA audit までで、flash および再実機試験は未実施である。

## 実機フォローアップ（2026-09-16）

`f96e4c6` の firmware 修正後に BP2 (`046D:C52C`) へ flash し、OpenOCD の Verify OK、
Resetting Target、PlatformIO SUCCESS を確認した。OpenOCD の target voltage warning は表示されたため、
電源条件は引き続き注意する。今回の実機試験は同一PC上の one-PC HIL であり、独立2台のhost clockを
証明する `AUDIO_E2E_PASS` ではなく `AUDIO_SINGLE_HOST_PASS` として記録する。

| 試験 | 結果 |
| --- | --- |
| Python全テスト | **275 passed**、検証hookの経過時間上限（60秒）内 |
| C++ native audio | **AUDIO_UNIT_PASS tests=2859** |
| BP1/BP2 audio・legacy build | **4構成 SUCCESS** |
| BP2 ELF descriptor/PMA audit | **AUDIO_ELF_AUDIT_PASS**、046D:C52C、183 byte、384/512 byte |
| 10秒 exclusive audio | **AUDIO_SINGLE_HOST_PASS**、PRBS p05 0.999929、gap 0 |
| 30秒 Audio/HID3 intermediate | **HID3_INTERMEDIATE_PASS**、keyboard make/break balanced |
| 300秒 final integration（Audio＋HID3） | **AUDIO_SINGLE_HOST_PASS / HID3_CONTINUOUS_PASS**、14,400,000 frames、unexpected zero run 0、keyboard make/break 12,905/12,905 |

すべての入口で `VERIFICATION_POLICY_REMINDER` を先に出し、途中確認は60秒以下、最終統合確認は
300秒以上でなければデバイスを開かない。今回の最終ログは
`logs/hid3_final_integration_after_timeout_gap_fix_20260916.log` に保存した。

独立2台PCのtwo-PC E2E、物理抜き差し・電源サイクルを含むreconnect/recovery matrix、6時間soakは、
別のtarget PCまたは自動電源設備が必要なため、この作業環境では未実施であり、release gateへは繰り上げない。

ログは `logs/offline_*_20260908.log` に保存。
詳細な保存波形照合は `logs/inspect_saved_audio.py` と `logs/offline_ring_diagnostic_20260908.log`。
生PCMや実行ログはGitに追加していない。

## デバイスなしで再実行

numpy / pytest が利用できるPython環境で、リポジトリルートから実行する。

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest -q -p no:cacheprovider --basetemp .pio/pytest-offline
python tools/audio_test/analyze_saved_capture.py .pio/bp2_e2e_capture.raw --expected-seconds 10
```

後者はこの失敗録音に対してexit 1が正しい。既存の連続録音を解析する場合のみ `--continuous` を追加する。
新しい録音は取得しない。

```powershell
./tools/audio_test/run_native_tests.ps1
pio run -e bluepill1_legacy -e bluepill2_legacy -e bluepill1_audio -e bluepill2_audio
python tools/audio_test/audit_firmware.py --env bluepill1_audio
python tools/audio_test/audit_firmware.py --env bluepill2_audio
```

`pio run` にupload targetは指定しない。修正後 binary の10秒baseline、短時間Audio/HID、
300秒の最終統合確認は上記のとおり完了した。今回の実機結果を独立2 PCのrelease E2E合格へ読み替えない。
