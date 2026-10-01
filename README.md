# DisplayHDR Host：顯示 HDR 測試畫面的程式

這個程式安裝在**連接待測螢幕的電腦**上，用來顯示不同的 HDR 測試畫面。你可以在這台電腦直接用鍵盤操作，也可以在另一台電腦使用 Client 遙控。

本專案以 [VESA 官方 DisplayHDRTest-v1.2](https://github.com/vesa-org/DisplayHDRTest-v1.2) 為基礎，加入遠端控制、狀態查詢與程式重啟功能。

## Host 和 Client 要放在哪裡？

| 名稱 | 放在哪台電腦 | 用途 |
| --- | --- | --- |
| **Host**（本專案） | 連接待測螢幕的電腦 | 顯示測試畫面、接收控制指令 |
| **[Client 遙控器](https://github.com/gchang1008/DisplayHDRTest-v1.2-Client)** | 你用來操作的另一台電腦 | 切換測試、調整設定、查看狀態 |

兩台電腦需要連到同一個區域網路，例如同一台路由器。也可以把 Host 和 Client 放在同一台電腦上試用。

## 使用前需要準備什麼？

- Windows 10 或 Windows 11，64 位元版本。
- 支援 HDR 的待測螢幕，並在 Windows 顯示設定中開啟 HDR。
- Host 和 Client 的 ZIP 整合包。包內已附所需執行檔案，**不用另外安裝 Python，也不用自己編譯程式**。

## 第一次使用：照這幾步操作

1. 開啟 [Host 下載頁面](https://github.com/gchang1008/DisplayHDRTest-v1.2/releases)，在最新版本的 **Assets** 區下載 `DisplayHDR_Host_x64.zip`。
2. 將 ZIP 複製到連接待測螢幕的電腦，按滑鼠右鍵選「解壓縮全部」。保留解壓縮後的所有檔案與資料夾。
3. 進入解壓縮後的資料夾，雙擊 **`StartDisplayHDR.cmd`**。
4. 程式會開啟測試畫面，並顯示一個文字視窗。文字視窗出現 **`READY`**，代表可以接受控制。使用期間請保留這個文字視窗。
5. 在另一台電腦啟動 Client，填入 Host 電腦的 IP 位址，按 **`Connect / Refresh`**，即可開始操作。Client 的步驟見 [Client 使用說明](https://github.com/gchang1008/DisplayHDRTest-v1.2-Client#readme)。

## 怎麼找到 Host 的 IP 位址？

IP 位址是電腦在網路上的地址，Client 需要這個地址才能找到 Host。

在 **Host 電腦**上按 `Win + R`，輸入 `cmd` 後按 Enter，再輸入：

```text
ipconfig
```

找到目前使用的 Wi-Fi 或乙太網路連線，記下它的 **IPv4 位址**，例如 `192.168.1.107`。將這個數字填入 Client 的 `Host` 欄位。

Client 的 `Port` 欄位預設是 **8765**，一般使用保留這個數字即可。同一台電腦試用時，`Host` 欄位填 **`127.0.0.1`**。

## 關閉與重啟

- 關閉測試畫面後，只要啟動時的文字視窗還在，Client 就可以按 **`Restart Host`** 再次開啟測試程式。
- 重啟會重新開始程式，原本的測試、設定與倒數會重設。
- 若連啟動時的文字視窗也關閉了，請回到 Host 電腦，再次雙擊 `StartDisplayHDR.cmd`。

## 連不上時先檢查

1. Host 的文字視窗是否仍開著，且曾顯示 `READY`。
2. 兩台電腦是否連到同一個區域網路，Client 是否填入 Host 正在使用的 IPv4 位址。
3. Client 的 `Port` 是否為 8765；如果自行改過，兩端需使用相同數字。
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
