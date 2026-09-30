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

## 正式執行檔實機驗收（追加）

同日改用可見視窗啟動正式 x64 Release 執行檔，原版基準、修改版 `--api`、修改版未啟用 API 均正常開啟與關閉，沒有重現初始化錯誤。本次不使用離屏測試副本或 WARP 替換。

實際 API 回報：HDR 模式、2560×1440、亮度滑桿比例 1、螢幕報告峰值約 603.6984 Nits；全螢幕尺寸 2560×1440，視窗模式 1280×720。

| 驗收項目 | 結果 |
| --- | --- |
| 正式版本 API 測試 | 10 項全部通過，包含全部 47 個畫面的識別值、資源有效性及 Present／可見狀態，以及 25 個持續設定回寫／查詢 |
| Active Dimming | API 設定 49.79；實際擷取畫面顯示 `5.1 Active Dimming`、`Nits: 49.79`，查詢值約 49.790237 |
| RGBW | 8% 與全畫面四種顏色的控制／查詢通過；另目視確認兩種模式的藍色色塊 |
| 說明文字 | Space 後實際畫面文字與量測標記隱藏，API 回報 `textVisible:false` |
| Subtitle Flicker | Shift+4 正確跳轉，字幕關閉／說明文字隱藏與 API 查詢一致；目視確認畫面沒有字幕／說明文字 |
| 全螢幕 | Alt+Enter 回到視窗，API 回報 `fullscreen:false` 與 1280×720；API 指定 `fullscreen:true` 後回到 2560×1440 |
| 原版基準 | 正常啟動、數字鍵 6 跳轉、兩次 Down 從 Red 切至 Blue，實際標題與色塊正確 |
| API 未啟用 | 修改版正常啟動與數字鍵 6 操作，確認沒有建立 Named Pipe |
| 測試工具相容性 | 新增 `DISPLAYHDR_LIVE_PID` 以連接正式執行檔；修正測試工具重新連線時的 PID 取得方式，離屏模式的 10 項 API 測試亦重新通過 |

實機測試日誌：工作區根目錄 `build-output/live-api-test-results.txt`。代表狀態快照：`live-keyboard-space-state.json`、`live-full-blue-state.json`、`live-window-state.json`、`live-patch-blue-state.json`、`live-subtitle-state.json`。目視結果來自 Windows 視窗擷取；沒有進行 47 個實機畫面的逐像素比對或光學量測。

重現實機 API 測試時，先以可見視窗啟動正式執行檔 `--api`，再從原始碼目錄執行（將 PID 換成該程序識別碼）：

```powershell
$env:DISPLAYHDR_LIVE_PID = 'PID'
python -m unittest discover -s tests -p test_automation.py -v
Remove-Item Env:DISPLAYHDR_LIVE_PID
```

這組測試會切換全部測試畫面與設定，完成後保留外部程序，不自動還原其設定。請使用專供驗收的程式實例。

## 歷史初始化錯誤與未驗證範圍

代理先前以自動啟動及診斷視窗執行時，在原有 `Game.Initialize` 取得 `DXGI_ERROR_UNSUPPORTED (0x887A0004)`；原版基準的診斷執行也出現相同錯誤。尚未定位失敗的具體 DirectX 呼叫，不能據此判定正式執行檔在使用者桌面無法開啟。

使用者後續回報：原版與修改版均能手動正常開啟。此回報修正先前「目前環境無法初始化」的概括描述；錯誤應限定於代理當時的啟動／診斷條件。啟動方式、視窗狀態或執行工作階段造成差異只是待查假設，尚未證實。

本次代理也已確認正式版本可正常啟動，先前錯誤不再構成本次驗收阻塞，但其根因仍未定位。以下項目仍未完成驗證：

- 實際 SDR 模式的正式執行檔驗收，以及 HDR／SDR 光學輸出。
- 最小化、遮擋、螢幕移動與全部鍵盤操作的完整實機覆蓋。
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

後續應完成上列未驗證項目，再將 `presentation`／等待條件與量測設備流程連接。
