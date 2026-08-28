# simple-kvm mono USB audio bridge 詳細実装計画

| 項目 | 内容 |
| --- | --- |
| 文書状態 | Proposed / 実装前 |
| 作成日 | 2026-08-28 |
| 調査基準 | main 24e04bf |
| 対象MCU | BluePill 2台、STM32F103C8 |
| 対象OS | ホストPC・ターゲットPCともにWindows 10/11 |
| 音声仕様 | 48 kHz、mono、signed PCM 16-bit little-endian |
| 既存機能 | BP1 USB CDC、UART HID転送、BP2の3 HIDを維持 |

## 1. 文書の目的

本計画は、simple-kvmの既存HID機能を維持しながら、ホストPCの音声をターゲットPCへUSB Audioとして転送するための実装、検証、デバッグ、リリース判定を定義する。

完成時の見え方は次の通りとする。

- ホストPCからBluePill #1は、既存COMポートとmono音声出力デバイスの複合USBデバイスに見える。
- ターゲットPCからBluePill #2は、既存のキーボード、相対マウス、絶対マウスに加えて、monoマイクに見える。
- ホストPCでBP1の音声出力を選ぶと、BP1からBP2へSPIでPCMが転送され、ターゲットPC上のアプリケーションはBP2のマイクから同じ音声を取得できる。
- HID・制御パケットは既存UART経路を維持する。音声を115200 bps UARTへ多重化しない。
- ビルド成功、USB列挙成功、ホスト側再生成功、ターゲット側録音成功を別々の検証状態として扱う。

本書は実装担当者がPhase順に作業できる粒度を目標とする。実装済み、実機検証済み、リリース可能を同じ意味では扱わない。

## 2. 決定事項

### 2.1 採用する方式

- USB Audio Class 1.0を使用する。
- サンプリング周波数は48,000 Hz固定とする。
- チャンネル数はmono固定とする。
- サンプル形式はsigned PCM 16-bit little-endianとする。
- 1 USB frameあたり48 sample、96 byteを送受信する。
- BP1をSPI1 master、BP2をSPI1 slaveとする。
- SPIはMode 0、MSB first、初期クロック4.5 MHzとする。
- SPIはDMAを使用し、USB割り込み内で同期的なSPI転送を行わない。
- BP2はターゲットPCのUSB SOFに同期して毎ms 48 sampleを送る。
- BP1側USBとBP2側USBの独立クロック差は、BP2のリングバッファとASRCで吸収する。
- UAC1のハードウェア音量・ミュートFeature Unitは初期実装に含めない。OS・アプリ側のソフトウェア音量を使用する。
- USB Audioのsampling frequency controlは宣言せず、48 kHz固定フォーマットだけを公開する。

### 2.2 採用しない方式

- 音声を既存UART 115200 bpsへ流さない。mono 48 kHz/16-bitだけで768 kbps必要なため帯域不足である。
- HID・音声・診断を1つの可変長UARTパケットへ統合しない。
- 44.1 kHz、stereo、24-bit、USB Audio Class 2.0は初期スコープに含めない。
- 音声欠落時の再送を行わない。リアルタイム性を優先し、無音補完または短いランプで処理する。
- GUIアプリが音声をキャプチャしてCOMへ送る構成にしない。Windowsの音声エンジンからBP1のUSB Audio endpointへ直接出力する。
- 初期実装で音質向上用のFIR resampler、ノイズ抑制、AGC、echo cancellationを追加しない。

## 3. 現在の基準状態

### 3.1 BP1

現在のfirmware/bluepill1/main.cppは次の機能を持つ。

- ホストPCにUSB CDCとして接続する。
- CDCから受信した既存バイナリパケットを検証する。
- 検証済みパケットをUART1 115200 bpsでBP2へ転送する。
- PA9をUART TX、PA10をUART RXに使用する。
- UART逆方向は配線されているが、コード上は未使用である。
- 4秒watchdogとPC13 heartbeat LEDを使用する。

### 3.2 BP2

現在のBP2は3-interface HID compositeである。

| Interface | 機能 | Endpoint |
| --- | --- | --- |
| 0 | Keyboard | interrupt IN |
| 1 | Relative mouse | interrupt IN |
| 2 | Absolute mouse | interrupt IN |

DEV_NUM_EPは0x04へ修正済みで、キーボード、相対マウス、絶対マウスの3 endpointを使用する。既存の静的テストはdescriptor、endpoint open/close、DataIn busy解除を確認している。

### 3.3 現在のテスト・CI

- tests/test_firmware_static.pyは主にソーステキストからUSB構造を検査している。
- tests/test_protocol.pyはホストとfirmware間のパケット形式を固定している。
- tests/test_serial_comm.pyはfake serial、queue、timeout、cancelを検査している。
- .github/workflows/build.ymlはWindowsアプリとinstallerを構築するが、pytestとfirmware buildは現在の必須jobではない。
- test_ci.ps1も主目的はWindows installerのローカル再現である。

Audio実装では既存テストを維持しつつ、実際に生成されたELFとUSB descriptorを検査するテストを追加する。

## 4. 要求仕様

### 4.1 機能要求

1. ホストPCはBP1をCOMポートとmono音声出力の両方として列挙できること。
2. ターゲットPCはBP2を既存3 HIDとmonoマイクの両方として列挙できること。
3. BP1のCDCパケット、UART HID転送、BP2のHID reportは既存動作を維持すること。
4. BP1へ48 kHz mono PCMを連続再生すると、BP2のマイクから同じ信号を連続取得できること。
5. 2台のPCのUSBクロックが異なっても、長時間でring overflowまたはunderflowを起こさないこと。
6. 音声stream open/close、USB reset、短時間のSPIエラー後に自動復帰すること。
7. 通常試験ではCOM番号やオーディオデバイスを人が毎回選択しないこと。
8. 実装build ID、reset reason、各種カウンタをホストPCから回収できること。

### 4.2 性能要求

| 項目 | 目標 |
| --- | --- |
| USB packet | 96 byte/ms固定 |
| SPI frame | Audio stream中は112 byte/USB DataOut、通常1 frame/ms |
| SPI使用時間 | 4.5 MHz時に約0.20 ms/frame |
| BP2 ring容量 | 1024 sample、約21.3 ms |
| BP2 ring目標 | 512 sample、約10.7 ms |
| ASRC試験範囲 | source/target相対差 -1000から+1000 ppm |
| 連続試験 | release候補で60分、nightlyで6時間 |
| 自動復帰 | stream reopenは5秒以内、再列挙は15秒以内かつEndpoint ACTIVE後5秒以内 |
| E2E遅延 | WASAPI exclusive modeで250 ms未満を安全上限とする |

250 msは製品目標ではなく、異常なバッファ蓄積を検出する初期安全上限である。最初の実機基準測定後、中央値とp99を記録し、より厳しいrelease上限を設定する。

### 4.3 非機能要求

- setup完了後のfirmware hot pathでは動的メモリ確保を行わない。
- USB ISRとDMA ISRではbuffer swapとcounter更新を中心とし、長い解析処理を行わない。
- watchdogはmain loopのhealth条件を通過したときだけ更新する。ISRから更新しない。
- テスト失敗は終了コード非0と機械可読なAUDIO_FAILレコードで表す。
- 生の長時間WAVをGitへ追加しない。失敗箇所前後の短いWAVとJSON summaryだけを保存する。
- 製品buildではfault injection commandを無効化する。

## 5. 全体アーキテクチャ

~~~text
Host PC
  Windows audio engine
      |
      | USB Audio render, 48 kHz mono PCM16
      v
BluePill #1
  CDC + UAC1 composite
  audio OUT ping-pong buffer
  SPI1 master DMA
      |
      | PA4 NSS / PA5 SCK / PA7 MOSI / PA6 MISO
      | fixed 112-byte full-duplex frame per BP1 USB Audio packet
      v
BluePill #2
  SPI1 slave DMA
  CRC / sequence validation
  1024-sample ring buffer
  fill-level PI controller + linear ASRC
  HID x3 + UAC1 microphone composite
      |
      | USB Audio capture, 48 kHz mono PCM16
      v
Target PC
~~~

既存HID経路は次のまま残す。

~~~text
Host application -> BP1 CDC -> UART1 -> BP2 packet parser -> HID x3 -> Target PC
~~~

音声とHIDは、BP1内部とBP2内部のqueue、DMA、USB endpointを共有しない。共有するのはCPU、RAM、watchdog、USB peripheralだけである。

## 6. ハードウェア配線

既存UART配線を残したまま、SPI1を追加する。

| BP1 | 方向 | BP2 | 用途 |
| --- | --- | --- | --- |
| PA4 | output | PA4 | NSS |
| PA5 | output | PA5 | SCK |
| PA7 | output | PA7 | MOSI、PCM BP1からBP2 |
| PA6 | input | PA6 | MISO、status BP2からBP1 |
| GND | - | GND | 共通基準 |

制約:

- BP1とBP2の5 Vピンを相互接続しない。
- 両ボードは現在と同じく、それぞれ接続先PCのUSBから給電する。
- SPIとUARTは3.3 Vロジックのためレベル変換しない。
- 初期検証ではSPI配線長を15 cm以下にする。
- signal integrityに問題がある場合だけ、BP1側SCK、MOSI、NSSへ22から47 ohmのseries resistorを検討する。
- GND接続により2台のPCのgroundが接続される点は現行UART構成と同じである。絶縁が必要な設備では別途USBまたはdigital isolator設計が必要であり、初期スコープ外とする。

## 7. BP1 USB設計

### 7.1 composite構成

BP1はCDCとUAC1 speaker/renderの複合デバイスとする。

| Interface | Class | 内容 |
| --- | --- | --- |
| 0 | CDC Communication | ACM control |
| 1 | CDC Data | COM data |
| 2 | Audio Control | UAC1 topology |
| 3 alt 0 | Audio Streaming | zero-bandwidth |
| 3 alt 1 | Audio Streaming | mono PCM16 48 kHz OUT |

IADを使うため、device descriptorのclass tupleは0xEF、0x02、0x01を採用する。WindowsのCDCとAudio class driverが両機能を別々にbindできることをdescriptor試験と実機列挙で確認する。

### 7.2 endpoint割り当て

STM32F103のendpoint registerでは同じ番号のIN/OUTがendpoint typeを共有する。この制約を利用し、物理endpoint register数を0から3に抑える。

| Endpoint | Type | Direction | 用途 | Max packet | Buffer |
| --- | --- | --- | --- | ---: | --- |
| EP0 | Control | IN/OUT | USB control | 64 | single each |
| EP01 | Isochronous synchronous | OUT | Audio PCM | 96 | double |
| EP02 | Bulk | OUT | CDC RX | 64 | single |
| EP82 | Bulk | IN | CDC TX | 64 | single |
| EP83 | Interrupt | IN | CDC notification | 8 | single |

現在のSTM32duino CDC defaultであるEP01 OUT、EP82 IN、EP83 INは、Audio用にEP01を空けるため、CDC OUTだけEP02へ変更する。CDC data IN/OUTを同じphysical endpoint 2へまとめる。

### 7.3 UAC1 descriptor

Audio Control topologyは最小構成とする。

~~~text
USB Streaming Input Terminal, ID 1
    -> Speaker Output Terminal, ID 2
~~~

Audio Streaming alt 1:

- Format Type I
- PCM format tag
- 1 channel
- 2 byte subframe
- 16 bit resolution
- 1 discrete sample frequency: 48,000 Hz
- wMaxPacketSize: 96
- bInterval: 1
- endpoint bmAttributes: 0x0D、isochronous、synchronous、data endpoint
- sampling frequency controlなし

BP1にはUSB SOFと独立した音声消費clockを置かず、受信した48 sampleをそのhost SOF domainのままSPI queueへ移す。このためAudio OUTはsynchronous sinkとして宣言する。48 kHzでは毎msのsample数が整数48となるため、44.1 kHzのようなpacket長の周期変動は発生しない。feedback endpointは使用しない。

descriptor fieldを次の値へ固定する。

| Descriptor | Field | Value |
| --- | --- | --- |
| CDC IAD | first/count/class/subclass/protocol | 0 / 2 / 0x02 / 0x02 / 0x01 |
| Audio IAD | first/count/class/subclass/protocol | 2 / 2 / 0x01 / 0x00 / 0x00 |
| AC interface | class/subclass/protocol | 0x01 / 0x01 / 0x00 |
| AC header | bcdADC | 0x0100 |
| AC header | wTotalLength | 30 byte |
| AC header | collection | bInCollection=1、baInterfaceNr=3 |
| Input Terminal | ID/type/assoc/channels/config | 1 / 0x0101 / 0 / 1 / 0 |
| Output Terminal | ID/type/assoc/source | 2 / 0x0301 / 0 / 1 |
| AS alt 1 | class/subclass/protocol/endpoints | 0x01 / 0x02 / 0x00 / 1 |
| AS General | terminal/delay/format | 1 / 1 / PCM 0x0001 |
| Format Type I | channels/subframe/bits/frequencies | 1 / 2 / 16 / 1 |
| Format Type I | tSamFreq | 0x80、0xBB、0x00 |
| Standard EP | address/attributes/max/interval | 0x01 / 0x0D / 96 / 1 |
| Standard EP | refresh/synch address | 0 / 0 |
| Class-specific EP | attributes/lock units/lock delay | 0 / 0 / 0 |

string indexは0またはproject固有string tableの値を使用し、descriptor auditでは長さ、entity ID参照、terminal link、interface collectionまで検査する。

### 7.4 PMA budget

BP1は最も厳しいresource gateである。

| 領域 | byte |
| --- | ---: |
| Buffer table、4 physical endpoint | 32 |
| EP0 OUT + IN | 128 |
| Audio OUT double buffer | 192 |
| CDC OUT single buffer | 64 |
| CDC IN single buffer | 64 |
| CDC notification | 8 |
| 合計 | 488 / 512 |

PMA残量は24 byteだけである。次を必須条件とする。

- CDC OUTをsingle bufferとして設定する。
- PMA addressを自動計算だけに任せず、compile後のep_defと各addressを検査する。
- すべてword alignmentを満たす。
- 領域重複または512 byte超過をbuild failureにする。
- audio OUTを96 byte未満に縮小しない。
- 新しいendpointをBP1へ追加しない。

### 7.5 class driver方針

使用中のSTM32duino USBDevice libraryにはCDCとHIDはあるがAudio class implementationは含まれない。BP1では、既存CDC APIを維持するローカルpatchとしてCDC+Audio composite classを実装する。

要件:

- ArduinoのSerial APIと既存CDC interface callbackを壊さない。
- CDC class request、DataIn、DataOutを既存実装から維持する。
- interface 2、3とEP01のrequest/callbackをAudio処理へrouteする。
- SET_INTERFACEでAudio Streaming alt 0/1を管理する。
- alt 0ではEP01を停止し、audio bufferとpending状態をクリアする。
- alt 1ではdouble-buffered EP01を開き、常に次の96 byte受信をarmする。
- descriptor配列とclass callbackを同じtranslation unitで管理し、framework更新時の差分を追跡できるようにする。
- 借用したST middleware codeがある場合は元licenseとTHIRD_PARTY_NOTICES.mdを更新する。

## 8. BP2 USB設計

### 8.1 composite構成

BP2は既存3 HIDへUAC1 microphone/captureを追加する。

| Interface | Class | 内容 |
| --- | --- | --- |
| 0 | HID | Keyboard |
| 1 | HID | Relative mouse |
| 2 | HID | Absolute mouse |
| 3 | Audio Control | UAC1 topology |
| 4 alt 0 | Audio Streaming | zero-bandwidth |
| 4 alt 1 | Audio Streaming | mono PCM16 48 kHz IN |

Audio functionにはIADを付ける。device descriptor class tupleはBP1と同様に0xEF、0x02、0x01を採用し、既存HIDのdriver bindingをWindows 10/11で確認する。

### 8.2 endpoint割り当て

| Endpoint | Type | Direction | 用途 | Max packet | Buffer |
| --- | --- | --- | --- | ---: | --- |
| EP0 | Control | IN/OUT | USB control | 64 | single each |
| EP81 | Interrupt | IN | Relative mouse | 8 | single |
| EP82 | Interrupt | IN | Keyboard | 8 | single |
| EP83 | Interrupt | IN | Absolute mouse | 8 | single |
| EP84 | Isochronous synchronous | IN | Microphone PCM | 96 | double |

DEV_NUM_EPは0x05へ変更する。既存HID endpoint番号とreport descriptorは変更しない。

### 8.3 UAC1 descriptor

Audio Control topology:

~~~text
Microphone Input Terminal, ID 1
    -> USB Streaming Output Terminal, ID 2
~~~

Audio Streaming alt 1:

- Format Type I
- PCM format tag
- 1 channel
- 2 byte subframe
- 16 bit resolution
- 48,000 Hz固定
- wMaxPacketSize: 96
- bInterval: 1
- endpoint bmAttributes: isochronous, synchronous, data endpoint
- sampling frequency controlなし

BP2はターゲットPCのSOFごとに必ず48 sampleを生成するため、Audio IN endpointをsynchronousとして宣言する。

descriptor fieldを次の値へ固定する。

| Descriptor | Field | Value |
| --- | --- | --- |
| Audio IAD | first/count/class/subclass/protocol | 3 / 2 / 0x01 / 0x00 / 0x00 |
| AC interface | class/subclass/protocol | 0x01 / 0x01 / 0x00 |
| AC header | bcdADC | 0x0100 |
| AC header | wTotalLength | 30 byte |
| AC header | collection | bInCollection=1、baInterfaceNr=4 |
| Input Terminal | ID/type/assoc/channels/config | 1 / 0x0201 / 0 / 1 / 0 |
| Output Terminal | ID/type/assoc/source | 2 / 0x0101 / 0 / 1 |
| AS alt 1 | class/subclass/protocol/endpoints | 0x01 / 0x02 / 0x00 / 1 |
| AS General | terminal/delay/format | 2 / 1 / PCM 0x0001 |
| Format Type I | channels/subframe/bits/frequencies | 1 / 2 / 16 / 1 |
| Format Type I | tSamFreq | 0x80、0xBB、0x00 |
| Standard EP | address/attributes/max/interval | 0x84 / 0x0D / 96 / 1 |
| Standard EP | refresh/synch address | 0 / 0 |
| Class-specific EP | attributes/lock units/lock delay | 0 / 0 / 0 |

BP2でもwTotalLengthだけでなく、AC collection、terminal source、bTerminalLink、class-specific endpoint descriptorを生成物から検査する。

### 8.4 PMA budget

| 領域 | byte |
| --- | ---: |
| Buffer table、5 physical endpoint | 40 |
| EP0 OUT + IN | 128 |
| HID IN x3 | 24 |
| Audio IN double buffer | 192 |
| 合計 | 384 / 512 |

BP2には約128 byteの余裕があるが、Audio INはdouble bufferを維持する。PMA検査はBP1と同様にcompile後の値を使用する。

### 8.5 class driver方針

現在のusbd_hid_composite_patch.cを基準としてHID+Audio compositeへ拡張する。

- 既存3 HID descriptor、setup handler、send function、DataIn busy解除を維持する。
- Interface 3、4のAudio descriptorとsetup routingを追加する。
- EP84 open/close、double buffer、DataIn callbackを追加する。
- Audio alt setting 0/1をHID用AltSettingと別のstateで管理する。
- capture alt 1から0ではring、ASRC phase、PI integralをclearし、SPIから届くPCMをringへ追加せずdiscarded_capture_closedを増加する。
- capture alt 0から1ではcapture session countを増加し、ringとASRC stateを再度clearしてprefillから開始する。
- EP84完了後、次の96 byte packetをdeadline前に準備する。
- HID send pathがAudio stateやAudio buffer lockを取得しない設計にする。
- Audio送信がbusyでもHID reportを捨てない。逆も同様とする。

## 9. USB identityとWindows cache

現在のBP2はLogitech VID/PID/Product stringを使用している。Audio interface追加後も同じidentityを使用すると、既存Windows descriptor cacheやLogitech softwareのfilter driverと競合する可能性がある。

初期実装では次の二段階で扱う。

1. 開発buildではdescriptor variantとbcdDeviceを変更し、検証対象であることをbuild metadataへ記録する。
2. 同一USB portで古いdescriptorが残った場合は、自動テストのpreflightでinstance情報を表示し、試験環境に限ってデバイス削除または別port使用を明示する。

外部配布前には、正規に使用可能なVID/PIDを決定する。現行の他社VID/PID維持を外部配布の前提にしてはならない。この決定はrelease gateであり、Audio機能の内部実装とは分離する。

自動識別性を高めるため、可能であればSTM32 unique device ID由来の安定したUSB serial stringをBP1とBP2に設定する。legacy HID互換性のためBP2 serial追加を避ける場合は、target agentがContainer IDとphysical USB locationを保存し、試験開始時に一致を検証する。

## 10. SPI transport

### 10.1 物理・peripheral設定

- SPI1 Mode 0
- 8-bit data
- MSB first
- BP1 master、software-controlled NSS output
- BP2 slave、hardware NSS input
- 初期clock 4.5 MHz
- BP1 DMA RX channel 2、TX channel 3
- BP2 DMA RX channel 2、TX channel 3
- Audio alt 1中、BP1が受信したUSB Audio DataOut packetごとに112 byte固定長のfull-duplex transaction
- NSS lowからDMA開始、112 byte完了後にNSS high

SPI transactionのpaceはBP1のfree-running timerではなく、BP1 USB Audio DataOutに従属させる。通常はhost SOFごとに1回、48 sampleを受信して1 transactionをqueueする。これによりBP1内部へ第三の独立sample clockを作らない。

DMA channel割り当てはSTM32F103C8のreference manualと実際のframework HAL macroで実装時に再確認し、compile-time assertまたはstatic testを置く。

### 10.2 audio frame format

すべて固定112 byte、little-endianとする。

| Offset | Size | Field | 内容 |
| ---: | ---: | --- | --- |
| 0 | 2 | magic | 0xA5, 0x5A |
| 2 | 1 | version | 初期値1 |
| 3 | 1 | flags | VALID、DISCONTINUITY、MUTE、TEST、各種control marker |
| 4 | 2 | sequence | uint16、毎frame増加 |
| 6 | 4 | boot_nonce | BP1 boot generationを表すuint32 |
| 10 | 2 | session_counter | boot内のAudio alt 1開始ごとに増加するuint16 |
| 12 | 1 | sample_count | 0から48、通常48 |
| 13 | 1 | reserved | 0固定 |
| 14 | 96 | pcm_or_control | int16 mono最大48 sample、またはcontrol payload |
| 110 | 2 | crc16 | offset 2から109を対象 |

CRCはCRC-16/CCITT-FALSEとし、polynomial、initial value、reflection、xoroutをcommon headerとPython reference testで固定する。

flagsはbit 0 VALID、bit 1 DISCONTINUITY、bit 2 MUTE、bit 3 TEST、bit 4 SESSION_START、bit 5 SESSION_END、bit 6 RUN_START、bit 7 RUN_ENDとする。CRC-16/CCITT-FALSEはpolynomial 0x1021、initial 0xFFFF、refin=false、refout=false、xorout 0x0000とする。

sample_countが48未満の場合もframe長は変えず、未使用PCM領域を0で埋める。不明version、48超過、CRC不一致、magic不一致はframe全体を破棄する。RUN_STARTまたはRUN_ENDではsample_count=0とし、pcm_or_control先頭4 byteをlittle-endian `run_id`、残り92 byteを0とする。

### 10.3 MISO status frame

同じ112 byte transactionのMISO方向で、BP2が前回transaction終了時点のstatus snapshotを返す。先頭32 byteを次の固定schemaとし、offset 32から111は0にする。すべてlittle-endianである。

| Offset | Size | Field | Type |
| ---: | ---: | --- | --- |
| 0 | 2 | magic | 0x5A、0xA5 |
| 2 | 1 | version | uint8、初期値1 |
| 3 | 1 | flags | HEALTHY、PREFILL、ASRC_CLAMP、USB_CONFIGURED |
| 4 | 2 | ack_sequence | uint16 |
| 6 | 2 | ring_fill | uint16 sample |
| 8 | 2 | ring_min | uint16 sample |
| 10 | 2 | ring_max | uint16 sample |
| 12 | 2 | crc_errors | saturating uint16 |
| 14 | 2 | sequence_gaps | saturating uint16 |
| 16 | 2 | underflows | saturating uint16 |
| 18 | 2 | overflows | saturating uint16 |
| 20 | 2 | asrc_ppm | int16 |
| 22 | 1 | audio_alt | uint8 |
| 23 | 1 | reset_reason | enum uint8 |
| 24 | 2 | spi_short_transfers | saturating uint16 |
| 26 | 2 | hid_drops | saturating uint16 |
| 28 | 2 | duplicates | saturating uint16 |
| 30 | 2 | status_crc16 | CRC-16/CCITT-FALSE、offset 0から29 |

status flagsはbit 0 HEALTHY、bit 1 PREFILL、bit 2 ASRC_CLAMP、bit 3 USB_CONFIGURED、bit 4 SPI_ERROR_LATCHED、bit 5から7を0とする。reset_reasonは0 UNKNOWN、1 POWER_ON、2 EXTERNAL_PIN、3 SOFTWARE、4 IWDG、5 WWDG、6 LOW_POWER、7 HARD_FAULTとする。

より大きいcumulative counter、uptime、build IDはUART diagnostics pageから取得する。MISOの16-bit counterはwrapさせず0xFFFFでsaturateする。

SPI full-duplexのため、このstatusは最大1 frame遅延する。リアルタイム制御には使用せず、health監視とfailure localizationに使用する。

### 10.4 BP1送信buffer

BP1はUSB Audio OUTのdouble bufferとは別に、4-slotのSPI用PCM queueとDMA ping-pong frameを持つ。

1. USB DataOut callbackは96 byteを4-slot SPSC transport event queueへcopyし、source SOFとvalid flagを記録する。PCMとrun markerは同じFIFO順序を共有する。
2. main loopが未送信slotからSPI frameを組み立てる。queueはUSB callbackのmicro-jitterを吸収するだけであり、rate変換には使用しない。
3. CRCを計算し、DMA transactionを開始する。
4. TX DMA completeだけではNSSをhighにしない。RX DMA complete、TX DMA complete、SPI BSY clearの3条件を満たした後にNSSをhighにする。BSY待ちはboundedにし、timeout時はSPIをresetする。
5. source SOFまたはDataOut sequenceにgapがあれば、次に送る有効frameへDISCONTINUITYを付ける。packetが来ていない期間をfree-running timerで埋めない。
6. SPI DMAが前回frameのままbusy、または4-slot queueがfullならspi_deadline_missを増加し、その古いframeを後追い送信しない。

BP1は起動ごとに`boot_nonce`を生成し、Audio alt 1開始ごとに`session_counter`を増加する。source session IDは`(boot_nonce:uint32, session_counter:uint16)`の組であり、その後の全PCM/control frameへ付ける。`boot_nonce`はSTM32 unique ID、reset flags、最初のUSB configuration時点のfree-running timerをCRC32で混合して生成する。暗号学的乱数とは扱わず、UART側の下記同期手順と組み合わせて再利用時の安全性を保証する。

BP1 boot直後はAudioをmute/discard状態に置き、BP2へ向かうUART TXを固定60 msだけ抑止する。この時間は既存parserの50 ms timeoutと最大packet wire timeの合計を上回る。CDCから到着するHID packetは32-slotのboot queueへ完全なframe単位で保持し、入力の有無によって60 msを延長しない。1 slotは最大20 byte frameと4 byte metadataを含む24 byte、合計768 byteとする。60 ms後、BP1はTX DMA stateをresetし、`AUDIO_CONTROL_SYNC(boot_nonce, sync_request_id)`をBP2へ最優先で送る。そのpacket境界を確立した直後からHID転送を再開するため、音声同期失敗がHIDを無期限に停止させない。

boot/reconnect stressの保証範囲は、CDC endpointがACTIVEになってから最大400 packet/s、各packet最大20 byte、10秒間連続とする。UART 115200 bps、8N1の理論上限は11,520 byte/sで、20 byte packetなら576 packet/sである。60 ms barrier中に最大24 packetが到着するため32 slotで8 packetの余裕があり、barrier後は最悪packet長でも176 packet/s以上の純drain能力が残る。queueはbarrier解除後500 ms以内に空になることをgateとする。COMが切断中でhost write自体が受理されなかったtokenは到達保証の母数に含めず、再列挙後にcontrollerが再送する。

400 packet/sまたは32 slotを超えた入力は保証外だがsilent lossにはしない。BP1は新着packetをframe単位でrejectし、`hid_boot_queue_overflow`をlatchして試験を即failさせ、UART復帰後にkeyboard all-releaseとmouse button releaseを優先送信する。host runnerと通常アプリは400 packet/s以下へrate-limitし、overflow通知をユーザーへ表示する。

`sync_request_id`はbootごとに生成するuint32で、BP1は同じ`(boot_nonce, sync_request_id)`をACKまで使用する。ACK timeoutは100 ms、最初の2秒間は最大20回再送し、その後はAudioをmuteしたrecovery stateのまま1秒周期で再送する。BP1は一致するACKを受けるまでSESSION_STARTもPCMも送らない。5秒以内に同期できなければreconnect testをfailし、`audio_control_sync_failed`をlatchするが、CDC/HID処理は継続する。

BP2は新しいSYNC tupleを初めて受理したときだけ旧source sessionを無効化し、ring、phase、PI integral、sequence baselineをclearしてtupleを保存する。同じtupleの再送は副作用なしにACKだけ返す。UART受信FIFOは順序を維持するため、旧bootの完全なpacketはSYNCより前に処理され、旧bootのpartial packetは60 ms barrier中にparser timeoutで破棄される。別tupleは新しいboot barrierとして受理する。これによりnonceが偶然再利用されても、旧bootから遅延したUART controlが新sessionへ適用されない。また、遅れて到着したduplicate SYNCが新SESSION_START後にringを再clearすることもない。SPIには永続queueがなく、BP1 reset後3 msでBP2 source timeoutが旧SPI sessionを無効化する。

Audio SET_INTERFACEでalt 0から1へ移るときは、DataOutを待たず、sample_count=0、SESSION_START、DISCONTINUITY、MUTEを持つcontrol transactionを1回queueする。`session_counter`を増加させ、その後のPCM frameへ同じsource session IDを付ける。

alt 1から0へ移るときは、sample_count=0、SESSION_END、MUTEを持つcontrol transactionを1回queueする。DMAがbusyで送れない場合にもBP2が確実に停止できるよう、UART diagnostics/control経路でもAUDIO_SESSION_ENDを送る。

### 10.5 BP2受信buffer

BP2は常に次のNSSに備えてRX/TX DMAをarmする。

1. DMA completeでRX bufferをswapする。
2. main loop側がmagic、version、sample_count、CRC、sequenceを検査する。
3. valid sampleをringへ追加する。
4. 異常frameは追加せず、counterとdiscontinuity stateを更新する。
5. 次回MISO用status snapshotを空きTX bufferへ作る。
6. NSS rising時に転送長不足またはSPI overrunを検出した場合、SPI peripheralとDMAを再armする。

SESSION_STARTまたはsource session ID変化を受信した場合、BP2はring、phase、PI integral、sequence baselineを破棄し、prefillへ戻る。SESSION_ENDまたはMUTE controlを受信した場合もringをclearし、USBへ0を送る。Audio stream中にSPI transactionが3 ms以上到着しない場合はsource_timeoutをlatchし、同じclear/prefill処理を行う。これによりBP1 resetやfinal control transaction欠落時も前sessionのPCMを再利用しない。

BP2 capture interfaceがalt 0の間は、valid SPI PCMを検証・countするがringへ入れず破棄する。capture alt 1へ戻った時点でcapture sessionを新しく開始し、source sessionが継続中でも新しいPCMだけでprefillする。source session IDとBP2 capture session countは別のstateとして扱う。

## 11. ring bufferとASRC

### 11.1 ring buffer

- int16_t 1024 sampleのpower-of-two ringとする。
- headとtailはsingle producer、single consumerとして扱う。
- SPI受信側だけがproducer、USB Audio IN生成側だけがconsumerとなる。
- fill計算、head/tail更新は短いcritical sectionまたはatomic ownershipで保護する。
- 目標fillは512 sampleとする。
- startup時は512 sample近くまでprefillし、それまではUSBへ0を送る。

### 11.2 なぜASRCが必要か

BP1はホストPCのUSB SOFを基準に毎秒約48,000 sampleを受ける。BP2はターゲットPCのUSB SOFを基準に毎秒48,000 sampleを送る。両PCのclockは独立しているため、名目が同じ48 kHzでも長時間ではring fillが一方向へ移動する。

単純なsample drop/duplicateはclickと周期ノイズを生むため、BP2で線形補間ASRCを使用する。

### 11.3 ASRC algorithm

- 出力はターゲットUSB SOFごとに必ず48 sample生成する。
- 入力ring上のstepをsigned Q2.30、phase accumulatorを64-bit Q2.30相当で管理する。Q2.30は1.0より大きい1.002も表現できる。
- x0とx1からlinear interpolationする。
- phaseが1 sampleを超えた回数だけringをadvanceする。
- fill errorはcurrent_fill - 512とする。
- 8 msごとにPI controllerを更新する。
- fillが多い場合はstepを1.0より大きくし、入力を速く消費する。
- fillが少ない場合はstepを1.0より小さくする。
- step補正は初期値として±2000 ppmでclampする。
- integralにはanti-windupを入れる。
- controller gainはnative simulationで決め、実機で無根拠に調整しない。
- interpolationの乗算は64-bit intermediateを使用し、full-scale入力でoverflowしないことをunit testする。

### 11.4 startup、underflow、overflow

Startup:

- alt 1開始後もringがprefill thresholdへ達するまで0を返す。
- 音声開始時に1 ms程度のlinear rampを適用する。
- PI integralとphaseを初期化する。

Underflow:

- 残存sampleや古いbufferを繰り返さない。
- 0を返し、underflow countを増やす。
- ASRC controllerをholdし、prefill後に再開する。

Session transition:

- SESSION_START、SESSION_END、source session ID変化、AUDIO_CONTROL_SYNC、3 ms source timeoutはすべてold PCMを破棄する。
- BP2 capture alt 1から0、および0から1もring、phase、PI integralをclearする。
- capture alt 0中のincoming PCMは保持せずdiscardする。
- 新sessionのprefillが完了するまで0を返す。
- previous source session IDの遅延frameはsequenceが妥当でも破棄する。
- session clear回数とsource timeout回数をdiagnosticsへ記録する。

Overflow:

- overflow countを増やす。
- 遅延した古い音声を再生し続けないよう、oldest sampleを捨ててtarget fill付近へ戻す。
- discontinuityを記録し、controller integralをresetする。

CRCまたはsequence error:

- 破損frameをringへ入れない。
- 不足分は結果的にunderflowまたはASRC補正で処理する。
- realtime audioで再送しない。

## 12. firmwareモジュール計画

### 12.1 common

| 予定ファイル | 責務 |
| --- | --- |
| firmware/common/audio_format.h | PCM定数、packet size、compile-time assert |
| firmware/common/audio_frame.h/.cpp | SPI frame encode/decode、CRC、sequence |
| firmware/common/audio_ring.h/.cpp | SPSC ring |
| firmware/common/audio_asrc.h/.cpp | fixed-point interpolation、PI controller |
| firmware/common/audio_diag.h | counterとstatus schema |

common codeはArduino型、USB型、HAL globalへ依存させない。native unit testで同じC/C++ sourceを直接実行できる形にする。

### 12.2 BP1

| 予定ファイル | 責務 |
| --- | --- |
| firmware/bluepill1/usbd_cdc_audio_patch.h/.c | composite descriptorとclass callback |
| firmware/bluepill1/usbd_ep_conf_audio.c | endpoint/PMA配置 |
| firmware/bluepill1/audio_usb_out.h/.cpp | UAC OUT buffer ownership |
| firmware/bluepill1/audio_spi_master.h/.cpp | SPI master DMAと1 ms frame送信 |
| firmware/bluepill1/audio_control.h/.cpp | diagnostics commandとstatus集約 |

firmware/bluepill1/main.cppはsetupとtask schedulingに限定し、USB class実装、SPI状態機械、diagnosticsを分離する。

### 12.3 BP2

| 予定ファイル | 責務 |
| --- | --- |
| firmware/bluepill2/usbd_hid_audio_composite_patch.h/.c | HID x3 + UAC descriptorとcallback |
| firmware/bluepill2/usbd_ep_conf_audio.c | DEV_NUM_EP=5とPMA配置 |
| firmware/bluepill2/audio_spi_slave.h/.cpp | SPI slave DMAとframe validation入口 |
| firmware/bluepill2/audio_usb_mic.h/.cpp | 48 sample/ms生成、ASRC呼び出し |
| firmware/bluepill2/audio_test_source.h/.cpp | 997 Hz等のtest mode |

Phase 2ではusbd_hid_audio_composite_patch.*を新規に作り、同じcommit内で既存usbd_hid_composite_patch.*をbuild対象から外す。既存HID実装を移植したうえでAudioを追加し、同じUSB symbolのpatchを複数残さない。

### 12.4 build設定

platformio.iniに次を追加する。

- audio feature flag
- fault injection用test flag
- CDC single buffer flag
- BP1 custom endpoint define
- BP2 DEV_NUM_EP=5 override
- 必要なframework symbol override
- native test environment

feature flag例:

~~~text
SIMPLE_KVM_AUDIO=1
AUDIO_SAMPLE_RATE=48000
AUDIO_CHANNELS=1
AUDIO_BITS=16
AUDIO_TEST_HOOKS=0 or 1
~~~

Audioなしのlegacy firmware profileを残し、USB列挙不能時に既知のfirmwareへ戻せるようにする。

## 13. diagnostics protocol

### 13.1 transport

既存UART packetは最大payload 16 byteであり、HID/control用として維持する。音声はSPIだけで送る。

UART逆方向を有効化し、BP2からBP1へpaged diagnostics responseを送る。BP1はCDCへ返し、host test runnerがCOMから取得する。

既存アプリが受信データを前提にしていないため、通常動作中に勝手に大量送信しない。hostからrequestがあった場合だけresponseする。

### 13.2 command案

| Command | 方向 | 内容 |
| --- | --- | --- |
| GET_CAPS | Host -> BP1/BP2 | protocol version、feature bit、build ID |
| GET_STATUS | Host -> BP1/BP2 | page指定でcounter取得 |
| GET_RUN_SNAPSHOT | Host -> BP1/BP2 | `run_id`指定で不変snapshot取得 |
| AUDIO_RUN_START | Host -> BP1 | payload: `run_id uint32`、測定開始markerをFIFOへ挿入 |
| AUDIO_RUN_END | Host -> BP1 | payload: `run_id uint32`、測定終了markerをFIFOへ挿入 |
| CLEAR_COUNTERS | Host -> BP1/BP2 | stream停止中の表示用counter初期化。E2E判定には使用しない |
| AUDIO_TEST_TONE | Host -> BP2 | 内蔵tone開始/停止 |
| AUDIO_TEST_FAULT | Host -> BP1/BP2 | test buildのみ障害注入 |
| AUDIO_TEST_MODE | Host -> BP1/BP2 | deterministic pattern選択 |
| AUDIO_CONTROL_SYNC | BP1 -> BP2 | payload: `boot_nonce uint32`、`sync_request_id uint32` |
| AUDIO_CONTROL_SYNC_ACK | BP2 -> BP1 | 同じSYNC tupleを返す。duplicateにもACK |
| AUDIO_SESSION_END | BP1 -> BP2 | payload: `boot_nonce uint32`、`session_counter uint16`、`reason uint8` |

既存packet typeと衝突しない値を割り当て、docs/protocol.mdへ反映する。production buildでAUDIO_TEST_FAULTを受信した場合は明示的unsupported responseを返す。

AUDIO_SESSION_ENDはSPIのSESSION_END control transactionを送れなかった場合のfallbackであり、通常host commandとして公開しない。BP2はpayloadのsource session IDがactive source session IDと一致し、source_session_activeがtrueの場合だけ適用する。一致しないstale ENDは破棄してstale_session_controlsを増加する。同じIDのduplicate ENDはstateを再変更せずACKだけ返す。BP1 boot時の固定60 ms TX barrier、idempotent SYNC handshake、この完全一致判定により、古いUART ENDが新しいSPI SESSION_STARTの後に到着して新sessionをclearすることを防ぐ。

#### 測定markerと原子的snapshot

各deviceのcumulative counterを別々の時刻にclearして比較してはならない。代わりにrunnerは一意な`run_id`でAUDIO_RUN_STARTとAUDIO_RUN_ENDをBP1へ送る。BP1はmarkerをPCMと同じtransport event FIFOへ挿入し、BP2へ追加のSPI control transactionとして送る。4.5 MHzでは112 byte transactionが約0.20 msであり、markerと同じ1 ms内のPCMを合わせても約0.40 msなので帯域上限内である。

境界は次のように定義する。

1. marker挿入時、BP1は短いcritical sectionでFIFO順序を確定し、そのmarkerより前にenqueue済みのUSB packet数を`usb_audio_boundary`へ保存する。割り込みが同時に来た場合もPCMがmarkerの前か後かのどちらか一方へ必ず順序付けされる。
2. BP1はmarkerより前のPCM frameをすべて送信した後、RUN_STARTまたはRUN_END transactionを送る。その直前の`spi_pcm_frames`と状態counterを同じsnapshotへ追記する。
3. BP2は同じ`run_id` markerをCRC/sequence検証後に受理し、それ以前に受理した`accepted_pcm_frames`と状態counterを不変snapshotへ保存する。
4. BP1/BP2は直近4 run分のstart/end snapshotを保持する。duplicate markerはcounterを再取得せず既存snapshotをACKし、同じ`run_id`の矛盾する再利用はerrorとする。
5. runnerは両deviceから同じ`run_id`とmarker sequenceのsnapshotを取得できるまでtimed windowを開始または終了しない。

したがってstartとendの差分は同じPCM集合を囲み、`delta usb_audio_boundary == delta spi_pcm_frames == delta accepted_pcm_frames`を厳密に判定できる。これは同一wall-clock時刻のsnapshotではなく、共通SPI markerで定義した同一論理境界である。

### 13.3 counters

BP1:

- usb_audio_packets、usb_audio_bytes、usb_audio_short、usb_audio_bad_size
- usb_audio_alt、usb_audio_alt_transitions、usb_audio_reset、usb_audio_suspend、usb_audio_resume
- audio_source_boot_nonce、audio_source_session_counter、audio_source_session_starts、audio_source_session_ends
- audio_control_sync_requests、audio_control_sync_retries、audio_control_sync_acks、audio_control_sync_failures
- usb_audio_overwrite、usb_audio_missing_ms
- spi_pcm_frames、spi_control_frames、spi_dma_busy、spi_deadline_miss
- spi_status_crc_error、BP2 health flags
- cdc_rx、cdc_tx、uart_tx、uart_rx、hid_boot_queue_high_water、hid_boot_queue_overflow
- uptime、reset_reason、build_id

BP2:

- spi_rx_frames、accepted_pcm_frames、accepted_control_frames
- spi_magic_error、spi_version_error、spi_crc_error、spi_sequence_gap、spi_duplicate、spi_short_transfer、spi_overrun
- source_boot_nonce、source_session_counter、source_session_starts、source_session_ends、source_session_clears
- source_timeouts、stale_session_controls、control_sync_accepts、control_sync_duplicates
- capture_alt、capture_alt_transitions、capture_session_starts、capture_session_clears
- discarded_capture_closed
- ring_fill、ring_min、ring_max
- asrc_step_ppm、asrc_integral、asrc_clamp_count
- usb_mic_packets、usb_mic_bytes、usb_mic_reset、usb_mic_suspend、usb_mic_resume
- underflow、overflow、prefill_count
- hid_send_busy、hid_drop per interface
- uptime、reset_reason、build_id

Counterは32-bit wrapを許容し、host parserはunsigned差分で扱う。ring fill、current alt、source session ID、ASRC値はsnapshotとして扱う。run snapshotには`run_id`、marker type、marker SPI sequence、`usb_audio_boundary`、cumulative counter群、alt/session stateを含め、作成後は変更しない。CLEAR_COUNTERSはstream停止中の表示と単体fault試験だけに限定し、active alt/sessionを変更しない。live E2Eのcross-device equalityやtransition判定には使用しない。

firmwareはalt change、source session start/end、capture session start/clear、USB reset/suspend/resume、run marker作成をdiagnostic eventとしても記録する。timed runでは共通RUN_START/RUN_END snapshotを比較し、usb_audio_alt_transitions=0、capture_alt_transitions=0、USB reset/suspend/resume delta=0を要求する。最終altが1であるだけでは連続稼働の証明にしない。

## 14. host test system

### 14.1 構成

tools/audio_test以下に通常アプリから独立した検証ツールを置く。

| 予定ファイル | 責務 |
| --- | --- |
| controller.py | 全体状態機械、BP1再生、結果集約 |
| target_agent.py | BP2録音、HID Raw Input収集、remote command |
| windows_audio.py | MMDevice列挙、WASAPI stream |
| signals.py | MLS、997 Hz、chirp生成 |
| analyze_capture.py | alignment、frequency、gain、gap解析 |
| device_inventory.py | USB、COM、audio endpoint、ST-Link識別 |
| evidence.py | JSONL、summary、PASS marker |
| run_audio_validation.ps1 | build、flash、testの入口 |

Python optional dependency groupとしてaudio-testを追加し、numpy、sounddevice、comtypesを使用する。sounddeviceのWASAPI RawInputStream/RawOutputStreamでPCM16を扱い、comtypesのMMDevice列挙結果とfriendly name、direction、Container IDを照合する。複数候補または対応付け不能時はpreflight failureにする。versionは上限付きでpinし、THIRD_PARTY_NOTICES.mdとpackage scopeを更新する。通常のsimple-kvm installerへtest-only dependencyを含めない。

transport integrity testはWASAPI exclusive event-driven modeで行い、render/captureとも48 kHz、mono、PCM16を直接negotiationする。shared modeは互換性smokeとして別runにし、gainやcorrelationのrelease判定へ使用しない。

sounddeviceのRawInputStream/RawOutputStreamにおけるRawはPython側bufferがbyte列であることを意味し、WindowsのAUDCLNT_STREAMOPTIONS_RAWを意味しない。本計画の必須integrity contractはexclusive mode、auto conversionなし、PCM16直接negotiationとする。

test runnerは開始前にendpoint/session volumeとenhancement状態を記録し、APIで変更可能ならvolumeをunityへ設定して終了時に復元する。既知のAPO/enhancementがexclusive streamへ残りnumeric gateへ影響する環境では、sounddevice経路をpassさせず、IAudioClient2/3とAUDCLNT_STREAMOPTIONS_RAWを直接扱う専用WASAPI helperをPhase 6で実装する。RAW processingを使った場合はAPI、flag、negotiated formatをevidenceへ記録する。

### 14.2 Windows endpoint識別

- COM番号だけでdeviceを特定しない。
- USB VID/PID、serial、Container ID、physical locationをinventoryへ記録する。
- IMMDeviceEnumeratorでeRenderとeCaptureを列挙する。
- Endpoint ID、friendly name、state、Container IDを記録する。
- controllerはBP1 render endpointをID指定で開く。
- target agentはBP2 capture endpointをID指定で開く。
- system default audio deviceを変更しない。
- endpointが複数一致した場合は自動で推測せずpreflight failureにする。初回だけinstance選択を保存できるようにする。

### 14.3 2台PC連携

target agentはtarget PC上のscheduled taskとしてログイン時に起動可能にする。

remote protocol:

- LAN内TCPまたは既存SSH/WinRMを利用する。
- 独自TCPを使用する場合は、初回生成したrandom tokenで認証する。
- localhost以外へlistenする場合はWindows Firewall ruleを明示する。
- commandとresultはlength付きJSONとし、任意コード実行機能を持たせない。
- PREPARE、START_CAPTURE、STOP_CAPTURE、RUN_HID_CHECK、GET_RESULTにcommandを限定する。

PC間の時計同期は合格条件にしない。音声preambleの相互相関で録音位置を合わせる。

### 14.4 evidence形式

各runは一意のsession IDを持ち、次を生成する。

~~~text
logs/audio-validation/YYYYMMDD_HHMMSS-session/
  manifest.json
  device-inventory.json
  events.jsonl
  summary.json
  platformio-bluepill1.log
  platformio-bluepill2.log
  descriptor-audit.json
  failure-window.wav
~~~

failure-window.wavは失敗前後の短いrolling windowだけを保存する。成功runでは原則保存しない。

events.jsonlはappend後にflushし、最終session_resultには次を含める。

- verification_scope
- tested boundaries
- untested boundaries
- pass/fail metric一覧
- firmware build ID
- USB instance/endpoint ID
- SPI/UAC/HID counter差分
- failure reason

## 15. test signalと解析

### 15.1 signal sequence

標準信号を次の順番で生成する。

1. 500 ms silence
2. MLS/PN sync preamble
3. 997 Hz、-12 dBFS、2秒
4. 100 Hzから10 kHzの短いlog chirp
5. deterministic pseudo-random PCM、2秒
6. MLS end marker
7. 500 ms silence

997 Hzは48 kHzに対して短い整数周期に揃いにくく、欠落や周波数誤差を見つけやすい。pseudo-random区間はblock欠落、重複、順序逆転の相関検出に使用する。

### 15.2 解析項目

- capture formatが48 kHz、mono、16-bitであること
- preamble相互相関で開始位置を検出できること
- 推定E2E latency
- 997 Hzの推定周波数
- RMS gain
- clipping sample数
- DC offset
- 1 ms以上の予期しないzero run
- block欠落、重複、局所的な時間伸縮
- ASRCで説明可能な全体rate ratio
- firmware counterとの差分整合

### 15.3 初期合格値

| Metric | Gate |
| --- | --- |
| format | 48 kHz / mono / PCM16に完全一致 |
| 997 Hz frequency | 996から998 Hz |
| gain | reference比 ±0.25 dB |
| clipping | 0 sample |
| sync correlation | rate補正後のzero-mean normalized correlationが0.995以上 |
| unexpected gap | 1 ms超が0回 |
| nominal CRC/sequence error | 0 |
| nominal underflow/overflow | 0 |
| ring fill | 5秒以内に1秒平均40から60 percent、以後瞬時20から80 percent |
| ASRC clamp | nominal runで0回 |
| E2E latency | exclusive modeで250 ms未満 |

これらは初回実機runで測定可能性を確認する。測定系の誤差で不安定なmetricは削除せず、測定方法を修正してからthresholdを変更する。

correlationはMLS/pseudo-random区間からsource/target rate ratioを推定し、そのratioでreferenceをresampleしてから、zero-mean normalized cross-correlationを計算する。gain ±0.25 dBは997 Hzのsteady segmentだけへ適用する。chirpは初期実装では周波数応答の記録用とし、同じgain gateを適用しない。

## 16. テスト階層

### 16.1 Layer A: hardware-free unit test

対象:

- audio frame encode/decode
- CRC既知vector
- sequence wrap、gap、duplicate
- ring wrap、full、empty
- ASRC interpolation
- PI anti-windup
- startup、underflow、overflow state machine
- status page encode/decode

test vector:

- silence
- DC positive/negative
- impulse
- full-scale alternating
- 997 Hz sine
- MLS
- sample_count 0、1、47、48、49
- sequence 65534、65535、0、1
- malformed magic/version/CRC

同じcommon C/C++ sourceをPlatformIO native testから呼ぶ。Python reference modelとも同じvectorを比較する。

### 16.2 Layer B: accelerated clock simulation

sourceとtargetに独立したvirtual clockを与える。

| Relative drift | Test duration |
| ---: | ---: |
| -1000 ppm | 24時間相当 |
| -500 ppm | 24時間相当 |
| -100 ppm | 24時間相当 |
| 0 ppm | 24時間相当 |
| +100 ppm | 24時間相当 |
| +500 ppm | 24時間相当 |
| +1000 ppm | 24時間相当 |

jitter、1 frame loss、burst loss、duplicateもseed固定で注入する。

通常drift runの合格条件:

- prefill後のunderflow/overflowが0
- startupまたはfault recoveryから5秒以内にrolling 1秒平均fillが40から60 percentへ入る
- steady stateの瞬時fillが20から80 percent、rolling 1秒平均が35から65 percent以内
- controllerが発散しない
- output sample数がtarget SOF x 48に一致
- frequencyとgainが15.3節のthreshold以内

### 16.3 Layer C: build・descriptor audit

- python -m pytest
- pio test -e native
- pio run -e bluepill1
- pio run -e bluepill2
- warningを分類し、USB/PMA/DMA warningを0にする
- Flash/RAM sizeをJSON化する
- ELFからdescriptor array、ep_def、DEV_NUM_EPを抽出する
- wTotalLength、bNumInterfaces、alt settingを検査する
- endpoint番号、方向、type、max packet、intervalを検査する
- PMA重複、alignment、512 byte上限を検査する
- IAD first/count、AC collection、terminal entity参照、bTerminalLink、bDelay、bRefresh、bSynchAddress、class-specific endpointを検査する

source textにsymbolが存在するだけでは合格にしない。最終binaryへ期待値が入ったことを確認する。

### 16.4 Layer D: BP2 standalone microphone

BP2のtest tone modeを使用し、SPI入力なしでマイク経路を検証する。

1. BP2をflashする。
2. target agentがHID x3とcapture endpointを列挙する。
3. AUDIO_TEST_TONEで997 Hzを開始する。
4. 5秒録音する。
5. format、frequency、gain、gapを解析する。
6. HID Raw Inputも同時に確認する。

これによりSPIとBP1を切り離してBP2 USB Audio問題を診断できる。

### 16.5 Layer E: BP1 standalone speaker

SPIを接続しなくてもBP1 USB受信まで検査できるmodeを用意する。

1. controllerがBP1 render endpointを開く。
2. deterministic signalを再生する。
3. BP1 USB packet/byte/size counterを取得する。
4. CDCでheartbeat、HID control packetを並行送信する。
5. expected byte数とcounterを比較する。

ホスト側再生完了はBP1がpacketを受信した証拠であり、BP2またはtarget capture成功とは扱わない。

### 16.6 Layer F: SPI loop and fault test

- deterministic PCM frameをBP1からBP2へ送る。
- BP2のack sequence、CRC、ring inputを取得する。
- 1、1000、65536 frame境界を試験する。
- CRC破損、drop、duplicate、delayを注入する。
- SPI peripheral reset後に再armできることを確認する。

### 16.7 Layer G: one-PC HIL

開発PCへBP1とBP2の両USBを接続する。

1. build/flash
2. USB endpoint inventory
3. 一意なrun IDでRUN_START snapshot確立
4. BP1へ標準信号再生
5. BP2から同時録音
6. HID stress
7. RUN_END snapshot確立
8. audio analysisと同一run差分counter回収
9. JSONL result

one-PC HILは経路全体を検査できるが、2台の独立host clockを十分に証明しない。AUDIO_E2E_PASSではなくAUDIO_SINGLE_HOST_PASSとする。

### 16.8 Layer H: two-PC E2E

controller PCとtarget agent PCを分ける。

- 30秒smoke: AUDIO_E2E_SMOKE_PASS
- 5分bench: AUDIO_E2E_BENCH_PASS
- 60分release candidate: AUDIO_E2E_PASS profile=release duration_s=3600
- 6時間nightly soak: AUDIO_E2E_SOAK_PASS duration_s=21600

試験中は未使用キーのpress/release、各mouse interfaceの安全な閉路patternを送る。Raw Input受信数と送信tokenを照合し、stuck key/buttonがないことを確認する。一般アプリへの副作用を避けるため、専用test user/sessionで実行する。

timed windowではrender streamとcapture streamを最初から最後までopenし、10秒周期のsync markerを含む非0のdeterministic signalを連続再生する。window開始時に一意な`run_id`のRUN_STARTを発行し、BP1/BP2双方のsnapshot取得を待つ。終了時も同じ`run_id`のRUN_END snapshotを確立し、次をすべて同一論理境界間の差分で満たすことを要求する。

- BP1 usb_audio_alt=1、BP2 capture_alt=1で開始・終了し、usb_audio_alt_transitions=0、capture_alt_transitions=0、USB reset/suspend/resume delta=0である。
- BP1 usb_audio_packetsが3,600,000以上になるまでrelease windowを終了しない。
- BP1 `delta spi_pcm_frames`が`delta usb_audio_boundary`に一致し、BP2 `delta accepted_pcm_frames`がBP1 `delta spi_pcm_frames`に一致する。SESSION_START、RUN_START、RUN_END等はspi_control_framesとaccepted_control_framesで別に扱う。
- BP2 usb_mic_packetsが3,600,000以上になるまでrelease windowを終了しない。
- target capture sample数が172,800,000 sample以上である。
- 10秒ごとのmarkerをすべて検出し、marker間に説明不能なgap、duplicate、reopenがない。
- durationはcontroller wall clockだけでなく、各device counterとcaptured sample数からも3600秒以上と確認する。

独立clockのためwall clockに対するpacket数はppm差を持ち得る。runnerは固定wall timeだけで停止せず、controller側とtarget側の両方が上記最低countへ到達するまで継続する。

AUDIO_E2E_PASSは独立2 PCで連続60分以上を完了したrelease profileだけが出せる。30秒と5分の結果に同じmarkerを使用しない。

### 16.9 Layer I: reconnect・suspend

実行ケース:

| Case | 対象 | Enumeration deadline | Recovery deadline |
| --- | --- | ---: | ---: |
| render close/open | BP1 Audio OUT | 再列挙なし | command後5秒 |
| capture close/open | BP2 Audio IN | 再列挙なし | command後5秒 |
| software reset | BP1、BP2個別 | endpoint ACTIVEまで15秒 | ACTIVE後5秒 |
| BP1 reset + continuous HID burst | BP1 | endpoint ACTIVEまで15秒 | TX barrier 60 ms、HID queue drain 500 ms、Audio 5秒 |
| Windows disable/enable | BP1、BP2個別 | endpoint ACTIVEまで15秒 | ACTIVE後5秒 |
| ST-Link hardware reset | BP1、BP2個別 | endpoint ACTIVEまで15秒 | ACTIVE後5秒 |
| Windows sleep/resume | controller、target個別 | agent/endpoint復帰まで30秒 | ACTIVE後5秒 |
| programmable hub power cycle | BP1、BP2個別 | endpoint ACTIVEまで15秒 | ACTIVE後5秒 |

各caseで同じ手順を使う。

1. 全key/button releaseを送る。
2. case固有のpre-fault audio markerを2秒送って検出する。
3. fault専用`run_id`のRUN_START snapshot後にfaultを実行する。
4. device再列挙がある場合、古いPortAudio indexを再利用せず、serialまたはContainer IDからEndpoint IDと新indexを再解決する。
5. BP1 render側caseではsource_session_startsとsource_session_clearsの増加を確認する。BP1 resetを伴うcaseではAUDIO_CONTROL_SYNCの再成立と新しいboot stateの受理も確認するが、nonceの数値的不一致だけを合格条件にはしない。BP2 capture側caseではcapture_session_clearsを確認する。いずれもprefillから再開することを確認する。
6. case固有のpost-fault markerを含む標準信号を10秒連続送信・録音する。
7. post-fault区間でHID tokenを100件照合する。
8. signal metric、CRC、sequence、underflow/overflowをpost-fault windowだけで判定する。

合格条件:

- 上表のenumeration deadlineとrecovery deadline以内である。
- post-fault PCMにpre-fault markerまたはold session PCMが含まれない。
- post-fault 10秒で標準signal gateがpassする。
- HID token 100件が一致し、stuck key/buttonがない。
- 正しいUSB instance、Container ID、Endpoint IDへ再接続している。
- intentional reset/disconnect以外の追加resetまたはreopenがない。
- recovery後のnominal counterにCRC、sequence gap、underflow、overflowがない。
- BP1 reset + continuous HID burstでは、endpoint ACTIVE後10秒間、最大20 byte frameを400 packet/sで送る。固定60 ms barrierが入力によって延長されず、boot queue high-waterが32以下、overflowが0、500 ms以内にqueueが空となり、BP1が受理したHID tokenがすべて到達することを確認する。SYNC retry中もHIDを継続し、SYNC duplicateは`control_sync_duplicates`だけを増やして`source_session_clears`を再度増やさない。

programmable hubがない場合、release前に1回だけ人が物理抜き差しを行う。この項目を自動試験済みと誤記しない。

## 17. fault injection matrix

| Fault | Expected behavior | Gate |
| --- | --- | --- |
| SPI CRC error 1 frame | frame破棄、counter +1 | stale replayなし |
| SPI sequence gap | gap記録、音声継続 | 5秒以内にsteady state |
| SPI duplicate | duplicate破棄 | ringへ二重追加しない |
| SPI stall 2/5/20 ms | underflow時0出力 | deadlockなし |
| Source stop 100 ms/1 s | 0出力、prefill再開 | 古い音声を再生しない |
| Ring near full | ASRCが消費を増加 | overflowなし、clamp記録 |
| Ring forced overflow | oldest discard | 遅延が増え続けない |
| BP1 reset | target micは一時0 | BP1復帰後5秒以内 |
| BP1 reset中の400 packet/s CDC/HID burst | 60 ms barrier後にHIDをdrain、Audio SYNCは並行retry | queue 32以下、overflow 0、500 ms以内にdrain、受理token全一致 |
| AUDIO_CONTROL_SYNC ACK drop/duplicate | 同じtupleを再送、duplicateはACKのみ | source session再clearなし、5秒以内に復帰 |
| BP2 reset | HID/audio一時切断 | USB再列挙、stuck keyなし |
| Audio alt 0/1 toggle | buffer初期化 | 前session音声が混入しない |
| CDC burst during audio | HID/control継続 | audio error counter 0 |
| HID stress during audio | HID event全一致 | audio deadline miss 0 |

## 18. debug plan

### 18.1 最初に見る順序

1. Windows USB instanceとaudio endpointが存在するか。
2. BP1 usb_audio_packetsが増えるか。
3. BP1 spi_pcm_framesとBP2 accepted_pcm_frames、およびcontrol frame countersが一致するか。
4. BP2 CRC/sequence counterが0か。
5. BP2 ring fillがtarget付近へ収束するか。
6. BP2 usb_mic_packetsが増えるか。
7. target agentが正しいEndpoint IDを録音しているか。
8. waveform解析結果がcounterと一致するか。
9. audio中のHID tokenがすべてtargetへ到達したか。

### 18.2 症状別切り分け

| 症状 | 主な確認箇所 |
| --- | --- |
| BP1がCOMだけでAudioがない | device/config/IAD descriptor、Windows cache |
| BP1 Audioはあるがpacket 0 | controllerのEndpoint ID、alt setting、WASAPI format |
| BP1 packet有、SPI tx 0 | USB buffer ownership、scheduler、DMA init |
| SPI tx有、BP2 rx 0 | NSS/SCK/MOSI配線、slave DMA arm |
| CRC errorが連続 | SPI mode、clock、NSS timing、signal integrity |
| ring fillが一方向へ移動 | ASRC sign、PI gain、SOF count、step clamp |
| mic packet 0 | BP2 alt setting、EP84 open、DataIn callback |
| micは録音できるが音が壊れる | endian、sample_count、double buffer ownership |
| 1 ms周期のclick | packet loss、underflow、buffer swap race |
| audio中だけHID欠落 | ISR時間、interrupt priority、USB endpoint routing |
| resetを繰り返す | watchdog health、stack、DMA overrun、hard fault record |

### 18.3 hard fault情報

debug buildでは、可能な範囲で次をbackup registerまたはno-init RAMへ残す。

- reset reason
- last audio state
- last SPI sequence
- ring fill
- CFSR、HFSR、MMFAR、BFAR
- stack pointerとreturn PC

再起動後のGET_STATUSで前回fault recordを取得する。watchdog resetとUSB disconnectを区別する。

### 18.4 timing観測

logic analyzerを必須にはしないが、任意のdebug GPIOを用意できる設計にする。

- BP1 USB packet callback pulse
- BP1 SPI NSS transaction
- BP2 DMA complete pulse
- BP2 USB Audio IN preparation pulse
- deadline miss pulse

製品buildではdebug GPIOを無効化する。通常の自動試験はcounterとtimestampだけで判定する。

## 19. 自動runner

最終的な入口:

~~~powershell
.\tools\audio_test\run_audio_validation.ps1 `
  -Mode TwoPcE2E `
  -SoakMinutes 60 `
  -Flash `
  -EvidenceRoot logs\audio-validation
~~~

runner処理順:

1. prerequisite確認
2. Git revisionとdirty state記録
3. ST-Link serial、USB device、COM、audio endpoint inventory
4. pytest/native test
5. BP1/BP2 build
6. warning、size、descriptor、PMA audit
7. 必要時flash
8. USB再列挙待機
9. target agent handshake
10. nominal用`run_id`を生成し、RUN_STARTを発行して両deviceのstart snapshotを確認
11. nominal signalとHID regression後にRUN_ENDを発行し、同じ`run_id`のend snapshotを回収
12. soak用の別`run_id`でRUN_START/RUN_ENDを作成し、nominal soak差分を保存
13. fault injectionごとに別`run_id`を使い、注入期待値と同一marker間の実測deltaを保存
14. fault runをRUN_ENDで閉じる。後続runは新しい`run_id`とcumulative snapshot差分で分離する
15. counters、run snapshots、failure window回収
16. summary生成
17. PASS markerまたはAUDIO_FAILを表示

明示的marker:

~~~text
AUDIO_UNIT_PASS
AUDIO_BUILD_PASS
AUDIO_DESCRIPTOR_PASS
AUDIO_ENUM_PASS
AUDIO_SIGNAL_PASS
AUDIO_DRIFT_PASS
AUDIO_HID_REGRESSION_PASS
AUDIO_SINGLE_HOST_PASS
AUDIO_E2E_PASS profile=release duration_s=3600
AUDIO_E2E_SOAK_PASS duration_s=21600
~~~

失敗例:

~~~text
AUDIO_FAIL stage=spi metric=sequence_gap actual=3 limit=0
~~~

## 20. CI・bench・release運用

### 20.1 Pull Request CI

- pytest全体
- native audio unit test
- accelerated clock simulationの短縮版
- BP1/BP2 firmware build
- descriptor/PMA/size audit
- Windows app buildに対する回帰

hardwareがなくても失敗させられる項目を最大化する。

### 20.2 Nightly bench

- 物理BP1/BP2へのflash
- one-PC HIL 5分
- deterministic fault suite
- HID stress
- configured two-PC benchでは6時間soakを必須実行する。hardware offline時はSKIPPEDと記録し、release evidenceには数えない

nightly benchはself-hosted runnerで、ST-Link serialとUSB instanceを設定ファイルへ固定する。

### 20.3 Release candidate

- CI全項目pass
- two-PC E2E 60分pass
- nominal error counterすべて0
- reconnect suite pass
- 人による物理抜き差し1回pass、またはprogrammable hub power cycle pass
- VID/PID release decision完了
- setup、hardware、protocol文書更新
- target PCでHID x3とmicrophoneが同時に動作
- host PCでCDCとspeakerが同時に動作

## 21. Phase別実装順

### Phase 0: baseline固定

作業:

- 現在のpytest件数と結果を保存する。
- BP1/BP2 build、size、warningを保存する。
- 現行BP1 COMとBP2 HID x3のinstance情報を保存する。
- firmware build IDとGit SHAを出力できる最小基盤を追加する。
- legacy build profileを確認する。

Gate:

- 既存HID、CDC、app testがpassする。
- endpoint warningがない。
- dirtyな未関連差分を実装commitへ含めない。

### Phase 1: common audio coreとhardware-free test

作業:

- audio_format、frame、CRC、ring、ASRC、diagnostics schemaを実装する。
- nativeとPython reference testを追加する。
- ±1000 ppmのaccelerated simulationを通す。

Gate:

- hardware-free testがすべてpassする。
- 24時間相当simulationで通常underflow/overflowが0。
- common codeがArduino/USB globalへ依存しない。

### Phase 2: BP2 standalone UAC1 microphone

作業:

- HID x3 + Audio descriptorを実装する。
- EP84、DEV_NUM_EP=5、PMAを実装する。
- test tone sourceを実装する。
- target agentのcaptureと解析を実装する。

Gate:

- HID x3の既存testがpassする。
- Windowsでmicrophoneが列挙する。
- 997 Hz test toneを自動録音・判定できる。
- BP2 PMA auditがpassする。

### Phase 3: BP1 standalone CDC + UAC1 speaker

作業:

- CDC+Audio composite classを実装する。
- CDC endpointをEP02/EP82へまとめる。
- Audio OUT EP01 double bufferを実装する。
- host controllerのrenderとcounter確認を実装する。

Gate:

- COMとspeakerが同時列挙する。
- 既存CDC/HID controlが変わらない。
- 48 kHz mono再生でBP1 counterが期待値と一致する。
- PMA 488/512 budget auditがpassする。

### Phase 4: SPI DMA transport

作業:

- BP1 master、BP2 slave、fixed frame、MISO statusを実装する。
- sequence、CRC、deadline counterを実装する。
- fault injectionをtest buildへ追加する。

Gate:

- 60分のdeterministic SPI testでCRC/sequence errorが0。
- fault countが注入回数と一致する。
- HID traffic並行時もSPI deadline missが0。

### Phase 5: ASRC統合

作業:

- SPI producer、ring、ASRC、USB mic consumerを接続する。
- startup、underflow、overflow recoveryを実装する。
- MISOとUART diagnosticsを接続する。

Gate:

- one-PC full path signal testがpassする。
- injected drift testがpassする。
- ring fillが収束し、controller sign/gainが実測と一致する。

### Phase 6: two-PC automation

作業:

- target agent remote protocolとscheduled task設定を実装する。
- controller、evidence、HID Raw Input correlationを完成させる。
- reconnectとsoak modeを追加する。

Gate:

- 60分two-PC E2Eが人の操作なしで完了する。
- AUDIO_E2E_PASS profile=release duration_s=3600がtarget録音証跡を伴う。
- failure時にどの境界で止まったかsummaryから判断できる。

### Phase 7: release hardening

作業:

- VID/PID、serial、product stringを確定する。
- Windows cache migration手順を確定する。
- docs/hardware.md、docs/protocol.md、docs/setup.mdを更新する。
- feature flag、legacy recovery image、flash手順を整備する。
- long soakとphysical reconnectを実施する。

Gate:

- release checklistの全項目に証跡がある。
- 未検証項目をAUDIO_E2E_PASS profile=releaseへ含めない。

## 22. 推奨commit境界

1. test(audio): add native frame ring and ASRC specifications
2. feat(audio): add common SPI audio transport primitives
3. feat(firmware): add BP2 UAC1 mono microphone
4. test(audio): add Windows capture agent and signal analysis
5. feat(firmware): add BP1 CDC and UAC1 speaker composite
6. feat(firmware): add SPI DMA audio bridge
7. feat(audio): integrate ring servo and ASRC
8. test(audio): add one-host and two-host HIL runner
9. docs(audio): document wiring protocol setup and release gates

各commitでbuildと関連testがpassする状態を維持する。RED testはローカル作業中に先に作るが、commit時には最小実装と組み合わせてgreenにする。BP1とBP2のUSB descriptor変更を同一の巨大commitへまとめない。

## 23. 停止条件

以下のいずれかが発生した場合、次Phaseへ進まず原因を解消する。

- BP1 PMAが512 byteを超える、または領域が重複する。
- BP2の既存HID interface、endpoint番号、report長が意図せず変化する。
- USB descriptorのwTotalLengthまたはbNumInterfacesが生成物と一致しない。
- firmware buildにUSB/PMA/DMA関連warningが残る。
- nominal testでCRC、sequence gap、underflow、overflowが1回でも発生する。
- ASRC controllerがnominal実機でclampへ張り付く。
- audio traffic開始後にHID event lossまたはstuck reportが発生する。
- target agentが期待するBP2 Endpoint ID以外を録音している。
- host再生進捗だけを根拠にE2E成功と判定している。
- watchdog reset、hard fault、USB再列挙loopが発生する。
- failure logからBP1、SPI、BP2、target captureのどこで停止したか区別できない。

## 24. resource budget gate

調査時点の既存buildはFlash/RAMに余裕があるが、Audio追加では静的bufferが増える。release buildの初期上限を次とする。

| Resource | Gate |
| --- | ---: |
| BP1 Flash | 56 KiB以下 |
| BP2 Flash | 56 KiB以下 |
| BP1 static RAM | 16 KiB以下 |
| BP2 static RAM | 16 KiB以下 |
| BP1 boot HID queue | 768 byte固定、24 byte x 32 slot |
| runtime stack reserve | stress時high-water測定で4 KiB以上 |
| BP1 PMA | 512 byte以下、計画値488 |
| BP2 PMA | 512 byte以下、計画値384 |

BluePill F103C8の20 KiB RAMに対して4 KiB以上をstack、framework、unexpected peak用に残す。map fileの.bss、.dataだけでは証明とせず、専用bench buildで未使用RAMへpatternを置き、USB Audio、SPI DMA、HID stress後のstack high-waterを測定する。

## 25. risk register

| Risk | 影響 | 対策 |
| --- | --- | --- |
| BP1 PMA余裕24 byte | 列挙不能、memory overlap | single CDC OUT、ELF/PMA audit |
| STM32duinoにAudio classなし | class driver工数増 | 最小UAC1、既存API互換patch、Phase分離 |
| 2つのUSB clock差 | 長時間drop | ring + PI ASRC、two-PC soak |
| SPI slave DMA race | CRC/gap | fixed frame、NSS、ping-pong、counter |
| Windows descriptor cache | 古いinterface表示 | variant、instance inventory、移行手順 |
| 他社VID/PID | driver/filter・配布問題 | release gateで正規identity決定 |
| Audio ISRがHIDを阻害 | stuck key/mouse | DMA、短いISR、HID stress gate |
| linear ASRC音質 | 高域劣化 | mono KVM用途で測定、必要時のみFIRを将来Phase化 |
| test toolが誤endpointを開く | false pass | Endpoint ID、Container ID、VID/PID照合 |
| 長時間WAV肥大化 | disk消費 | rolling failure window、online metric |
| USB power/ground loop | 不安定・ノイズ | 5 V非接続、短配線、必要時絶縁を別設計 |

## 26. 人手を最小化した運用

初回だけ必要:

1. SPI4信号とGNDを配線する。
2. BP1/BP2のST-Link serialを設定へ登録する。
3. BP1 render、BP2 captureのUSB instanceを確認して保存する。
4. target agentをscheduled taskへ登録し、tokenを交換する。
5. programmable hubがない場合、最終releaseで物理抜き差しする。

通常runでは不要:

- COM番号選択
- Windows default speaker/microphone変更
- 手動録音開始
- WAVを耳で判定
- counterの目視比較
- flash後の手動待機
- 長時間試験中の監視

聴感確認は補助試験であり、機械判定を置き換えない。

## 27. 最終受入状態

状態は次の順に進め、飛び越えない。

1. Proposed: 本計画のみ。
2. Implemented: sourceが存在する。
3. Unit tested: hardware-free testがpassする。
4. Built: BP1/BP2 firmwareがwarningなしで生成される。
5. Flashed: 対象boardとbuild IDが一致する。
6. Enumerated: BP1 CDC+speaker、BP2 HID x3+microphoneを確認する。
7. Signal verified: target録音解析がpassする。
8. HID regression verified: audio並行時のHID E2Eがpassする。
9. Soak verified: 独立2 PCのrelease profileで60分以上passする。
10. Release ready: reconnect、identity、文書、recoveryまで完了する。

最終AUDIO_E2E_PASS profile=release、duration_s 3600以上の必要条件:

- 正しいBP1 render endpointへ出力した証跡
- BP1 USB receive counter
- BP1/BP2 SPI sequenceとCRC counter
- BP2 ring/ASRC counter
- usb_audio_alt_transitions=0、capture_alt_transitions=0とUSB reset/suspend/resume delta=0
- 共通RUN_START/RUN_END間の`usb_audio_boundary`、`spi_pcm_frames`、`accepted_pcm_frames`差分が一致する証跡
- `usb_mic_packets`差分とcaptured sample数がduration gateを満たす証跡
- 正しいBP2 capture endpointから得たPCM
- waveform metric pass
- HID token E2E pass
- firmware build IDとUSB instance情報

## 28. 関連文書の更新予定

実装Phaseで次を更新する。

- docs/hardware.md: SPI配線、電源注意、optional resistor
- docs/protocol.md: diagnostics command、status page、SPI frame
- docs/setup.md: Windows speaker/microphone、cache、target agent
- README.md: 対応機能と制約
- THIRD_PARTY_NOTICES.md: 追加libraryまたはST codeを借用した場合
- pyproject.toml: audio-test optional dependencies
- platformio.ini: native、audio、legacy environment
- .github/workflows: pytest、firmware build、descriptor audit

## 29. 参考資料

- USB-IF, USB Device Class Definition for Audio Devices Release 1.0: https://www.usb.org/sites/default/files/audio10.pdf
- USB-IF, Audio Data Formats Release 1.0: https://www.usb.org/documents?search=Audio+1.0
- Microsoft, USB Audio Class System Driver: https://learn.microsoft.com/en-us/windows-hardware/drivers/audio/usb-audio-class-system-driver--usbaudio-sys-
- Microsoft, USB device class drivers included in Windows: https://learn.microsoft.com/en-gb/windows-hardware/drivers/usbcon/supported-usb-classes
- Microsoft, USB Interface Association Descriptor: https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/usb-interface-association-descriptor
- Microsoft, IMMDeviceEnumerator::EnumAudioEndpoints: https://learn.microsoft.com/en-us/windows/win32/api/mmdeviceapi/nf-mmdeviceapi-immdeviceenumerator-enumaudioendpoints
- STMicroelectronics, STM32F101/102/103/105/107 reference manual RM0008: https://www.st.com/resource/en/reference_manual/cd00171190.pdf
- PlatformIO, Unit Testing: https://docs.platformio.org/en/latest/advanced/unit-testing/index.html
- PlatformIO, Test Runner: https://docs.platformio.org/en/latest/advanced/unit-testing/runner.html

## 30. 実装開始時の最初のチェックリスト

- [ ] 作業用feature branchをisolated worktreeへcheckoutする。
- [ ] main 24e04bf以降の変更を確認し、本書のbaselineを更新する。
- [ ] pytestとBP1/BP2 buildのbaseline証跡を保存する。
- [ ] 現行framework USBDevice versionを固定する。
- [ ] legacy firmware imageを保存する。
- [ ] BP1 PMA allocation testを先に作る。
- [ ] BP2 descriptor testを先に作る。
- [ ] common audio testをREDにしてから実装する。
- [ ] Audioなしprofileを常にbuildする。
- [ ] USB identityの開発variantを決める。
- [ ] ST-LinkとUSB instanceをinventoryへ記録する。
- [ ] Phase 1 gateを満たすまでUSB descriptorを変更しない。
