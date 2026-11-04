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

透過 Restart Host 只重啟 DisplayHDR；`ready` 表示程序與 API 已就緒，不代表視窗已置前、置頂或無遮擋。視窗呈現與檢查由 Client 另送指令；Host 不自動還原畫面或切換驗證圖樣。

遠端控制方式見 [Remote_API.md](Remote_API.md)，測試與設定清單見 [Automation_API.md](Automation_API.md)。

開發端從 Host 原始碼執行 tools/build.ps1 建立 x64 Release，再執行 python tools/package.py。輸出為本專案 dist/DisplayHDR_Host_x64.zip 與 SHA256SUMS.txt。

manifest.json 記錄包內各檔 SHA-256。保留 LICENSE-DisplayHDR.txt、runtime/LICENSE.txt 與官方 Python runtime 來源；勿刪除 runtime 或分開搬移必要資源。

Host API 提供 `get_host_status` 查詢程序狀態，以及 `restart_host` 重啟 DisplayHDR 程式；HTTP 服務保持運行。重啟會重設圖樣與設定，不重啟 Windows。

## 固定安裝位置與一次性防火牆設定

將完整套件放在固定本機資料夾，後續更新沿用相同路徑。更新前先停止自己管理的 Host 服務，且須確認沒有量測進行；勿任意中斷其他 Client、量測或原廠程式。固定 `runtime\python.exe` 路徑可讓既有程式防火牆規則繼續匹配。

初次安裝由管理員在該套件資料夾開啟 PowerShell，將控制端 IP 換成實際值：

```powershell
.\ConfigureHostFirewall.ps1 -ControllerAddress 192.168.1.100
```

自訂 HTTP 埠時加入 `-Port`，例如 `-Port 8875`；腳本支援 `-WhatIf` 預覽。規則限定套件的 `runtime\python.exe`、指定控制端來源與 TCP 埠，適用 Private／Domain 網路。腳本只管理自己建立的規則，不刪改其他既有規則；更換控制端 IP 或安裝路徑後需重新執行。既有封鎖規則、公司群組原則或網路政策仍可能限制連線，腳本不取代管理者設定。

日常啟動 `StartDisplayHDR.cmd` 不需管理員權限，也不自動修改防火牆。正式套件不需要開發部署代理。首次安裝未執行此設定時，Windows 仍可能出現網路存取提示。

## 手動 Input Port 功能

使用相容 Client 的 Input Port 配對／切換介面，先確認 DUT 開啟 Auto Switch 與 DDC/CI，並保留單一啟用的 Windows 輸出作為起點。逐一對照 OSD 保存輸入名稱，再使用配對值切換。Port 變更與 HDR 啟用後均重新啟動 DisplayHDR，完成後保留重啟後的畫面，以全螢幕、隱藏說明文字呈現，維持置頂及遮擋檢查，不另切換驗證圖樣；這是手動功能，不會自動啟動跨 Port 量測。

原生 DDC/CI 查詢、畫面遮擋與路徑控制模組已內附，不需安裝 ControlMyMonitor。功能依螢幕、驅動與線材支援程度而定；DDC/CI 讀不到時可在使用者明確選擇後改用人工確認，並在每次切換後對照 OSD 與畫面；不把 Windows 路徑切換成功當作來源已自動確認。人工模式仍保留單一路徑、裝置身分、HDR、重啟、置頂及遮擋檢查，無法自動偵測接線交換。此模式需同時更新 Host 與控制端。完整條件及 API 見 [Remote_API.md](Remote_API.md)。

Input 操作狀態、請求 id 與診斷僅保存在記憶體，不建立狀態檔、鎖定檔或資料夾。服務重啟後不保存歷史操作，需重新讀取目前狀態。舊版 display-ports.json 與 display-port-session.lock 不會讀取、覆寫或清除。不建立跨次操作的原始桌面備份，也不提供 Restore；要返回之前來源，直接選擇該 Input。Host 重啟或切換失敗後先 Refresh inputs 重新核對目前路徑與 DDC/CI 來源，通過後即可再切換。舊版 pending-display-restore.json 保留但忽略，不會阻擋操作。移除還原功能需同時更新 Host 與 Client。
