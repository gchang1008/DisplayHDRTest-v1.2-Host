# DisplayHDRTest
VESA DisplayHDR compliance tests

This is the github repo for source code of the DisplayHDRTest app
which generates the test patterns for DisplayHDR certification.

## 自動化 Host

本 fork 的 `feature/automation-api` 分支新增本機 Named Pipe 與區域網路 HTTP 控制，保留原版測試圖樣與鍵盤功能。[Client 遙控器](https://github.com/gchang1008/DisplayHDRTest-v1.2-Client) 已拆至獨立專案。

解壓 Host ZIP 後執行 `StartDisplayHDR.cmd`，預設 TCP 8765。部署端不需安裝 Python；詳見 [部署文件](docs/Portable_Packages.md) 與 [API 契約](docs/Automation_API.md)。

開發端以 Visual Studio C++／Windows SDK 與 Python 3.13 執行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/build.ps1
python tools/package.py
python -m unittest discover -s tests -p test_portable.py -v
```

建置輸出在本專案 `build-output/automation-x64-Release/`；Host ZIP 與 SHA-256 在 `dist/`。封裝工具只建立 Host，不需要 Client 原始碼或 Qt。上游仍為 [VESA 官方儲存庫](https://github.com/vesa-org/DisplayHDRTest-v1.2)。

拆分前的 Client 程式與整合驗證紀錄仍保留於既有 Git 歷史；目前版本的 Client 原始碼、GUI 文件與封裝工具由獨立儲存庫維護。

