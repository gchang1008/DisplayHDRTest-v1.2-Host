# Host 程式重啟驗證（2026-10-01）

## 成功標準與結果

- HTTP 服務在 Renderer 正常結束或異常終止後保持運行；`get_host_status` 可查詢 `stopped`／`failed`，`restart_host` 可重新啟動服務擁有的程序。
- 7 項程序監管測試及 17 項既有 HTTP 契約測試通過。
- Host 3 項免安裝封裝測試通過。
- 解壓整合包在 Windows 同機以內建 Python 驗收：API 主動重啟、正常關閉後重啟、終止程序後重啟三種情境均取得新的 PID，並可再次讀取狀態及控制圖樣。
- 47 個測試可查詢；74 組遠端按鍵／Host 原版本地訊息的測試識別值及全部持續設定一致。
- C++ 原始碼未變更；更新前後 Renderer 執行檔 SHA-256 均為 `8082ea3957bf390e182deb818b10628121f74e28016badda5bb313dce582679e`。

## 限制與觀察

調整同機輪詢驗收時，曾在異常終止後重啟的第一次圖樣操作觀察到兩次 `bridge_timeout`，程序仍存活；目前未確定原因。最終驗收先重新讀回測試狀態再發送操作，全部通過，並未改動 Renderer 或自動重送該操作。這不代表所有啟動時序均不會逾時；遇到逾時必須重新確認狀態。

同機控制視窗可能使全螢幕 Renderer 最小化；驗收在發送需要渲染的命令前讀取 `presentation.minimized`，必要時還原僅由驗收啟動的視窗。最終三種重啟情境皆未需要此還原。

未在第二台電腦驗證網路／防火牆。重啟不保留測試設定、不重啟 Windows、不重啟 HTTP 服務。程序崩潰或關閉後不自動重啟。

## 證據與重現

Host：`python tests/test_supervisor.py`、`python tests/test_remote.py`、`python tests/test_portable.py`。
