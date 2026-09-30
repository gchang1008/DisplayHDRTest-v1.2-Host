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

正式執行檔使用原有硬體渲染與 Present 流程。上述測試證明已覆蓋設定下的軟體圖樣／查詢一致性，不能取代實際螢幕驗收。動態圖樣的時序另由下方新增的固定時鐘回歸與實機效能比較驗證。

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

本次代理也已確認正式版本可正常啟動，先前錯誤不再構成本次驗收阻塞，但其根因仍未定位。本次追加結果如下；「配對一致」與「功能成功恢復」分開判定。

## 追加軟體行為驗證（2026-10-01）

正式原版及修改版的核心程式碼未因本輪驗證修改；新增測試副本、探針、腳本及報告。完整自動化套件 14 項通過（93.847 秒），其中故障等價性通過不代表該故障能成功恢復；五分鐘穩定性腳本另有門檻失敗。完整日誌：`build-output/completed-verification-tests.log`。

| 項目 | 結果 |
| --- | --- |
| 動態狀態／像素 | HDR／SDR 各 855 個檢查點，共 1,710 個；原版、修改版 API 關閉／啟用一致 |
| 涵蓋動態項目 | 15 個圖樣，包含暖機、冷卻、長時間白畫面、Flash、Rise-Fall、X-Rite、Profile、字幕及動態漸層；涵蓋暫停／恢復、倒數到期、冷卻返回與重啟 |
| 提交間隔與 CPU | 真正硬體渲染／原有 Present 路徑；Flash、Subtitle Flicker 各四模式、兩輪，共 16 次、每次 20 秒；6 組彙整比較全部通過 |
| 持續 API 查詢 | 提交間隔中位數最大增量 0.2575 ms，p95 最大增量 0.08 ms；CPU 最大增量約 0.04 個核心；未增加慢畫格比例 |
| 通訊故障 | 錯誤 JSON、第二個連線限時失敗、超過 16 KiB、未完整請求、10 秒閒置逾時、25 次未讀回覆即斷線；皆可重連，已設定的藍色圖樣未被部分請求改變 |
| 鍵盤／API 混用 | 數字鍵 6、Space、Shift+4、Alt+Enter；查詢對應圖樣、文字與全螢幕狀態正確 |
| 最小化／還原 | 最小化仍可查詢，`minimized:true`、`presented:false`；還原後 `minimized:false`、`presented:true` |
| 資源失效／重建／縮放 | HDR／SDR 各 20 個輸出檢查點、退出碼在三版本一致；前三個代表圖樣的裝置重建、800×600／640×480 縮放及暫停／恢復成功，回復原有像素 |
| 失效資源狀態 | TenPercentPeak 強制資源無效時 API 正確回報 `resourcesValid:false`／`submitted:false`，重建後資源恢復有效 |

### 時序與效能方法

動態回歸以原有 Update 函式及每秒 60 次的固定測試時鐘執行，每個圖樣 3,000 次更新，再注入倒數邊界；這是加速狀態回歸，並非 30 分鐘實際等待。像素於代表檢查點精確比對。保留原版暫停語意：部分倒數在動畫暫停時仍繼續。

硬體探針在原版與修改版的測試副本加入相同的記憶體緩衝記錄，結束才寫入檔案，使用原有視窗、GPU、計時與 Present。四模式為原版、修改版未啟用 API、API 啟用但未連線、持續 get_state；排除每次起始兩秒，第二輪反轉順序。

執行前門檻：中位數增量 ≤1 ms、p95 增量 ≤2 ms、慢畫格比例增量 ≤1 個百分點、CPU 增量 ≤0.1 個核心。慢畫格定義為間隔超過自身中位數兩倍。GPU 使用率未採樣；部分建置作業與第一輪測試重疊，結果應解讀為本機觀察值。

Flash 渲染記錄的相位間隔在修改版各模式約 1.99999／9.99996 秒；原版一輪首次亮相位為 1.93333 秒，其餘約 1.99999／9.99996 秒。這是提交後取樣結果，不能當作每次內部 Update 邊界；固定時鐘回歸另確認內部序列一致。未因這個原版觀察值修改時序。

### 未通過的情境及追加診斷

1. **五分鐘混合控制穩定性門檻未通過**：期間至少 26,880 次命令，輪流控制全部 47 個圖樣，定期斷線重連；沒有命令錯誤或程序崩潰。暖機後私有記憶體波動未超過 20 MiB，但控制代碼數在 470～476 波動，超過預設最大差 5 的門檻。原始失敗保留。
   - 後續第一次追加診斷與視窗啟用重疊，控制代碼數從約 467 跳至 528；尚不能判定成因。
   - 再固定視窗狀態追加 4,000 次查詢及 40 次斷線，斷線後控制代碼數為 528～532，最後 528，淨變化 -4，未觀察到持續累積。這支持連線能回收，但不等於原五分鐘門檻通過，也不是長時間無洩漏的證明。
2. **裝置重建故障情境未成功恢復**：第四個圖樣 AnimatedColorGradient 於強制資源失效後重建，三版本在同一輸出點以 `0xC0000005` 存取違規結束。之前 20 行輸出完全相同。這是測試副本中的既有／共通故障，未證實正式版本的驅動裝置遺失也會重現；本輪沒有修改核心功能修復它。等價性檢查通過，恢復能力不列為通過。

### 結論與範圍

目前未發現 API 新增造成的核心圖樣、色彩計算、動態狀態或已覆蓋操作行為差異。可在已驗證的環境與正常操作範圍內使用修改版取代原版；不能將兩項未通過情境寫成「全部驗收通過」。

實機使用 NVIDIA GeForce RTX 5070 Ti、VG27AQL1A、HDR、2560×1440／170 Hz。SDR 的配對驗證採離屏測試副本，尚未切換 Windows 至實際 SDR；跨螢幕移動、實際驅動重置、任意長時間運轉及主執行緒停止時的 5 秒處理逾時未實機注入。光學量測與設備 API 串接不屬於本輪軟體行為比對的驗收範圍。

證據位於工作區 `build-output/behavior-verification/`：`dynamic-results.txt`、`benchmark-results.json`、`benchmark-comparisons.json`、`flash-phase-results.json`、`fault-HDR.json`、`fault-SDR.json`、`live-fault-results.json`、`stability-samples.json`、兩份 `handle-recovery*.json` 及 `mixed-*.json`。原五分鐘失敗日誌為 `build-output/live-stability.log`。

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

重現本輪追加驗證：先建置 `tools/build-probe.ps1`（原版加 `-Baseline`），再執行 `python tests/run_live_benchmark.py`；動態／故障配對使用 `test_timing_regression.py`。`run_live_stability.py` 會啟動專用正式版本，`run_live_faults.py PID` 連接指定實例，均會切換圖樣。
