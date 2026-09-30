# 自動化 API 驗證報告

日期：2026-09-30。原版基準：`68cda1f04eb14dea882dd9309d50f61803413574`。

## 已完成

| 項目 | 結果與範圍 |
| --- | --- |
| x64 Release／Debug | 建置成功，執行檔與資源位於工作區根目錄 `build-output/automation-x64-Release`、`automation-x64-Debug` |
| API 自動化測試 | 10 項通過，使用真正的 C++ Named Pipe、JSON 驗證、狀態控制與查詢程式 |
| 原始碼回歸檢查 | 1 項通過；全部原有圖樣函式、色彩換算、計時工具及鍵盤事件處理與原版一致 |
| HDR／SDR 畫面及 metadata 比對 | 1 項通過；每種模式 160 組，共 320 組；原版、API 關閉、API 啟用三者一致 |
| 總計 | 12 項測試通過 |

API 測試涵蓋：全部 47 個測試畫面切換、25 個持續設定回寫與查詢、8%／全畫面 RGBW 明確選擇、Active Dimming 49.79 顯示與字幕關閉／文字隱藏範例、無效請求整份拒絕、未知欄位／型別／範圍錯誤、X-Rite 初始化與間隔、自動換色狀態版本、相同設定不重設倒數、暖機等待與呈現提交分離、明確重啟、通訊錯誤與重新連線、正常關閉清理。

畫面比對涵蓋全部測試識別值，以及 RGBW、棋盤格、黑階、Profile 索引、X-Rite 色塊／白階、字幕、Local Dimming 模式及部分有文字的代表狀態。比較 fp16 原始像素雜湊及原程式 metadata 計算內容。

## 離屏測試方法與證據限制

測試工具從原版 Git 基準及修改版各複製一份至本機暫存目錄，只在這些**測試副本**替換硬體邊界：

- D3D11 使用 WARP 軟體裝置。
- 建立離屏 fp16 Render Target 與原有 Direct2D 圖樣，於 Present 前擷取像素。
- 使用固定的模擬螢幕資訊：640×480、峰值 1000、全畫面 500、最低 0.0001 Nits；分別模擬 HDR／SDR。
- Present 與實體 metadata 提交在測試副本中替換；保留原有 metadata 計算。
- 固定原版隨機抖動的測試輸入，使配對像素可比較。

正式執行檔使用原有硬體渲染與 Present 流程。上述測試證明已覆蓋設定下的軟體圖樣／查詢一致性，不能取代實際螢幕驗收。動態圖樣的配對畫格不代表整段時序已驗證。

## 外部阻塞與未驗證範圍

代理先前以自動啟動及診斷視窗執行時，在原有 `Game.Initialize` 取得 `DXGI_ERROR_UNSUPPORTED (0x887A0004)`；原版基準的診斷執行也出現相同錯誤。尚未定位失敗的具體 DirectX 呼叫，不能據此判定正式執行檔在使用者桌面無法開啟。

使用者後續回報：原版與修改版均能手動正常開啟。此回報修正先前「目前環境無法初始化」的概括描述；錯誤應限定於代理當時的啟動／診斷條件。啟動方式、視窗狀態或執行工作階段造成差異只是待查假設，尚未證實。

使用者已確認可啟動，但以下項目仍未由代理完成實機驗證：

- 正式執行檔在實際 HDR／SDR 螢幕上的操作與光學輸出。
- 實機全螢幕切換、視窗狀態、人工鍵盤與 API 同時操作。
- HDR metadata 實際送達螢幕、裝置遺失／重建與螢幕移動。
- API 持續查詢對畫面更新、VSync、Flash／Rise-Fall 動態時序與效能的影響。
- 缺少資源、通訊逾時、異常中斷等所有實機故障注入情境。
- 量測設備 API 串接與端到端自動量測。

Win32 Release 的原版與修改版均在原有 `BackgroundNoiseEffect.hlsl` 的 `lib_4_0_level_9_3_ps_only` 編譯設定出現相同 `X3548`／`X3511`，未產生 Win32 交付版本。未修改該 shader 或原有測試內容。

## 重現方式

從原始碼目錄執行：

```powershell
powershell -NoProfile -File tools/build.ps1 -Baseline
powershell -NoProfile -File tools/build.ps1
powershell -NoProfile -File tools/build-harness.ps1 -Baseline -Software
powershell -NoProfile -File tools/build-harness.ps1 -Software
python -m unittest discover -s tests -p 'test_*.py' -v
```

工作區根目錄的 `build-output/test-results.txt`、`render-regression-results.txt` 與各建置目錄的 `build.log` 保存本次結果。測試副本位於 `%LOCALAPPDATA%/DisplayHDRAutomationBuild`，不加入 Git。原始碼內只追蹤工具、測試與文件。

實機環境恢復後，應按上列未驗證項目完成驗收，再將 `presentation`／等待條件與量測設備流程連接。
