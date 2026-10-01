# DisplayHDR Host 可攜式整合包

適用 Windows 10／11 x64。完整解壓 DisplayHDR_Host_x64.zip，執行 StartDisplayHDR.cmd，看到 READY 後可接受控制。Python runtime、執行檔、shader 與 PNG 已附，不需另裝 Python／Visual C++ 執行環境。

預設全部 IPv4 介面 TCP 8765。Windows 防火牆須允許控制端連入；HDR 測試仍需開啟 Windows HDR 並使用適當顯示驅動。沒有身分驗證或 HTTPS。

指定監聽位址：

```powershell
.\StartDisplayHDR.cmd --host 192.168.1.107 --port 8765
```

IP 以 Host 實際位址為準；同機 Client 可使用 127.0.0.1。關閉 DisplayHDR 後服務保持運行，可由 Client 要求重啟，控制端斷線不修改畫面或設定。

Client 遙控器、命令列與 Python Client 由 [獨立儲存庫](https://github.com/gchang1008/DisplayHDRTest-v1.2-Client) 提供，請搭配支援 key 指令的版本。API 文件見 Remote_API.md 與 Automation_API.md。

開發端從 Host 原始碼執行 tools/build.ps1 建立 x64 Release，再執行 python tools/package.py。輸出為本專案 dist/DisplayHDR_Host_x64.zip 與 SHA256SUMS.txt；不依賴 Client 原始碼或 Qt。

manifest.json 記錄包內各檔 SHA-256。保留 LICENSE-DisplayHDR.txt、runtime/LICENSE.txt 與官方 Python runtime 來源；勿刪除 runtime 或分開搬移必要資源。

新版提供 Host 程式重啟及程序狀態查詢。請更新兩端整合包；Client GUI 的 `Restart Host` 重啟 DisplayHDR 程式，HTTP 服務保持運行。重啟會重設圖樣與設定，不重啟 Windows。
