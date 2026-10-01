# DisplayHDR 遠端控制 API

## 執行 DisplayHDR 的電腦

使用可攜式 Host／Client ZIP 時，不需要額外安裝 Python；解壓後的入口會使用包內 runtime。部署與操作見 [可攜式整合包](Portable_Packages.md)。以下 `python` 指令可改用包內 `runtime\python.exe -X utf8`。

Client 新增 GUI 遙控器，雙擊 `StartDisplayHDRClient.cmd`，輸入 Host IP 與連接埠即可操作；見 Client 包內 `GUI_Remote.md`。需搭配同批新版 Host 的 `key` 指令。命令列及 Python 呼叫介面保留。

使用 Windows，安裝 Python 3 並確保 `python` 可在命令列執行。正式 C++ 程式的編譯器及執行檔沒有因 HTTP 介面改變；Python 服務負責將網路指令轉送至既有 Named Pipe。

在 `build-output/automation-x64-Release` 雙擊 `StartDisplayHDR.cmd`。這個入口自動啟動 DisplayHDR（`--api`）及 HTTP 服務，顯示 `READY` 後可接受控制。預設連接埠為 **8765**，監聽本機全部 IPv4 介面。

需指定監聽的區域網路 IP 或連接埠時，在該目錄執行：

```powershell
.\StartDisplayHDR.cmd --host 192.168.1.107 --port 8765
```

`192.168.1.107` 是本次驗收主機的乙太網路 IPv4；部署時以執行 DisplayHDR 的電腦實際 IP 為準，可用 `ipconfig` 查詢。`0.0.0.0` 是監聽位址，不是控制端的連線位址。

執行檔、`.cso`、`.png` 資源與下列四個檔案保留在同一目錄：

- `StartDisplayHDR.cmd`
- `displayhdr_server.py`
- `displayhdr_api.py`

`displayhdr_remote.py` 與 GUI 已拆至 [Client 獨立專案](https://github.com/gchang1008/DisplayHDR-Client)，不隨 Host 原始碼或 Host ZIP 提供。

Windows 防火牆須允許控制端連入所選 TCP 連接埠。啟動工具不會自動修改防火牆。依確認需求，本版不提供身分驗證或 HTTPS。

關閉 DisplayHDR 視窗後，啟動入口的服務自動退出。服務停止不主動終止 DisplayHDR 或變更其測試狀態；可用以下方式重新連接仍在執行的 `--api` 實例：

```powershell
python displayhdr_server.py --pid 12345 --host 192.168.1.107 --port 8765
```

`--pid` 模式不擁有 DisplayHDR 程序，服務需自行停止。連接埠已使用、找不到執行檔、無法連接 Named Pipe 或未完成啟動時，入口會回報錯誤，不會顯示 `READY`。連接埠錯誤會在啟動 DisplayHDR 前檢查。

## 另一台 Windows 控制電腦

安裝 Python 3，只需複製 `displayhdr_remote.py`；控制端不需要 DisplayHDR、C++ 編譯器或第三方 Python 套件。

```powershell
# 取得全部測試與設定清單
python displayhdr_remote.py --url http://192.168.1.107:8765 --command catalog

# 指定全畫面藍色，隱藏說明文字
python displayhdr_remote.py --url http://192.168.1.107:8765 --command set_state --test ColorPatchesFull --settings '{"color":"Blue","textVisible":false}'

# 讀回目前測試、設定、提交狀態及倒數
python displayhdr_remote.py --url http://192.168.1.107:8765
```

Python 整合範例：

```python
from displayhdr_remote import DisplayHDRRemoteClient

client = DisplayHDRRemoteClient("http://192.168.1.107:8765", timeout=12)
result = client.request("set_state", id="blue-001", test="ColorPatchesFull",
                        settings={"color": "Blue", "textVisible": False})
if not result["ok"]:
    raise RuntimeError(result["error"])

state = client.request("get_state")["state"]
assert state["lastSetRequestId"] == "blue-001"
assert state["test"]["id"] == "ColorPatchesFull"
assert state["settings"]["color"] == "Blue"
assert state["presentation"]["submitted"]
assert state["presentation"]["presented"]
# 依測試的 timing 等待條件，決定何時呼叫量測設備 API。
```

客戶端每個請求建立並關閉 HTTP 連線，沒有需要維持的登入／工作階段。單一控制端依序送出指令，不實作多控制端協調。系統 Proxy 設定不套用至此區域網路客戶端。

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
| 504 | 本機連線或指令處理逾時 |

網路服務錯誤沿用 `version`、`id`、`ok:false`、`error`，另包含 `error.requestMayHaveApplied`。502／504 的設定指令會保守標示 `true`，表示必須查詢確認，不代表確實已套用。無法解析請求識別值時 `id` 為空字串。

HTTP 正文接收逾時 5 秒；Named Pipe 連接與每次指令等待各最多 5 秒。Python 遠端客戶端預設 12 秒，可用 `--timeout` 或建構子調整。HTTP 回覆後關閉連線；網路服務依序處理請求，不會阻塞 DisplayHDR 的渲染執行緒。

新增原版操作範例：`python displayhdr_remote.py --url http://192.168.1.107:8765 --command key --key Shift+Up`。`key` 與 `set_state` 都是修改指令，502／504 可能已生效，服務不重送；傳輸正文另允許 `key` 欄位。

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
