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
- 重啟先正常關閉服務啟動的程序；等待 5 秒仍未退出時終止該程序，再啟動相同執行檔與 `--api`。不關閉其他 DisplayHDR 程序。
- 程式尚未 ready 時，圖樣操作／查詢回覆 HTTP 503、`host_unavailable`，不轉送操作。狀態查詢仍可用。
- 兩個新指令只接受 version、id、command；額外欄位、重複重啟及附掛模式的重啟要求回覆 400。`--pid` 附掛模式的 `restartSupported` 為 false；附掛程序結束後仍會更新程序狀態，但不會關閉或重啟附掛程序。
- 重啟會重新初始化程式，原有測試、設定與倒數不保留，也不重播先前控制指令。
- 請求送達後即使回覆遺失，重啟可能已開始；不要自動重送，先查詢程序狀態。
- 本功能需要支援 `restart_host` 的 Host 整合包。

查詢程序狀態時，使用 `get_host_status`；重新啟動測試程式時，使用 `restart_host`。
## 手動 DUT Input Port 配對與切換

此功能由 HTTP bridge 的 `POST /api` 處理，不改變官方圖樣、計時或量測流程。使用 Windows 原生 DDC/CI 查詢 VCP `0x60`，不需外部螢幕控制工具或部署代理。僅支援由 `StartDisplayHDR.cmd` 管理的可重啟 Host，初始桌面須只有一條啟用顯示路徑；所有待配對輸入可以預先接線。DUT 必須開啟 Auto Switch 與 DDC/CI。軟體無法讀取 OSD 的 Auto Switch 設定，必須由使用者確認。螢幕、顯卡或線材不支援有效 DDC/CI 輸入讀值時，不提供自動確認。

所有命令使用既有 `version: 1`、非空字串 `id` 與 `command` 欄位，且只接受下列額外欄位：

| command | 額外欄位 | 行為 |
| --- | --- | --- |
| `get_display_ports` | 無 | 唯讀刷新顯示端點、EDID 雜湊及目前 DDC/CI 值；操作執行中只回快取 |
| `get_display_port_status` | 無 | 回傳快取狀態，不重新查詢 DDC/CI；renderer 故障時仍可查 |
| `switch_display_port` | `targetKey`、`monitorDevicePath`、`expectedInput`、`calibration`、`allowInterrupt: true`、`autoSwitchConfirmed: true` | 非同步單一輸出切換、DDC/CI、HDR 與視窗呈現確認 |

新 bridge 的 `get_host_status` 回覆包含 `host.displayPortControl: true` 能力旗標，Client 可據此識別 Port API。沒有此旗標的舊 Host 不代表支援此功能。

切到不同端點的配對會排除切換前已確認的舊輸入值，避免 DUT 尚在顯示舊來源時誤把兩筆舊值當新 Port；無法區分兩個來源時會逾時失敗。若切換前目前輸入值無法確認，拒絕變更，應先刷新盤點。配對原本已啟用的端點則允許相同值。

Port 操作以服務內的記憶體狀態及執行緒鎖互斥，同一服務不接受重疊的切換要求；不建立跨服務檔案鎖。每次刷新及切換都重新核對目前單一路徑與 DDC/CI 身分，不依賴上一輪顯示配置。

配對要求 `calibration: true`、`expectedInput: null`；等待連續兩次相同有效值，由 Client 請使用者對照 OSD 命名，不自行推定 26 代表 USB-C。正常切換要求 `calibration: false`、`expectedInput` 為已配對的 1–255 整數；連續兩次符合目標才完成。`targetKey` 的 adapter LUID 可能於重開機後改變，不能當永久儲存鍵；以重新盤點的 `monitorDevicePath`、`edidHash` 核對配對。無法取得 EDID 雜湊時須人工重新核對裝置身分。接線交換不一定能由身分欄位提前偵測，使用者更換接線後應重新配對；來源不符時停止。

正常回覆為 `{"version":1,"id":"...","ok":true,"displayPorts":{...}}`。`displayPorts` 包含 `supported`、`targets`、`activeTargetKey`、`input`、`pendingRestore`、`operation`。端點項目為 `targetKey`、`monitorDevicePath`、`name`、`connection`、`active`、`available`、`edidHash`；DisplayPort 輸出可能接到 DUT 的 DP 或 USB-C，名稱仍須配對。`pendingRestore` 固定為 false，僅保留舊格式相容，新 Client 不依賴此欄位；不再提供 `restore_display_ports`。`input` 保留原始讀值及解析格式；只辨識單 byte 或相同 byte 重複格式，其他混合值不截低位元組當成功。

`operation` 包含 `operationId`、`kind`、`phase`（`idle`、`running`、`ready`、`failed`）、`error`、`ready`、`targetKey`、`inputValue`、`hdr`、`calibration`，完成時另有新 renderer `state` 與 `window`。切換先回 `running`，Client 使用 `get_display_port_status` 輪詢。請求逾時後先查狀態，不重送 mutation；同一服務執行期間，相同 id 不會重複套用，不能改用同一 id 送不同內容。操作狀態、請求 id 及診斷只保存在記憶體。服務重啟後以未確認的 idle 狀態開始，不保留歷史操作或自動重跑；按 Refresh inputs 重新盤點，核對通過後可再操作，不會要求先還原。

配對及一般切換皆要求原狀態為 `StartOfTest` 或 `ColorPatchesFull`；Client 可先透過既有 `set_state` 切回 `StartOfTest`，確認成功後再送出配對要求。Client 在量測期間必須阻擋配對及切換，不得於量測中呼叫。API 為維持相容性保留 `calibration` 欄位名稱。切斷其他路徑並儲存指定單一路徑後，先重啟 renderer；若該輸入 HDR 關閉則開啟並再重啟。每次原生查詢以獨立唯讀程序及 3 秒上限隔離，45 秒內要求連續兩次相符讀值，樣本間隔 0.5 秒。失敗、逾時、不符或遮擋均停止且不自動還原。配對及切換完成後不再指定藍色或其他驗證圖樣；保留重啟後畫面，僅設定全螢幕、隱藏說明，將受管理 renderer 置頂，並確認呈現及幾何遮擋。切換仍需確認 HDR；這不插入官方量測序列，也不代表量得 HDR 光學性能。

可以直接選擇下一個輸入，不建立或復用跨次操作的原始桌面備份。目前已啟用的端點可直接配對，不呼叫無意義的 SetDisplayConfig，但仍確認新環境與視窗呈現。操作期間 bridge 拒絕 `set_state`、`key`、`restart_host` 及另一個 Port 操作。Input 功能不建立狀態檔、鎖定檔或資料夾；HTTP 狀態不包含完整取樣或原始 CCD 資料。舊版留下的 display-ports.json 與 display-port-session.lock 不會讀取、覆寫或清除。舊版留下的 pending-display-restore.json 保留原地但忽略，不復用，也不阻擋操作。

切換失敗時保留當前輸出並回報具體原因，不自動切回其他 Input。重新讀取核對通過後，可再配對或切換。網路斷線、關閉程式或 Host 重啟均不自動還原；若要回到之前的來源，直接選擇該 Input。移除還原功能需同步更新 Host 與 Client。
