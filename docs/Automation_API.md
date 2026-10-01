# DisplayHDR 自動化 API

## 啟動與連線

以 `DisplayHDRComplianceTests.exe --api` 啟動。未加 `--api` 時不建立控制介面，原有鍵盤操作保留。

本機介面使用 Windows Named Pipe：`\\.\pipe\DisplayHDRTest-v1.2-<PID>`。每個程式實例使用自己的處理程序識別碼。另一台電腦透過新增的 HTTP 服務控制，啟動入口、Python 客戶端及操作方式見 [遠端 API 文件](Remote_API.md)。以下描述本機契約與兩種傳輸共用的設定／狀態語意。

在原始碼目錄執行以下 PowerShell 範例，路徑中的執行檔必須與 `.cso`、`.png` 資源放在同一個目錄：

```powershell
$displayHdrProcess = Start-Process -FilePath 'build-output\automation-x64-Release\DisplayHDRComplianceTests.exe' -ArgumentList '--api' -PassThru
python tools/displayhdr_api.py --pid $displayHdrProcess.Id --command catalog
python tools/displayhdr_api.py --pid $displayHdrProcess.Id --command set_state --test ColorPatchesFull --settings '{"color":"Blue","textVisible":false}'
python tools/displayhdr_api.py --pid $displayHdrProcess.Id
```

Python 客戶端只使用標準函式庫，適用 Windows；不同控制端可依下列契約自行實作。

## 通訊契約

- UTF-8 JSON，一行一個物件，以換行字元 `\n` 結束。
- `version` 必須為 `1`；`id` 使用字串，最長 128 字元，建議每次請求使用唯一值。回覆原樣帶回。
- 指令為 `catalog`、`get_state`、`set_state`、`key`。
- 請求最大 16 KiB。服務端同時接受一個連線，逐一處理請求，限制一個待處理請求。
- 讀寫／閒置逾時 10 秒，等待主執行緒完成請求逾時 5 秒；逾時會斷線。控制端可另設定較短逾時。
- 未知欄位、錯誤型別、超出範圍的值會被拒絕。整份設定驗證成功後才套用，無效請求不造成部分變更。

```json
{"version":1,"id":"query-1","command":"get_state"}
{"version":1,"id":"catalog-1","command":"catalog"}
{"version":1,"id":"blue-1","command":"set_state","test":"ColorPatches","settings":{"color":"Blue","textVisible":false}}
{"version":1,"id":"dimming-1","command":"set_state","test":"ActiveDimming","settings":{"activeDimmingPq":451,"textVisible":true}}
{"version":1,"id":"subtitle-1","command":"set_state","test":"SubTitleFlicker","settings":{"subtitlesVisible":false,"textVisible":false}}
```

成功回覆：`{"version":1,"id":"query-1","ok":true,"state":{...}}`。`catalog` 指令以 `catalog` 取代 `state`。

失敗回覆：`{"version":1,"id":"...","ok":false,"error":{"code":"...","message":"..."}}`。

錯誤碼包含 `invalid_request`、`invalid_json`、`unsupported_test`、`unsupported_setting`、`unknown_command`、`internal_error`。`message` 提供具體原因。超大訊息或連線逾時可能直接斷線而無 JSON 回覆。

逾時或斷線後，指令**可能已經生效**。重新連線，以 `get_state` 比對 `lastSetRequestId` 及完整設定後再決定是否重送；不要直接重送帶有 `restart:true` 的請求。

## 測試識別值與設定清單

### 原版按鍵操作

GUI 遙控器使用新增的 `key` 指令，例如：

```json
{"version":1,"id":"key-1","command":"key","key":"Down"}
{"version":1,"id":"key-2","command":"key","key":"Shift+Up"}
{"version":1,"id":"key-3","command":"key","key":"Shift+4"}
```

支援 `Up`, `Down`, `Left`, `Right`, `PageUp`, `PageDown`, `Space`, `Control`, `C`, `Home`, `P`, `Pause`, `A`, `Period`, `Comma`, `Plus`, `Minus`, `LeftBracket`, `RightBracket`, `Escape`, `AltEnter` 與 `0`–`9`。可加 `Shift+` 前綴，沿用原版 Shift 語意；Shift＋6–9 不切換測試。未支援的名稱／型別／額外欄位會在任何操作前拒絕。

每次請求代表一次按鍵操作，呼叫原版處理函式；不向系統注入鍵盤事件，不依賴 Host 視窗焦點。操作在原版 Update 開始前執行，回覆等到該次 Update／Render／Present 嘗試完成，格式與 set_state 相同，lastSetRequestId 記錄本次操作識別值。遠端 Shift 僅作用於本次操作，結束後保留本地 Shift 狀態。

相對操作不可安全重送，逾時後必須先查詢確認。無作用的按鍵仍成功回覆當前狀態；適用範圍、循環、步進、暫停及 Cooldown 特殊行為完全沿用原版函式。上下長按由 Client 依序送出個別請求。

### 指定測試與設定

`catalog.tests` 列出全部 47 個測試畫面，每個項目具有穩定的 `id`、畫面首行標題所對應的 `title` 與 `applicableSettings`。請使用 `id` 切換，不使用標題或顯示順序。8% 色塊為 `ColorPatches`，全畫面色塊為 `ColorPatchesFull`。

清單名稱是固定的選單標籤，並不代表目前設定。RGB 頁面使用預設紅色的完整首行標題；Flash 頁面使用預設 Off 標題。倒數秒數、亮度、漸層 RGB 數值及 Local Dimming 的 1-D／2-D 模式不加入固定標籤。切換後的實際標題與設定請查詢 `get_state`；文字顯示時可用 `test.displayedText` 核對畫面文字。

`catalog.settingSchema` 是機器可讀的型別、範圍、單位與列舉值；`catalog.settings` 是目前值；`startupDefaults` 是本次啟動時的原程式狀態。原程式部分校正欄位在首次進入測試前使用初始化哨兵值，可能不在 API 可寫範圍內；不可將整份啟動快照盲目回寫。

| 設定名稱 | 合法值／範圍 | 作用 |
| --- | --- | --- |
| `textVisible` | 布林值 | 說明文字顯示 |
| `subtitlesVisible` | 布林值 | Subtitle Flicker 字幕 |
| `paused` | 布林值 | 使用原有暫停行為，僅作用於原本支援暫停的測試 |
| `fullscreen` | 布林值 | 原有全螢幕切換 |
| `color` | `Red`, `Green`, `Blue`, `White` | 色塊選擇器；部分測試借用作白階／亮度選擇器 |
| `testingTier` | 400, 500, 600, 1000, 1400, 2000, 3000, 4000, 6000, 10000 | 測試等級 |
| `checkerboard` | `6x4`, `4x3`, `4x3-inverted` | 棋盤格 |
| `whiteLevel` | 50, 100, 200, 250, 300, 500, 700, 1000 | 709／X-Rite 參考白階 |
| `blackIndex` | 整數 0–4 | 0.5, 0.3, 0.1, 0.05, 0 Nits |
| `profileIndex` | 整數 0–`profileMaximumIndex` | 原有 Profile Curve 索引，最大值依螢幕而定 |
| `xriteIndex` | 整數 0–97 | X-Rite 色塊 |
| `xriteAuto` | 布林值 | X-Rite 自動換色 |
| `xriteInterval` | 0.001–float32 最大值，秒 | X-Rite 換色間隔 |
| `dimmingMode` | `1D`, `2D` | Local Dimming 圖樣 |
| `gradient` | `{"r":數值,"g":數值,"b":數值}` | Static Gradient；每個分量須為有限 float32 值 |
| `staticContrastPq` | 100–750 | HDR Static Contrast PQ 控制值 |
| `staticContrastSrgb` | 0–255 | SDR Static Contrast 控制值 |
| `activeDimmingPq` | 420–488 | Active Dimming PQ 控制值 |
| `activeDimmingDarkPq` | 208–292 | Active Dimming Dark PQ 控制值 |
| `calibrationMaxPq` | 0–1023 | HDR 最大亮度校正 |
| `calibrationFullFramePq` | 0–1023 | HDR 全畫面亮度校正 |
| `calibrationMinPq` | 0–1023 | HDR 最低亮度校正 |
| `calibrationMaxSrgb` | 0–255 | SDR 最大亮度校正 |
| `calibrationFullFrameSrgb` | 0–255 | SDR 全畫面亮度校正 |
| `calibrationMinSrgb` | 0–255 | SDR 最低亮度校正 |

PQ／sRGB 控制值維持原程式浮點型別，允許小數。校正 PQ 的 API 寫入範圍限制為 10 位元的 0–1023；原有鍵盤範圍未修改。

`settings.nits` 是額外的寫入別名，適用 `ActiveDimming`、`ActiveDimmingDark`、`StaticContrastRatio`、三個校正測試。使用原有 PQ／sRGB 換算，換算結果必須符合該欄位範圍；不得同時指定對應的原始控制值。其餘測試以索引／白階設定選擇，Nits 唯讀。

所有 25 個持續設定均可寫入及查詢，允許預先設定非當前測試的共用值。`applicableSettings` 指出目前模式真正使用的欄位，HDR／SDR 切換時會選用對應控制值。設定共用狀態不代表所有測試都受該設定影響。

`color` 在 `FullFrameSDRWhite` 與 `SharpeningFilter` 依序對應 80、160、240、320 Nits；在 `FullFrameSDRWhiteWithHDR` 對應螢幕報告峰值、600、1000、1400；在 `ToneMapSpike` 對應 350、700、1015、10000。這些名稱沿用原程式共用選擇器。

## 套用順序與重啟

`set_state` 的 `test`、`settings`、`restart` 均可省略，未指定設定保留原有狀態；原程式切換測試的初始化仍可能改變共用設定，以回覆快照為準。API 指定值於原有 Update 初始化後、Render 前套用。回覆等到這次套用與 Render／Present 嘗試完成。

指定相同測試不重新啟動。需重新開始暖機／倒數時使用 `restart:true`。重複相同 X-Rite 自動模式及間隔不重設倒數；變更間隔、啟動自動換色或重新進入測試時會套用指定間隔。

鍵盤輸入與 API 共用主執行緒狀態；沒有排他控制權。人工操作或自動換色可在回覆後改變狀態，量測前必須再次核對。

## 狀態快照與量測前核對

| 欄位 | 意義 |
| --- | --- |
| `test.id` | 當前測試的穩定識別值 |
| `test.title` / `titleSource` | 顯示文字存在時取得實際首行；隱藏時回傳原始定義與動態名稱。來源為 `rendered` 或 `definition` |
| `test.displayedText` | 擷取的測試標題／說明文字區塊，不是整張畫面所有文字的 OCR |
| `settings` / `applicableSettings` | 完整共用設定快照／當前適用欄位 |
| `lastSetRequestId` | 最近完成套用的設定請求識別值 |
| `stateVersion` | 測試、設定及受追蹤階段改變時遞增；逐畫格倒數不一定遞增 |
| `effective` | 原有換算的 Nits、控制碼、參考白階等；無單一亮度的多色／多階圖樣使用 `null` |
| `timing` | 原有倒數、等待完成條件及適用的閃爍階段 |
| `presentation` | 套用、提交、畫格識別值、資源有效性及視窗狀態 |
| `display` | HDR、尺寸、螢幕原始報告值、亮度滑桿比例、唯讀 back buffer 格式 |
| `metadata` | 原程式計算的 HDR metadata 原始欄位 |

`effective.nits` 是原程式內部的圖樣亮度參數；部分測試畫面會乘上 Windows 亮度滑桿比例，另以 `displayedNits` 回報對應數字。`nitsText` 依 `displayedNits` 格式化為兩位小數（Active Dimming Dark 三位）。控制值保留 float32 精度；精確核對以原始碼值及浮點容差進行，顯示文字以該格式核對。非單一亮度時數值為 `null`、文字為空字串。Flash／Rise-Fall 的 Nits 為亮相參數，當前相位另查 `timing.flashOn`。

`metadata.maxMastering` 是 Nits；`minMastering` 是 0.0001 Nits 單位；`maxCLL`、`maxFALL` 是 Nits。這些欄位表示程式的設定內容。

量測前至少核對：

1. `lastSetRequestId`、`test.id`、所需 `settings` 對應本次請求。
2. `presentation.applied`、`submitted`、`resourcesValid` 為真，且 `lastPresentResult` 為 `S_OK`（0）。
3. 需正常可見畫面時確認 `presented` 為真、`minimized` 為假、尺寸符合預期。
4. 有等待條件時確認 `timing.waitComplete`；動態測試另依原測試要求核對階段。

`submitted` 表示原程式 Present 成功；`presented` 再加上視窗可見且未最小化條件。它們不提供螢幕遮擋偵測、光學穩定、VSync 精確時間戳或量測設備觸發同步。這些需在實際量測環境驗證。

## Python 整合範例

```python
from displayhdr_api import DisplayHDRClient

with DisplayHDRClient(pid) as api:
    result = api.request("set_state", id="measurement-001", test="ColorPatchesFull",
                         settings={"color": "Blue", "textVisible": False})
    if not result["ok"]:
        raise RuntimeError(result["error"])
    state = api.request("get_state")["state"]
    assert state["lastSetRequestId"] == "measurement-001"
    assert state["test"]["id"] == "ColorPatchesFull"
    assert state["settings"]["color"] == "Blue"
    assert state["settings"]["textVisible"] is False
    assert state["presentation"]["presented"]
    assert state["timing"]["waitComplete"]
    # 後續在此串接量測設備 API，並保存本次 state 與量測結果。
```

## 建置

以 Visual Studio 2022 的 MSBuild、MSVC v142、Windows SDK 建置原有專案。`tools/build.ps1` 會在本機暫存目錄建置，避開 UNC 路徑的 manifest 工具限制，再將執行檔與資源複製至本儲存庫的 `build-output`。

```powershell
powershell -NoProfile -File tools/build.ps1 -Configuration Release -Platform x64
```

驗證範圍與限制見 [驗證報告](Automation_Verification.md)。
