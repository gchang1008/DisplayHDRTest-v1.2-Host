# DisplayHDR Host 可攜式整合包

適用 Windows 10／11 x64。完整解壓 `DisplayHDR_Host_x64.zip` 並保留所有檔案。Python runtime、執行檔、shader 與 PNG 已附，不需另裝 Python／Visual C++ 執行環境。

## 選擇啟動方式

| 使用方式 | 雙擊的檔案 | 網路連線 |
| --- | --- | --- |
| 本地鍵盤操作 | `DisplayHDRComplianceTests.exe` | 不啟動 HTTP 服務，不監聽外部連線 |
| 遠端 API 控制，也可用本地鍵盤 | `StartDisplayHDR.cmd` | 啟動 HTTP 服務，預設監聽 `0.0.0.0:8765` |

本地模式關閉後，重新雙擊 EXE 即可再次開啟。遠端模式需等啟動文字視窗顯示 `READY`，並在使用期間保留該視窗。

## 遠端控制設定

預設全部 IPv4 介面 TCP 8765。Windows 防火牆須允許控制端連入；HDR 測試仍需開啟 Windows HDR 並使用適當顯示驅動。沒有身分驗證或 HTTPS。

指定監聽位址：

```powershell
.\StartDisplayHDR.cmd --host 192.168.1.107 --port 8765
```

IP 以 Host 實際位址為準；同機呼叫 API 可使用 127.0.0.1。關閉 DisplayHDR 後服務保持運行，可透過 API 要求重啟，控制端斷線不修改畫面或設定。

遠端控制方式見 [Remote_API.md](Remote_API.md)，測試與設定清單見 [Automation_API.md](Automation_API.md)。

開發端從 Host 原始碼執行 tools/build.ps1 建立 x64 Release，再執行 python tools/package.py。輸出為本專案 dist/DisplayHDR_Host_x64.zip 與 SHA256SUMS.txt。

manifest.json 記錄包內各檔 SHA-256。保留 LICENSE-DisplayHDR.txt、runtime/LICENSE.txt 與官方 Python runtime 來源；勿刪除 runtime 或分開搬移必要資源。

Host API 提供 `get_host_status` 查詢程序狀態，以及 `restart_host` 重啟 DisplayHDR 程式；HTTP 服務保持運行。重啟會重設圖樣與設定，不重啟 Windows。
