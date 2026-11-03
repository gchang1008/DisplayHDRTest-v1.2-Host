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
- 本功能需要支援 `restart_host` 的 Host 整合包。

查詢程序狀態時，使用 `get_host_status`；重新啟動測試程式時，使用 `restart_host`。
## 本機顯示操作 API

HTTP bridge 的 `POST /api` 提供獨立操作，不改動官方圖樣、計時或量測規則；DDC/CI使用Windows原生VCP 0x60，不需外部控制工具。`get_host_status` 回報 `displayPortControl: true`、`portPrimitives: true` 能力。

`get_display_ports` 唯讀盤點端點、EDID雜湊、Windows唯一啟用輸出與當次DDC/CI值，回覆 `displayPorts`。端點包含 `targetKey`、`monitorDevicePath`、`name`、`connection`、`active`、`available`、`edidHash`；adapter LUID可能在重開機後改變，不能當永久識別。顯示器輸入名稱與數值的對應由呼叫端配對，不推定26必為USB-C。缺少可靠EDID、同型號裝置或交換線材時，仍可能需要人工核對。

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

### EDID 原始資料查詢

`get_display_edid` 是唯讀查詢，只接受 `version:1`、非空 `id`、`command`、`targetKey`、`monitorDevicePath`，不接受 `allowInterrupt`。指定身分須符合目前唯一啟用的 Windows 輸出，讀取前後均核對；不改顯示配置、HDR、視窗或 DDC/CI 來源。

```json
{"version":1,"id":"edid-1","command":"get_display_edid","targetKey":"adapter/target","monitorDevicePath":"device path"}
```

成功回覆為 `{"version":1,"id":"edid-1","ok":true,"edid":{...}}`。`edid` 包含 `targetKey`、`monitorDevicePath`、`dataBase64`（原始 bytes 的 Base64）、`source`（`wmi`、`registry` 或 `unavailable`）、`byteLength`、`expectedLength`（無基礎區塊時為 null）、`complete`、`checksumsValid`、`warnings`（字串陣列）。`complete` 僅表示資料長度等於基礎區塊宣告的 `(extension count + 1) × 128`；標頭或 checksum 錯誤另列警告，不修補資料。

優先透過 Windows `WmiMonitorDescriptorMethods.WmiGetMonitorRawEEdidV1Block` 逐一讀取所有宣告區塊，不固定限制 256 bytes。固定 PowerShell worker 上限 8 秒，保留逾時前已取得的連續區塊；不重送讀取。不完整時可選用同一端點較長的登錄 EDID，回報 `source:registry` 及快取來源警告，不與 WMI 區塊拼接；已有 WMI 基礎區塊時，登錄基礎區塊須完全相同才可替代。Windows 驅動提供的 EDID 可能包含快取或 override，不宣稱為直接向面板 EEPROM 即時讀取。

缺少區塊、checksum 錯誤或無法讀取均回覆 `ok:true`，保留實際原始內容並列出原因，由呼叫端顯示警告及決定測試策略。身分不符、讀取期間輸出改變、欄位錯誤或本機操作忙碌仍拒絕。資料保存與跨 Input 排程由 Client 負責。

原廠依據：[WmiGetMonitorRawEEdidV1Block](https://learn.microsoft.com/en-us/windows/win32/wmicoreprov/wmigetmonitorraweedidv1block-wmimonitordescriptormethods)、[Windows EDID 格式與 override](https://learn.microsoft.com/en-us/windows-hardware/drivers/display/overriding-monitor-edids)。

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

回覆在 `action` 中包含 `command`、`targetKey`、`monitorDevicePath`、`ok:true` 與 `currentValue`（1–255），並保留原生讀值資訊。原生查詢在獨立程序執行，上限3秒；讀取前後核對全部啟用路徑與所選裝置身分。共用同一 GDI source 的鏡像配置、非唯一實體螢幕、未啟用或已變動的身分、無法確認的來源皆拒絕，不猜測或重試。Windows 配置一致性及本機互斥保護仍保留。是否由讀值選取唯一輸出由 Client 決定；Host不自行串接恢復流程。
