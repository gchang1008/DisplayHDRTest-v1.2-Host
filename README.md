# DisplayHDR Host：顯示 HDR 測試畫面的程式

這個程式放在**連接待測螢幕的電腦**上，用來顯示不同的 HDR 測試畫面。你可以直接用鍵盤操作，也可以透過遠端 API 控制。

本專案以 [VESA 官方 DisplayHDRTest-v1.2](https://github.com/vesa-org/DisplayHDRTest-v1.2) 為基礎，加入遠端控制、狀態查詢與程式重啟功能。

## 使用前需要準備什麼？

- Windows 10 或 Windows 11，64 位元版本。
- 支援 HDR 的待測螢幕，並在 Windows 顯示設定中開啟 HDR。
- Host 的 ZIP 整合包。包內已附所需執行檔案，**不用另外安裝 Python，也不用自己編譯程式**。

## 第一次使用：照這幾步操作

1. 開啟 [Host 下載頁面](https://github.com/gchang1008/DisplayHDRTest-v1.2-Host/releases)，在最新版本的 **Assets** 區下載 `DisplayHDR_Host_x64.zip`。
2. 將 ZIP 複製到連接待測螢幕的電腦，按滑鼠右鍵選「解壓縮全部」。保留解壓縮後的所有檔案與資料夾。
3. 進入解壓縮後的資料夾，依下方說明選擇本地操作或遠端控制。

### 本地操作：只在這台電腦使用

雙擊 **`DisplayHDRComplianceTests.exe`**，即可像原版一樣用本地鍵盤操作測試畫面。

這種啟動方式不會啟動 HTTP 服務，也不會監聽外部網路連線，不需要設定 IP 或防火牆。請保留同資料夾內的資源檔案。

### 遠端控制：讓另一台電腦操作

雙擊 **`StartDisplayHDR.cmd`**，會同時啟動測試程式與遠端控制服務。文字視窗出現 **`READY`**，代表可以接受控制；使用期間請保留這個文字視窗。

服務預設監聽 **`0.0.0.0:8765`**，也就是接受本機所有 IPv4 網路介面的連線。控制端需使用 Host 的實際 IP 位址，操作方式見 [遠端 API 說明](docs/Remote_API.md)。這種模式下，本地鍵盤仍可使用。

## 怎麼找到 Host 的 IP 位址？

只在使用遠端控制時需要查詢 IP。IP 位址是電腦在網路上的地址，控制端透過這個地址找到 Host。

在 **Host 電腦**上按 `Win + R`，輸入 `cmd` 後按 Enter，再輸入：

```text
ipconfig
```

找到目前使用的 Wi-Fi 或乙太網路連線，記下它的 **IPv4 位址**，例如 `192.168.1.107`。遠端 API 的連線地址使用這個位址，例如 `http://192.168.1.107:8765/api`。

Host 預設使用連接埠 **8765**，一般使用不需修改。同一台電腦呼叫 API 時，可以使用 `http://127.0.0.1:8765/api`。

## 關閉與重啟

- 本地操作模式：關閉測試畫面後，重新雙擊 `DisplayHDRComplianceTests.exe` 即可再次開啟。
- 下列遠端重啟方式適用於使用 `StartDisplayHDR.cmd` 啟動的模式。
- 關閉測試畫面後，只要啟動時的文字視窗還在，就可以透過 API 的 `restart_host` 指令再次開啟測試程式，操作方式見 [遠端 API 說明](docs/Remote_API.md)。
- 重啟會重新開始程式，原本的測試、設定與倒數會重設。
- 若連啟動時的文字視窗也關閉了，請回到 Host 電腦，再次雙擊 `StartDisplayHDR.cmd`。

## 遠端連不上時先檢查

1. Host 的文字視窗是否仍開著，且曾顯示 `READY`。
2. 兩台電腦是否連到同一個區域網路，控制端是否使用 Host 正在使用的 IPv4 位址。
3. 連線地址中的連接埠是否為 8765；如果自行改過，兩端需使用相同數字。
4. Windows 防火牆是否允許 Host 接受區域網路連線。若出現存取提示，允許目前使用的私人網路。

## 為什麼檔案裡有 Python？

顯示測試畫面的程式是用 **C++** 編寫；接收遠端指令、查詢程序狀態與重啟程式的部分使用 **Python**。整合包已附 Python，直接執行啟動檔即可使用。

## 給開發者：自行修改與打包

若要修改原始碼，需要 Visual Studio C++ 建置工具、Windows SDK 與 Python 3.13。在專案根目錄執行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/build.ps1
python tools/package.py
```

編譯結果在 `build-output/automation-x64-Release/`；可供使用者下載的 ZIP 與檔案校驗值在 `dist/`。

## 更多說明

- [整合包詳細使用說明](docs/Portable_Packages.md)
- [用程式遠端控制 Host](docs/Remote_API.md)
- [可控制的測試與設定](docs/Automation_API.md)
- [重啟功能的驗證結果與限制](docs/Restart_Verification.md)
- [MIT 授權條款](LICENSE)
