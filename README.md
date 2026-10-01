# DisplayHDRTest Automation Host

本專案是 [VESA DisplayHDRTest-v1.2](https://github.com/vesa-org/DisplayHDRTest-v1.2) 的 fork，提供 HDR 測試圖樣、本機 API 與區域網路遠端控制。測試名稱與鍵盤操作沿用原版設計。

## 程式組成

- **C++ 測試程式**：產生 HDR 測試畫面，提供本機 Named Pipe API。
- **Python Host 服務**：接收 Client 的 HTTP 指令、轉送至測試程式，並提供程序狀態查詢與重啟功能。

Host 整合包已包含 Python runtime，使用者不需自行安裝 Python。C++ 測試程式仍由 Visual Studio C++ 編譯；Python 用於控制服務與封裝工具。

## 部署與啟動

適用 Windows 10／11 x64；HDR 測試需啟用 Windows HDR 並使用支援的顯示器與顯示驅動。

1. 從 [Host Releases](https://github.com/gchang1008/DisplayHDRTest-v1.2/releases) 下載 `DisplayHDR_Host_x64.zip`。
2. 完整解壓至待測電腦，執行 `StartDisplayHDR.cmd`。
3. 顯示 `READY` 後，即可透過 [Client 遙控器](https://github.com/gchang1008/DisplayHDRTest-v1.2-Client) 或 HTTP API 操作。

預設監聽全部 IPv4 介面的 TCP **8765**；Windows 防火牆需允許控制端連入。Client 填入待測電腦的 IP，同機操作可使用 `127.0.0.1`。

指定監聽位址與連接埠：

```powershell
.\StartDisplayHDR.cmd --host 192.168.1.107 --port 8765
```

## 控制與程序狀態

- `catalog`、`get_state`：查詢可用測試與目前測試／設定。
- `set_state`、`key`：設定測試圖樣、參數，或執行原版按鍵操作。
- `get_host_status`、`restart_host`：查詢程序狀態與重啟 Host 測試程式。

關閉測試視窗後，HTTP 服務保持運行，可由 Client 的 `Restart Host` 重新啟動測試程式。重啟會初始化測試、設定與倒數；不重啟 Windows。控制端斷線不會自動重啟或重送操作。

## 從原始碼建置

以下是**開發端**需求；使用整合包的待測電腦不需安裝這些開發工具。

- Visual Studio C++ 建置工具與 Windows SDK。
- Python 3.13，用於執行封裝工具。

在儲存庫根目錄執行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/build.ps1
python tools/package.py
```

預設建立 x64 Release，建置輸出位於 `build-output/automation-x64-Release/`；Host ZIP 與 SHA-256 校驗值位於 `dist/`。

## 文件與授權

- [整合包部署說明](docs/Portable_Packages.md)
- [遠端 HTTP API](docs/Remote_API.md)
- [本機 API 與測試設定契約](docs/Automation_API.md)
- [重啟功能驗證紀錄](docs/Restart_Verification.md)
- [MIT 授權條款](LICENSE)
