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

執行檔、`.cso`、`.png` 資源與下列四個檔案保留在同一目錄：

- `StartDisplayHDR.cmd`
- `displayhdr_server.py`
- `displayhdr_api.py`
- `displayhdr_supervisor.py`

Windows 防火牆須允許控制端連入所選 TCP 連接埠。啟動工具不會自動修改防火牆。依確認需求，本版不提供身分驗證或 HTTPS。

關閉 DisplayHDR 視窗後，HTTP 服務保持運行，可透過 `restart_host` 要求重啟。服務停止不主動終止 DisplayHDR 或變更其測試狀態；可用以下方式重新連接仍在執行的 `--api` 實例：

```powershell
python displayhdr_server.py --pid 12345 --host 192.168.1.107 --port 8765
```

`--pid` 模式不擁有 DisplayHDR 程序，服務需自行停止。連接埠已使用、找不到執行檔、無法連接 Named Pipe 或未完成啟動時，入口會回報錯誤，不會顯示 `READY`。連接埠錯誤會在啟動 DisplayHDR 前檢查。

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

HTTP 正文接收逾時 5 秒；Named Pipe 連接與每次指令等待各最多 5 秒。控制端需自行設定 HTTP 請求的逾時時間。HTTP 回覆後關閉連線；網路服務依序處理請求，不會阻塞 DisplayHDR 的渲染執行緒。

原版操作的 JSON 請求範例：`{"version":1,"id":"key-001","command":"key","key":"Shift+Up"}`。`key` 與 `set_state` 都是修改指令，502／504 可能已生效，服務不重送；傳輸正文另允許 `key` 欄位。

完整測試識別值、25 個持續設定、狀態快照與暖機／倒數語意見 [既有 API 契約](Automation_API.md)。HTTP 層保留回覆內容，不重新計算圖樣或 Nits。

## 斷線與重連

- 斷線不自動暫停、重啟、切換圖樣或還原設定；原有動畫與倒數照原程式繼續。
- 正文未完整送達時，不轉送任何設定。
- 完整請求送達後，即使控制端沒有收到回覆，設定仍可能完成。
- 網路服務及客戶端都不自動重送失敗指令。重連後先呼叫 `get_state`，核對 `lastSetRequestId`、圖樣及完整設定，再決定是否重送。
- `lastSetRequestId` 是最近一次設定請求，不是歷史指令清單；鍵盤介入或自動變化仍須用目前狀態確認。

## 驗證範圍

同機 HTTP／真實 Named Pipe 的契約測試，以及正式執行檔的 HTTP 測試均已執行；跨電腦驗收仍需在另一台電腦執行上方範例。同機呼叫主機區域網路 IP 可確認監聽介面，不能證明另一台電腦可穿過主機防火牆。

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
- 兩個新指令只接受 version、id、command；額外欄位、重複重啟及附掛模式的重啟要求回覆 400。`--pid` 附掛模式的 `restartSupported` 為 false。
- 重啟會重新初始化程式，原有測試、設定與倒數不保留，也不重播先前控制指令。
- 請求送達後即使回覆遺失，重啟可能已開始；不要自動重送，先查詢程序狀態。
- 本功能需要支援 `restart_host` 的 Host 整合包。

查詢程序狀態時，使用 `get_host_status`；重新啟動測試程式時，使用 `restart_host`。
