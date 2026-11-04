# DisplayHDR 遠端控制 API

## 執行 DisplayHDR 的電腦

使用 Host ZIP 整合包時，不需要額外安裝 Python；解壓後的入口會使用包內 runtime。部署與操作見 [可攜式整合包](Portable_Packages.md)。以下 `python` 指令可改用包內 `runtime\python.exe -X utf8`。

從原始碼啟動服務的開發端需安裝 Python 3；使用整合包不需另裝。正式 C++ 程式的編譯器及執行檔沒有因 HTTP 介面改變；Python 服務負責將網路指令轉送至既有 Named Pipe。

在解壓縮後的 Host 整合包資料夾中雙擊 `StartDisplayHDR.cmd`。這個入口自動啟動 DisplayHDR（`--api`）及 HTTP 服務，顯示 `READY` 後可接受控制。預設連接埠為 **8765**，監聽本機全部 IPv4 介面。

需指定監聽的區域網路 IP 或連接埠時，在該目錄執行：

```powershell
.\StartDisplayHDR.cmd --host 192.168.1.107 --port 8765
```

`192.168.1.107` 是範例位址；部署時以執行 DisplayHDR 的電腦實際 IP 為準，可用 `ipconfig` 查詢。`0.0.0.0` 是監聽位址，不是控制端的連線位址。

執行檔、`.cso`、`.png` 資源與完整 Python 服務模組保留在同一目錄，包括：

- `StartDisplayHDR.cmd`
- `displayhdr_server.py`
- `displayhdr_api.py`
- `displayhdr_supervisor.py`
- `displayhdr_ports.py`
- `displayhdr_display_paths.py`
- `displayhdr_hdr_control.py`
- `displayhdr_monitor_input.py`
- `displayhdr_window_presentation.py`

Windows 防火牆須允許控制端連入所選 TCP 連接埠。啟動工具不會自動修改防火牆。依確認需求，本版不提供身分驗證或 HTTPS。

關閉 DisplayHDR 視窗後，HTTP 服務保持運行，可透過 `restart_host` 要求重啟。服務停止不主動終止 DisplayHDR 或變更其測試狀態；可用以下方式重新連接仍在執行的 `--api` 實例：

```powershell
python displayhdr_server.py --pid 12345 --host 192.168.1.107 --port 8765
```

`--pid` 模式不擁有 DisplayHDR 程序，服務需自行停止。連接埠已使用或找不到執行檔時，入口會回報錯誤並退出；連接埠錯誤會在啟動 DisplayHDR 前檢查。DisplayHDR 啟動或 Named Pipe 就緒檢查失敗時，HTTP 服務保持運行，文字視窗顯示 `SERVICE ... status=failed`，不顯示 `READY`；用 `get_host_status` 取得原因，受監管模式可明確要求 `restart_host`。

## 從另一台 Windows 電腦控制

兩台電腦需在同一個區域網路。控制端可使用 Windows 內建的 PowerShell 呼叫 API，不需安裝本專案以外的控制程式。下列範例中的 IP 請改成 Host 電腦的實際位址。

```powershell
$displayHdrEndpoint = 'http://192.168.1.107:8765/api'

# 查詢目前的測試與設定
$displayHdrRequest = @{version = 1; id = 'state-001'; command = 'get_state'}
Invoke-RestMethod -Uri $displayHdrEndpoint -Method Post -ContentType 'application/json' -Body ($displayHdrRequest | ConvertTo-Json)

# 顯示全畫面藍色，隱藏說明文字
$displayHdrRequest = @{version = 1; id = 'blue-001'; command = 'set_state'; test = 'ColorPatchesFull'; settings = @{color = 'Blue'; textVisible = $false}}
Invoke-RestMethod -Uri $displayHdrEndpoint -Method Post -ContentType 'application/json' -Body ($displayHdrRequest | ConvertTo-Json -Depth 5)

# 重啟 Host 的測試程式
$displayHdrRequest = @{version = 1; id = 'restart-001'; command = 'restart_host'}
Invoke-RestMethod -Uri $displayHdrEndpoint -Method Post -ContentType 'application/json' -Body ($displayHdrRequest | ConvertTo-Json)
```

回覆中的 `ok` 為 true 才代表請求成功。設定後請呼叫 `get_state`，核對 `lastSetRequestId`、測試、設定及畫面提交狀態；量測前也需依測試的倒數條件等待。重啟請求只代表已接受，需繼續查詢程序與測試狀態，確認程式已就緒。

API 沒有登入或需要維持的工作階段。單一控制端依序送出指令；不實作多控制端協調。

## HTTP 契約

**`POST /api`**，`Content-Type: application/json`，提供單一 `Content-Length`。UTF-8 JSON 物件，最大 16 KiB；不支援 chunked 請求。正文使用既有 `version`、`id`、`command`、`test`、`settings`、`restart`，不需要 Named Pipe 的行尾換行。

```json
{"version":1,"id":"state-001","command":"get_state"}
```

| HTTP 狀態 | 意義 |
| --- | --- |
| 200 | 已收到 DisplayHDR 回覆；仍須檢查 JSON 的 `ok`，設定驗證失敗也可能為 200 |
| 400 | JSON、正文型別或格式錯誤 |
| 404／405 | 路由或方法不支援 |
| 408 | 正文未在 5 秒內送完，未轉送至 DisplayHDR |
| 411／413／415 | 缺少單一 Content-Length、訊息大小不符、Content-Type 不符 |
| 502 | 本機通訊中斷／不可用 |
| 503 | Host 程式尚未就緒，未轉送操作 |
| 504 | 本機連線或指令處理逾時 |

網路服務錯誤沿用 `version`、`id`、`ok:false`、`error`，另包含 `error.requestMayHaveApplied`。502／504 的設定指令會保守標示 `true`，表示必須查詢確認，不代表確實已套用。無法解析請求識別值時 `id` 為空字串。

HTTP 請求行與標頭的接收期限合計 5 秒，正文另有 5 秒接收期限；持續零星傳送資料不會延長期限。請求行或標頭逾時會關閉連線，不轉送命令；正文逾時回覆 408。Named Pipe 連接與每次指令等待各最多 5 秒。控制端需自行設定 HTTP 請求的逾時時間。HTTP 回覆後關閉連線；網路服務依序處理請求，不會阻塞 DisplayHDR 的渲染執行緒。

原版操作的 JSON 請求範例：`{"version":1,"id":"key-001","command":"key","key":"Shift+Up"}`。`key` 與 `set_state` 都是修改指令，502／504 可能已生效，服務不重送；傳輸正文另允許 `key` 欄位。

完整測試識別值、25 個持續設定、狀態快照與暖機／倒數語意見 [既有 API 契約](Automation_API.md)。HTTP 層保留回覆內容，不重新計算圖樣或 Nits。

## 斷線與重連

- 斷線不自動暫停、重啟、切換圖樣或還原設定；原有動畫與倒數照原程式繼續。
- 正文未完整送達時，不轉送任何設定。
- 完整請求送達後，即使控制端沒有收到回覆，設定仍可能完成。
- 網路服務及客戶端都不自動重送失敗指令。重連後先呼叫 `get_state`，核對 `lastSetRequestId`、圖樣及完整設定，再決定是否重送。
- `lastSetRequestId` 是最近一次設定請求，不是歷史指令清單；鍵盤介入或自動變化仍須用目前狀態確認。

## 驗證範圍

同機 HTTP／真實 Named Pipe 的契約測試，以及正式執行檔的 HTTP 測試均已執行。2026-10-07／08 的設備整合紀錄亦確認另一台電腦可透過區域網路控制測試畫面並讀回狀態；此為當時環境的實際連線證據，不代表完整網路故障或各種防火牆部署情境已驗收。部署至新環境時，仍須從另一台電腦確認連線；同機呼叫主機區域網路 IP 不能證明另一台電腦可穿過主機防火牆。

本版只提供控制與狀態查詢，不提供遠端畫面串流或量測設備驅動。

## Host 程式重啟與程序狀態

新版 Host HTTP 服務持續運作，負責監管它啟動的 DisplayHDR 程式。關閉或崩潰不會自動重啟；控制端可透過 API 明確要求重啟。此功能不重啟 Windows，也不能重啟已停止的 HTTP 服務。

```json
{"version":1,"id":"status-1","command":"get_host_status"}
{"version":1,"id":"restart-1","command":"restart_host"}
```

成功回覆包含 `host`，沒有測試 `state`：

```json
{"version":1,"id":"status-1","ok":true,"host":{"status":"ready","pid":1234,"restartSupported":true,"error":""}}
```

- `status`：`starting`（等待啟動）、`restarting`（關閉舊程序）、`ready`、`stopped`（正常結束）、`failed`（啟動失敗或異常結束）。
- `pid`：目前或最近一次啟動的程序識別值；尚未成功啟動時可為 null。`error` 提供失敗原因。
- `restart_host` 非同步執行，成功回覆只表示已接受；必須查詢到 `ready` 並成功取得 `get_state`，才能確認恢復控制。
- `restart_host` 只重啟受管理的 renderer，回報新程序啟動狀態，不置頂、檢查遮擋或恢復畫面。呼叫端決定是否另送視窗呈現指令。
- 重啟先正常關閉服務啟動的程序；等待 5 秒仍未退出時終止該程序，再啟動相同執行檔與 `--api`。不關閉其他 DisplayHDR 程序。
- 程式尚未 ready 時，圖樣操作／查詢回覆 HTTP 503、`host_unavailable`，不轉送操作。狀態查詢仍可用。
- 兩個新指令只接受 version、id、command；額外欄位、重複重啟及附掛模式的重啟要求回覆 400。`--pid` 附掛模式的 `restartSupported` 為 false；附掛程序結束後仍會更新程序狀態，但不會關閉或重啟附掛程序。
- 重啟會重新初始化程式，原有測試、設定與倒數不保留，也不重播先前控制指令。
- 請求送達後即使回覆遺失，重啟可能已開始；不要自動重送，先查詢程序狀態。
- 同一次 HTTP 服務執行期間，已嘗試的 `restart_host` 請求 id 再次送達時回覆 400，不再次重啟，包含前次已完成或失敗的情況。確定需要另一次重啟時使用新 id；服務重新啟動後不保留此紀錄。
- 本功能需要支援 `restart_host` 的 Host 整合包。

查詢程序狀態時，使用 `get_host_status`；重新啟動測試程式時，使用 `restart_host`。
## 本機顯示操作 API

HTTP bridge 的 `POST /api` 提供獨立操作，不改動官方圖樣、計時或量測規則；DDC/CI使用Windows原生VCP 0x60，不需外部控制工具。`get_host_status` 回報 `displayPortControl: true`、`portPrimitives: true` 能力。

`get_display_ports` 唯讀盤點端點、EDID雜湊、Windows唯一啟用輸出與當次DDC/CI值，回覆 `displayPorts`。端點包含 `targetKey`、`monitorDevicePath`、`name`、`connection`、`internal`、`active`、`available`、`edidHash`；adapter LUID可能在重開機後改變，不能當永久識別。顯示器輸入名稱與數值的對應由呼叫端配對，不推定26必為USB-C。缺少可靠EDID、同型號裝置或交換線材時，仍可能需要人工核對。

唯一啟用輸出為內建面板（`internal=true`，依 Windows LVDS、embedded DisplayPort、embedded UDI、Internal connector technology 判定）時，盤點不查詢 DDC/CI，`input.intentionallySkipped=true`；`supported`、`manualSupported`、`outputSelectionSupported` 均為 false，呼叫端應停用輸入配對與切換。盤點仍回傳端點資料，以便辨識裝置變更。

`outputSelectionSupported` 表示目前有可驗證的啟用輸出、可用端點及相符的 Windows 已儲存配置，且 Host 可由啟動器管理；多輸出時也可為 true，僅允許先選定唯一輸出，不代表已可確認來源。`manualSupported` 仍只表示Windows單一路徑、儲存配置及可重啟Host符合操作條件，不表示DDC/CI可用或面板來源已確認。有效DDC回覆若不符合目前Windows裝置身分會回報錯誤；暫時無法讀取不代表可以猜測來源。Host不建立Input狀態檔或鎖定檔，不自動還原或復用舊備份；`pendingRestore` 固定false，只供格式相容。

輸出控制由呼叫端負責順序與就緒策略。`get_display_ports` 接受可選 `switchMode: pair/active/passive`；Passive 不讀寫 DDC/CI，其餘只讀取當次來源，不等待穩定。`get_display_port_status` 回傳快取。回覆 `controlOwner: client` 表示支援以下獨立操作。`operation` 保留空的 idle 結構供格式相容，不表示測試就緒。

### 獨立本機操作

所有操作必填 `version: 1`、非空 `id`、`command`、`allowInterrupt: true`、`targetKey` 與 `monitorDevicePath`。

| command | 額外欄位 | 本機行為 |
| --- | --- | --- |
| `set_display_output` | 無 | 儲存及啟用指定單一 Windows 輸出；回報 `changed`，不重啟 renderer、不改測試畫面。 |
| `write_display_input` | `value`，整數1–255 | 對指定的目前啟用輸出送一次 VCP 0x60 寫入；回報 `accepted`，不切 Windows 配置、不等待來源穩定。 |
| `enable_display_hdr` | 無 | 啟用目前指定輸出的 Windows HDR，回報 `changed`；不重啟 renderer、不改畫面或視窗。 |
| `present_display_window` | 無 | 將目前 renderer 帶到前景及置頂並嘗試取得鍵盤焦點，回報 `unobstructed`、`topmost`、`foreground`、`keyboardFocused` 布林值；呼叫端須全部核對為 true。`unobstructed` 只表示幾何遮擋結果，不代表取得鍵盤焦點。不切畫面或更動 HDR。 |

回覆為 `{"version":1,"id":"...","ok":true,"action":{"command":"...","targetKey":"...","monitorDevicePath":"...",...}}`。只有 set_display_output 可指定未啟用但已連接的輸出；其他操作必須符合目前唯一啟用輸出身分。所有操作驗證 Windows 已儲存配置與實際配置一致。`set_display_output` 可從多啟用輸出收斂為指定的唯一輸出，即使目標已是多個啟用輸出之一，也會套用單一路徑並回報 `changed:true`。零啟用輸出、未受啟動器管理、配置不符或身分不符時拒絕選取；其餘操作仍拒絕多啟用輸出。欄位錯誤或同時操作仍會被拒絕。

Host 保留本機互斥、底層有界逾時與同一請求 id 不重複執行保護；未知結果或失敗不自動重送、不補償、不自動還原輸出。同 id 不可改變內容。這些保護僅涵蓋單次本機指令；呼叫端須阻擋量測期間的操作，並在多步驟間重新核對身分與結果。

防重複紀錄只保留變更操作；唯讀 `get_display_controls`、`get_display_edid`、`read_display_input` 每次重新讀取，不累積請求或回覆快取。唯讀請求仍不可借用既有變更操作的 id。

### EDID 原始資料查詢

`get_display_edid` 是唯讀查詢，只接受 `version:1`、非空 `id`、`command`、`targetKey`、`monitorDevicePath`，不接受 `allowInterrupt`。指定身分須符合目前唯一啟用的 Windows 輸出，讀取前後均核對；不改顯示配置、HDR、視窗或 DDC/CI 來源。

```json
{"version":1,"id":"edid-1","command":"get_display_edid","targetKey":"adapter/target","monitorDevicePath":"device path"}
```

成功回覆為 `{"version":1,"id":"edid-1","ok":true,"edid":{...}}`。`edid` 包含 `targetKey`、`monitorDevicePath`、`dataBase64`（原始 bytes 的 Base64）、`source`（`wmi`、`registry` 或 `unavailable`）、`byteLength`、`expectedLength`（無基礎區塊時為 null）、`complete`、`checksumsValid`、`warnings`（字串陣列）。`complete` 僅表示資料長度等於宣告的 `(extension count + 1) × 128`；第一個 CTA 延伸區塊（revision ≥ 3）的第一個 data block 若為有效、非零的 HF-EEODB（extended tag `0x78`），優先使用其延伸數，否則使用基礎區塊的延伸數。讀取與登錄備援的完整性判斷採相同規則；標頭或 checksum 錯誤另列警告，不修補資料。

優先透過 Windows `WmiMonitorDescriptorMethods.WmiGetMonitorRawEEdidV1Block` 從區塊 0 逐一探測，最多讀取 256 個區塊（0–255，共 32768 bytes）；宣告長度僅用於檢查，不作為停止條件。方法失敗、失敗狀態或未初始化的 `BlockType:0` 表示當次無法再提供區塊；若尚未取得宣告長度則另列停止原因，已達宣告長度後的上述停止不額外視為錯誤。未知 block type 或非 128-byte 資料仍警告並停止；不跳過失敗區塊、不重送讀取。固定 PowerShell worker 上限 8 秒，逾時或達到 256 區塊上限時警告並保留已取得的連續區塊。超過宣告的資料照實保存、回報長度不符，不裁切、不因內容重複或全零而丟棄；`complete` 仍只表示長度符合宣告，不代表已證明實體資料結尾。

少於宣告長度時可選用同一端點較長的登錄 EDID，回報 `source:registry` 及快取來源警告，不與 WMI 區塊拼接；登錄資料須完整保留已讀到的全部 WMI bytes 作為前綴才可替代。已達或超過宣告長度的 WMI 資料不由登錄資料替代。Windows 驅動提供的 EDID 可能包含快取或 override，不宣稱為直接向面板 EEPROM 即時讀取，也不代表顯示卡底層 DDC／AUX 交易紀錄。

WMI 方法的回傳值依實際型別處理：布林 `True` 成功、`False` 失敗；整數保留 `0` 成功、非零失敗的相容性。空值或字串不視為成功，每一區塊仍須包含128 bytes，再核對完整長度與checksum；不因回傳成功而略過資料驗證。

缺少區塊、checksum 錯誤或無法讀取均回覆 `ok:true`，保留實際原始內容並列出原因，由呼叫端顯示警告及決定測試策略。身分不符、讀取期間輸出改變、欄位錯誤或本機操作忙碌仍拒絕。資料保存與跨 Input 排程由呼叫端負責。

診斷欄位 `readElapsedMs` 是本次讀取含備援與檢查的總耗時（毫秒）；`readTrace` 是最多 260 筆、不含原始 EDID 內容的事件。每筆包含 `stage`（`wmi`／`registry`）、`result`（`read`／`end`／`error`／`timeout`／`limit`／`used`／`skipped`）及非負的 `elapsedMs`，依事件另含 `block`（0–256）、`byteLength`、`blockType`、`reason`（最多1024字元）。WMI 成功區塊的耗時由各次 CIM 呼叫計時；逾時／異常退出事件的耗時是整個 worker 經過時間。即使長度已符合宣告且沒有警告，也保留下一區塊的停止位置與原因；登錄備援是否使用、跳過或失敗亦記錄。診斷可由呼叫端與請求 id 關聯後保存；舊版 Host 未含這兩個欄位時，呼叫端可維持原有讀取功能。

原廠依據：[WmiGetMonitorRawEEdidV1Block](https://learn.microsoft.com/en-us/windows/win32/wmicoreprov/wmigetmonitorraweedidv1block-wmimonitordescriptormethods)、[Windows EDID 格式與 override](https://learn.microsoft.com/en-us/windows-hardware/drivers/display/overriding-monitor-edids)。

### Other 顯示控制

以下操作不需要 Input 配對，但都要求目前唯一啟用且身分可核對的輸出，不切換 Input、不修改 Windows 輸出配置、不控制圖樣或重啟 renderer。`get_display_controls` 是唯讀查詢，只接受 `version:1`、非空 `id`、`command`，回覆 `displayControls`：

- `target`：`targetKey`、`monitorDevicePath`、`name`、`connection`、`internal`、`technology`（Windows connector technology 整數，11 表示 eDP）。內建識別依 Windows connector technology：LVDS、embedded DisplayPort、embedded UDI、Internal。
- `hdr`：`supported`、`enabled`（true／false／null）、`error`。狀態直接讀 Windows；舊 advanced-color 介面無法區分 HDR／WCG 時回覆 null 並停用此工具的 HDR 控制，不把 advanced color 當成 HDR。
- `brightness`：`supported`、`writable`、`method`（`windows`／`ddc`）、`minimum`、`maximum`、`current`、`percent`、`levels`、`error`。不可用值為 null，層級為空陣列；值表示設定比例，不是實測 cd/m²。讀取能力失敗保留錯誤，不假造成功或亮度值。

`set_display_hdr` 接受共同欄位加 `allowInterrupt:true`、`targetKey`、`monitorDevicePath`、`enabled`（boolean）；`set_display_brightness` 以 `percent`（0–100 的整數）取代 enabled。兩者回覆 `action`，包含 `command`、目標身分、`changed` 及操作後的 `displayControls`。相同設定不重寫；寫入後讀回不符即報錯，不重送。同 id 的成功回覆可重取，但不得改內容；失敗／未知結果的同 id 不重新執行。

內建亮度使用 `WmiMonitorBrightness` 與 `WmiMonitorBrightnessMethods.WmiSetBrightness`，只操作與目前 monitorDevicePath 精確對應的 active WMI instance，套用最接近的支援 level，再讀回確認。外接亮度使用 `GetMonitorCapabilities` 的 MC_CAPS_BRIGHTNESS、`GetMonitorBrightness`／`SetMonitorBrightness`，邏輯及實體 monitor 都須唯一；0–100% 對應實際 min/max 範圍，單次寫入後核對實際值。外接輸出的 Windows HDR 開啟或狀態未知時，不讀寫 DDC/CI 亮度，顯示限制原因；內建依其 Windows 亮度能力處理。

外接亮度的能力查詢或首次亮度讀取若回覆 `ERROR_GRAPHICS_MCA_INVALID_CAPABILITIES_STRING`（0xC0262587），可改用低階 `GetVCPFeatureAndVCPFeatureReply` 唯讀查詢亮度 VCP 0x10。能力查詢另接受 `0xC0262589`／`0xC026258A`（DDC/CI command／length 錯誤）；能力查詢及首次高階亮度讀取遇 `0xC02625D9`–`0xC02625DC`（MCCS／VCP 版本或宣告不相容）也可進入唯讀 VCP 備援。能力查詢成功但缺少高階亮度旗標時，仍以 VCP 0x10 實際回覆判斷。權限／裝置身分等其他錯誤不放寬。只有設定型控制及有效的目前值／最大值才可用，以0至回覆最大值映射百分比；使用者明確調整時才單次 `SetVCPFeature`，並用同一路徑核對讀值及範圍。其他錯誤、VCP 不支援或無效回覆仍失敗，不以寫入測試能力；寫入開始後不再換路徑重送。HDR、裝置身分及逾時保護不變。[低階讀取](https://learn.microsoft.com/en-us/windows/win32/api/lowlevelmonitorconfigurationapi/nf-lowlevelmonitorconfigurationapi-getvcpfeatureandvcpfeaturereply)、[低階寫入](https://learn.microsoft.com/en-us/windows/win32/api/lowlevelmonitorconfigurationapi/nf-lowlevelmonitorconfigurationapi-setvcpfeature)、[Microsoft 亮度 VCP 說明](https://github.com/microsoft/PowerToys/blob/main/doc/devdocs/modules/powerdisplay/design.md)。

`brightness.ddcMethod` 可回報 `high-level`／`vcp`／`windows`。成功確認同一 `targetKey`／`monitorDevicePath` 的外接 SDR 亮度需使用 VCP 時，Host 服務只記住此讀取方式，不快取亮度值；後續 Refresh、HDR 切換及 Apply 可省略已知失敗的能力查詢。worker 每次先核對目前唯一啟用輸出與提示身分完全相同，才直接讀取 VCP 0x10，仍驗證控制類型、範圍、目前值及 HDR 狀態；寫入一次後仍讀回確認。這是 Host 內部提示，遠端 API 不接受指定。HDR 開啟時不查外接亮度，但保留同一裝置的方法提示；關閉後重新讀取真實值。

已知 VCP 路徑的唯讀查詢回覆 `0xC0262589`／`0xC026258A`（command／length 格式錯誤）時，可保留同一裝置的方法提示供呼叫端有限重查；回覆仍是亮度不可用、`writable:false`，不使用先前數值、不自動寫入。未知 HDR、輸入／輸出配置操作、身分改變、其他讀取失敗或任何寫入失敗會清除提示；失敗當次不改用其他介面重送。

`displayControls` 另含 `controlElapsedMs`（包含 worker 的總毫秒數）與 `controlTrace`（最多64筆分段事件，`stage`、`result:ok/error/skipped`、`elapsedMs`，必要時 `reason`）。階段包含 endpoint／HDR 核對、外接能力查詢／首次讀取／寫入／確認，內建則以 `windows-brightness` 記錄 WMI 操作耗時。`worker` 是整個子程序的經過時間，與內部分段重疊，不應加總；能力查詢略過會明確記錄 skipped。控制失敗時，HTTP 錯誤的 `error` 物件也保留這兩個診斷欄位及原有 `requestMayHaveApplied`；worker 逾時只能提供整體耗時，不假造尚未回傳的內部分段。診斷不包含原始 EDID 或量測內容，可由呼叫端以原請求 id 保存。

整個原生控制在固定參數子程序內執行，上限10秒；WMI worker另有4秒上限、HDR讀回最多5秒，逾時不重送。寫入前後核對 targetKey／monitorDevicePath，配置變化不回報成功。Host 保留本機互斥及請求防重複；呼叫端仍須在量測、配對、來源切換期間停用 Other 控制。舊 `enable_display_hdr` 的 Automation 行為與回覆契約不變。

原廠依據：[Windows connector types](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ne-wingdi-displayconfig_video_output_technology)、[WmiSetBrightness](https://learn.microsoft.com/en-us/windows/win32/wmicoreprov/wmisetbrightness-method-in-class-wmimonitorbrightnessmethods)、[GetMonitorBrightness](https://learn.microsoft.com/en-us/windows/win32/api/highlevelmonitorconfigurationapi/nf-highlevelmonitorconfigurationapi-getmonitorbrightness)、[SetMonitorBrightness](https://learn.microsoft.com/en-us/windows/win32/api/highlevelmonitorconfigurationapi/nf-highlevelmonitorconfigurationapi-setmonitorbrightness)。

### 呼叫端流程責任

- 配對：呼叫端指定起始畫面、選擇 Windows 輸出、必要重啟、輪詢來源及命名。Host 不追加畫面指令。
- Active：呼叫端先寫 DDC/CI，再選輸出，依 `changed` 決定是否重啟，輪詢 Windows 配置與 DDC/CI 來源，要求連續穩定至少10秒。
- Passive：呼叫端選輸出、必要重啟後管理1–60秒倒數；不得宣稱實際來源已經自動確認。
- 測試前：呼叫端啟用 HDR，依 `changed` 決定是否重啟，再明確設定全螢幕及說明文字、要求視窗置頂／遮擋檢查，全部符合後才開始量測。不保存或還原先前測試畫面。
- Restart：Host 只處理程序；呼叫端決定後續視窗處理。

整套工作流程 API `switch_display_port` 與 `prepare_display_test` 已移除，舊呼叫會被拒絕，需同步更新呼叫端。Windows HDR 啟用與 renderer 啟動的本機確認仍有底層逾時，與來源穩定／測試等待策略不同。官方測試圖樣、時序及量測規則不變。


`present_display_window` 在完成置頂後要求前景與鍵盤焦點，使用 GetGUIThreadInfo 查詢 renderer 執行緒的實際焦點。一般要求未達成時，暫時連接呼叫端、目前前景及 renderer 執行緒的輸入佇列以執行 SetForegroundWindow／SetFocus，隨後逆序解除。整個置前與檢查操作在獨立程序執行，逾時上限 5 秒；逾時終止該程序並回報錯誤，不重送操作或還原輸出。Windows 仍可能拒絕要求，實際驗證結果為準；不修改官方 renderer 或模擬左右鍵。

### 指定啟用路徑的 DDC/CI 唯讀查詢

`read_display_input` 只接受 `version:1`、非空 `id`、`command`、`targetKey`、`monitorDevicePath`，不接受 `allowInterrupt` 或來源值。可在多輸出時指定其中一條已啟用路徑；不選取輸出、不寫入 DDC/CI、不重啟 renderer、不控制視窗。`get_display_ports`／狀態回覆的 `pathInputQuerySupported:true` 表示支援此指令。

```json
{"version":1,"id":"path-read-1","command":"read_display_input","targetKey":"adapter/target","monitorDevicePath":"device path"}
```

回覆在 `action` 中包含 `command`、`targetKey`、`monitorDevicePath`、`ok:true` 與 `currentValue`（1–255），並保留原生讀值資訊。原生查詢在獨立程序執行，上限3秒；讀取前後核對全部啟用路徑與所選裝置身分。共用同一 GDI source 的鏡像配置、非唯一實體螢幕、未啟用或已變動的身分、無法確認的來源皆拒絕，不猜測或重試。Windows 配置一致性及本機互斥保護仍保留。是否由讀值選取唯一輸出由呼叫端決定；Host不自行串接恢復流程。

上述亮度相容處理依標準 API 回覆判斷，不使用廠牌／型號例外清單；不同最大值依各自實際範圍映射百分比。VCP 失敗不再重複同一次探測，任何寫入開始後皆不轉換路徑或自動重送。新增 brightness-path 診斷階段記錄缺少高階亮度旗標後的探測原因；原 capability 錯誤與 VCP initial-read 結果仍保留。[Microsoft 錯誤碼](https://learn.microsoft.com/en-us/windows/win32/com/com-error-codes-5)。

內建螢幕 WmiSetBrightness 明確回覆非零 ReturnValue 時仍回報錯誤；CIM 回覆未提供／為 null 時，不直接視為寫入失敗，仍立即重新查詢同一 active instance 並確認實際亮度等於目標。缺少回傳碼不代表成功，必須通過原有讀回／levels／身分驗證；不重送寫入、不新增固定等待。此處相容處理適用未完整提供回傳碼的 provider，並非修改 Windows 文件定義的零成功／非零失敗語意。[Microsoft WmiSetBrightness](https://learn.microsoft.com/en-us/windows/win32/wmicoreprov/wmisetbrightness-method-in-class-wmimonitorbrightnessmethods)。

### 即時亮度係數

`get_brightness_factor` 是單次唯讀查詢，只接受 `version:1`、非空 `id`、`command`、`targetKey`、`monitorDevicePath`，要求唯一啟用的 eDP（technology 11）或 Windows 回報 Internal（technology 0x80000000）且 Windows HDR 明確開啟。不需要 renderer 執行，不切換輸出／畫面、不重啟程式、不改 HDR 或亮度。回覆頂層 `brightnessFactor`：

- `target`：與上述 Other 控制相同的裝置身分。
- `brightnessPercent`：取樣前後相同的 Windows 亮度百分比。
- `rawMaxLuminance`、`adjustedMaxLuminance`：分別由同一 monitor interface 的 `DisplayMonitor.MaxLuminanceInNits` 與全新 DXGI factory 下、同 source adapter LUID／GDI device 的 `IDXGIOutput6.GetDesc1().MaxLuminance` 取得；單位 nits，屬系統／裝置資訊，並非光學量測值。
- `factor`：前兩者相除，沿用官方程式 float32 除法後轉為 JSON 數值的語意；必須有限且正值，來源無效時拒絕，不能以推估值代替。
- `controlTrace`、`controlElapsedMs`：沿用既有有界診斷格式，包含亮度前後查核與 fresh-factor 階段。

取樣前後查核唯一端點、身分、HDR 與亮度；有變動即拒絕。原生查詢共用獨立 display-control worker 的 10 秒總逾時，各 PowerShell 子查詢最多4秒；子步驟合計超過總界仍拒絕，不重試，不回傳舊 renderer 快取。Windows 必須提供 DisplayMonitor Windows Runtime API 與 DXGI Output6；缺少介面時回報不可用。

`set_display_brightness` 可額外指定 `expectedHdr:true`，要求在寫入前重新確認同一 eDP 或 Internal 且 HDR 仍開啟，寫後再次確認；條件不符則拒絕或回報未確認，不自動重送。此旗標僅接受布林 true；未提供時維持一般手動 Apply 行為。亮度搜尋順序、停止／取消、等待與成功判定由呼叫端管理，Host 不串接多次調整。

原廠依據：[DisplayMonitor](https://learn.microsoft.com/en-us/uwp/api/windows.devices.display.displaymonitor)、[GetDesc1 動態色彩資訊更新](https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_6/nf-dxgi1_6-idxgioutput6-getdesc1)。

Windows 的 Internal 只表示內建連線，不保證其實體介面為 eDP；不得將其改標成 eDP。仍須通過同端點 WMI 亮度、HDR、即時 metadata 及前後身分／來源核對，無效來源不寫入。[Microsoft 輸出類型定義](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ne-wingdi-displayconfig_video_output_technology)。
