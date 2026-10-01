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

## 遠端 HTTP 實作驗證（2026-10-01）

本輪新增 Python HTTP 服務、遠端客戶端及單一啟動入口，沒有修改或重新編譯 C++ 核心。HTTP 正文原樣交由既有控制邏輯驗證與套用，回覆沿用原有狀態快照。

- 17 項 HTTP 測試通過；先以真實 Named Pipe 測試副本執行，再連接正式 x64 Release 執行檔驗收。涵蓋全部 47 個圖樣與 25 個持續設定、RGBW、49.79 Nits、字幕／文字、原子驗證、初始化、倒數、自動更新與識別值。
- 新增網路故障測試：無效 JSON／UTF-8／正文型別／路由／方法／大小／Content-Type、未完整正文的絕對逾時、完整指令送出後斷線、橋接逾時／中斷的錯誤回覆、不得自動重送，以及服務停止後狀態保留。
- 部分橋接故障以測試替身注入；正文與斷線測試使用真正 TCP，正常控制使用真正 C++ Named Pipe。
- 實際 `StartDisplayHDR.cmd` 從 UNC 輸出目錄成功啟動，設定主機 IP `192.168.1.107:8765`；同機呼叫該 IP 切換與查詢成功。DisplayHDR 正常關閉後服務退出碼為 0；連接埠占用時，服務在建立新的 DisplayHDR 程序前回報錯誤。
- Python 驗收版本為 3.13.5；正式原有執行檔及資源未改動，只有加入部署腳本。

### HTTP 查詢對核心效能的影響

使用前輪相同的硬體探針副本與門檻。原版與修改版持續 HTTP 查詢，各以 Flash／Subtitle Flicker 比較兩輪，第二輪反轉順序；共 8 次，每次 20 秒，排除起始兩秒。探針保留真實 GPU、視窗、原有計時與 Present；客戶端與服務在同一電腦以 TCP 呼叫，沒有背景建置／測試作業重疊。

兩組彙整皆通過：Flash 中位數與 p95 增量皆約 0 ms；Subtitle Flicker 中位數增量約 0.31 ms、p95 增量約 -0.21 ms；兩者慢畫格比例增量皆 0。DisplayHDR 程序 CPU 最大增量約 0.023 個核心，未量測 Python 服務的 CPU 使用量。門檻仍為中位數 ≤1 ms、p95 ≤2 ms、慢畫格比例增量 ≤1 個百分點及 DisplayHDR CPU 增量 ≤0.1 個核心。

證據：`build-output/remote-test-results.log`、`remote-live-tests.log`、`remote-packaged-launch.log`、`remote-port-conflict.log`、`remote-lan-dimming.json`、`remote-lan-subtitle.json`，及 `behavior-verification/remote-benchmark-results.json`、`remote-benchmark-comparisons.json`、`remote-*.csv`。

跨電腦的實際連線、防火牆及網路故障尚未驗收；需要第二台 Windows 電腦執行 `Remote_API.md` 的客戶端範例。同機使用主機 IP 不等於完成這項驗收。兩版本原有共通故障仍屬既有／共通問題，不歸類為遠端 API 引入的回歸。

封裝入口驗收曾重現 Windows 的同連接埠重複綁定；現已以 `SO_EXCLUSIVEADDRUSE` 修正並新增占用測試，第二次啟動回報 `WinError 10048`，不會啟動第二個 DisplayHDR。此行為及排他綁定方式依 [Microsoft Winsock 文件](https://learn.microsoft.com/en-us/windows/win32/winsock/using-so-reuseaddr-and-so-exclusiveaddruse) 核對。沒有修改 C++ 核心。

最終完整套件共 31 項通過，94.295 秒；原有 HDR／SDR 共 320 組靜態圖樣／metadata 及 1,710 個動態狀態／像素檢查點仍一致。日誌：`build-output/remote-full-suite.log`。部署腳本與來源逐位元相符，證據：`build-output/remote-deployment-check.json`。

## 免安裝整合包驗證（2026-10-01）

- Host／Client 分別內附官方 Python 3.13.16 Windows x64 embeddable runtime。下載 ZIP 的 SHA-256 與 [Python 官方發行頁](https://www.python.org/downloads/release/python-31316/) 一致，打包工具固定來源與雜湊。
- Host 原有 Release 採 `/MT` 靜態 C Runtime；`dumpbin /dependents` 顯示只依賴 Windows 的 DirectX、WinRT 與系統 DLL。Python 所需 `vcruntime140.dll`、`vcruntime140_1.dll`、`libffi-8.dll` 已隨包提供。
- 3 項封裝測試通過：ZIP CRC／解壓後所有檔案雜湊、隔離 runtime 與實際 DLL 路徑、Host／Client 啟動入口。
- 測試解壓路徑包含中文、空白與 UNC。子程序 PATH 只保留 Windows System32，PYTHONHOME／PYTHONPATH 指向不存在位置；runtime `isolated=1`，sys.path 全部位於整合包，指定 C Runtime 與 libffi 實際載入路徑皆位於包內 runtime。
- 從 Host ZIP 的啟動入口執行正式 DisplayHDR；Client ZIP 成功取得 catalog、指定測試、查詢及切換全畫面藍色。包內 Python 執行的 17 項正式 API 驗收全部通過。
- 正常關閉 DisplayHDR 後 HTTP 監聽停止；本輪沒有修改 C++ 核心。驗收過程曾發生測試腳本混合編碼輸出錯誤，修正測試輸出後完成控制，並非包內 Host 或 Client 執行失敗。

證據：`build-output/portable-tests.log`、`portable-live-api-tests.log`、`portable-live-host.log`、`portable-live-client-results.json` 及 `portable-package-build.json`。交付 ZIP 位於工作區 `packages/`，旁附 `SHA256SUMS.txt`；包內含 `manifest.json`。

這是排除系統 Python 與檢查 DLL 來源的測試，並未重新安裝一台乾淨 Windows，也未在第二台電腦實測。Windows 10／11 x64 的系統功能、顯示驅動與 Host HDR 設定仍由目標作業系統提供；不要求額外安裝本程式的 Python／C++ 執行依賴。
## GUI 遙控器驗證（2026-10-01）

- 正式 x64 Release 與 offscreen harness 重新編譯成功。新增範圍僅為 API key 指令、GUI 與封裝；Game.cpp、Main.cpp、原有按鍵函式、圖樣與 metadata 計算未修改。
- 4 項遠端按鍵測試通過：數字／Shift 跳轉、方向及 Shift 步進、功能按鍵、無效輸入不變更狀態。
- 8 項 GUI 測試通過：全部 33 個按鈕、放開觸發、Ctrl 組合防誤動作、輸入焦點、滑鼠及鍵盤長按、不積壓、逾時停用且不重送、請求中關閉。
- 既有 17 項 HTTP API 回歸測試通過，涵蓋全部 47 個測試、全部持續設定與斷線行為；另確認 key 指令的 bridge 逾時標示 requestMayHaveApplied=true 且只嘗試一次。
- 5 項封裝驗證通過：完整檔案雜湊、隔離 Python／C Runtime、命令列入口、GUI 的 Qt／Shiboken／MSVC DLL 全部從 Client 包內載入，以及從中文／空白 UNC 路徑執行 GUI 啟動入口並正常關閉。
- 實際解壓 Host／Client 到中文與空白 UNC 路徑，PATH 僅 Windows System32，PYTHONHOME／PYTHONPATH／QT_PLUGIN_PATH 指向不存在位置。Client 包內 Python 啟動原生 Windows Qt GUI，讀取 47 項測試，成功操作全畫面 RGB、文字、字幕、Cooldown、Home 及 Shift 長按 Active Dimming（450 → 480）；成功讀回與顯示狀態。
- 正式 Host 同一實例中，以原版 Main.cpp 的 WM_KEYDOWN／WM_KEYUP／WM_SYSKEYDOWN 處理路徑，和遠端 key 操作進行 74 組比對。測試識別值與完整持續設定全部一致，涵蓋原版跳轉、Shift＋6–9 無作用、方向、功能、亮度、X-Rite、棋盤格、白階及全螢幕。
- 正常關閉待測程式後服務退出。這輪測試腳本曾修正 READY pid 的大小寫解析，以及 Qt 測試等待期間讓 Python 背景工作正常執行的事件迴圈；均非交付程式的故障。

證據：build-output/gui-tests.log、remote-key-tests.log、gui-remote-regression.log、gui-portable-tests.log、gui-live-results.json、gui-native-key.log 與 displayhdr-gui-preview.png。

這輪驗證為同機透過 HTTP 的 Client／Host，尚未使用第二台電腦驗證網路／防火牆，也未使用乾淨重裝系統。按鍵比對檢查程式狀態，沒有新增光學量測；既有圖樣／metadata 與動態回歸證據仍見前文。
# Host 清單名稱核對（2026-10-01）

使用重新編譯的 x64 Release 執行檔，透過 API 逐一切換全部 47 個頁面並顯示說明文字，核對 `catalog.tests[].title` 與 `test.displayedText` 的第一個非空白行。47 個項目均符合完整標題或不含動態值的固定前綴。RGB 與 Flash 使用啟動預設設定核對，未宣稱固定選單會隨顏色或 On／Off 更新。

本次修正 8 個清單名稱：

| 測試 ID | 修正後名稱 |
| --- | --- |
| `ConnectionProperties` | `Connection properties:` |
| `PanelCharacteristics` | `Reported Panel Characteristics` |
| `ResetInstructions` | `Start of performance tests` |
| `PQLevelsInNits` | `PQ/ST 2084 levels in nits` |
| `ColorPatches` | `6. Checking Red Chromaticity Point` |
| `ColorPatchesFull` | `6. Checking Red Chromaticity Point` |
| `ColorPatchesMAX` | `6.b Checking Red Chromaticity Point` |
| `XRiteColors` | `1.2.5 X-Rite?Colors` |

X-Rite 名稱中的問號來自目前原有畫面輸出，本次只使清單一致。程式碼修改僅涉及 `GameAutomation.cpp` 的名稱字串；未修改 `Game.cpp`、測試 ID、設定控制、繪圖或鍵盤處理。這是名稱與切換驗證，沒有重新執行時序或光學驗證。完整快照記錄於 `build-output/title-audit.json`。


## 特殊字元顯示修正（2026-10-01）

原有 Game.cpp 的三個字串使用 Windows-1252 的 ©（0xA9）與 ™（0x99），在目前字碼頁 950 的編譯環境會被誤讀。本次僅將這三個字串中的特殊字元改成 Unicode 跳脫寫法，並恢復 API 清單的 `1.2.5 X-Rite™ Colors`；未變更測試計算、圖樣、計時或操作邏輯。前輪把問號當成正確標題的處理已撤回。

- x64 Release 重新編譯成功。
- `tests/test_unicode.py` 核對編譯後執行檔的三個 UTF-16 字串。
- 正式程式透過 API 核對 Start Screen 的 `Copyright © VESA`、`Includes Portrait X-Rite™ color technology`，以及 X-Rite 頁面的 `1.2.5 X-Rite™ Colors`，三個字串的 Unicode 碼位均正確。
- 全部 47 頁的清單名稱與畫面首行／固定前綴核對通過。實機文字驗證腳本為 `build-output/verify_unicode.py`。


## RGB 標題在 Text On／Off 間一致（2026-10-01）

修正 API 的隱藏文字標題組合：直接依目前測試及顏色產生標題，不再把清單的預設紅色完整標題與目前顏色重複串接。測試 ID、清單名稱、設定與原有畫面渲染不變。

在重新編譯的正式 x64 Release 程式執行 `test_rgb_titles_match_with_text_on_and_off`，核對 ColorPatches、ColorPatchesFull 與 ColorPatchesMAX，四種 RGBW 顏色及 Text On／Off，共 24 組狀態。所有標題均符合完整預期字串，色彩及文字設定均一致。正式程式啟動驗證入口為 `build-output/verify_rgb_titles.py`；Client 不需修改。
