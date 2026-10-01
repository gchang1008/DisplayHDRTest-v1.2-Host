# DisplayHDR 可攜式整合包

## 部署

兩份 ZIP 適用 Windows 10／11 x64。完整解壓縮後即可執行，不需要安裝 Python、Visual Studio、Visual C++ Redistributable 或其他 Python 套件。每份整合包包含自己的 `runtime`，不要只複製啟動檔或刪除 runtime。

- 待測系統：解壓 `DisplayHDR_Host_x64.zip`，執行 `StartDisplayHDR.cmd`。
- 控制端：解壓 `DisplayHDR_Client_x64.zip`，使用 `ControlDisplayHDR.cmd`。

Host 預設監聽 TCP 8765。待測系統仍需原程式所需的 Windows 顯示功能與顯示驅動；HDR 測試需開啟 Windows HDR。控制端須能連入 Host 的所選連接埠。這些是作業系統／網路條件，不是額外安裝的程式依賴。

## Host 啟動

雙擊 `StartDisplayHDR.cmd`，看到 `READY` 後可接受控制。也可在解壓目錄的 PowerShell 指定監聽位址與連接埠：

```powershell
.\StartDisplayHDR.cmd --host 192.168.1.107 --port 8765
```

IP 請以待測系統實際位址為準。DisplayHDR 視窗關閉後，服務自動退出。原有鍵盤功能保留；控制端斷線不修改畫面或設定，動畫與倒數照原流程繼續。

## Client 使用

在 Client 解壓目錄開啟 PowerShell，指定 Host IP：

```powershell
.\ControlDisplayHDR.cmd --url http://192.168.1.107:8765 --command catalog
.\ControlDisplayHDR.cmd --url http://192.168.1.107:8765 --command set_state --test ColorPatchesFull
.\ControlDisplayHDR.cmd --url http://192.168.1.107:8765
```

需要提供 JSON 設定時，可直接使用包內執行環境；這個指令不使用或安裝系統 Python：

```powershell
.\runtime\python.exe -X utf8 displayhdr_remote.py --url http://192.168.1.107:8765 --command set_state --test ColorPatchesFull --settings '{"color":"Blue","textVisible":false}'
```

自動化程式可放在 Client 解壓目錄，使用包內 Python 執行：

```powershell
.\runtime\python.exe -X utf8 automation.py
```

`automation.py` 可匯入同目錄的 `displayhdr_remote.DisplayHDRRemoteClient`，整合範例與設定語意見 `Remote_API.md`。這份 runtime 提供 Python 標準函式庫；使用者另外加入的第三方量測設備套件不屬於本包內容。

## 驗證與授權檔

- `manifest.json` 記錄包內各檔 SHA-256；ZIP 外的 `SHA256SUMS.txt` 記錄兩份 ZIP 的 SHA-256。
- `LICENSE-DisplayHDR.txt` 保留原專案授權；`runtime/LICENSE.txt` 保留 Python 及其隨附元件授權。
- 使用 [Python 官方可嵌入發行版](https://docs.python.org/3.13/using/windows.html#the-embeddable-package)，來源及 SHA-256 固定於打包工具。runtime 不讀取系統 Python 安裝或第三方 site-packages，不修改登錄檔與 PATH。

建置端可由原始碼目錄執行 `python tools/package.py` 重建 ZIP。第一次建置會下載官方 runtime，部署後執行不需要下載依賴。
