# 儲存庫拆分驗證（2026-10-01）

以下為 2026-10-01 的歷史驗證，不代表現行版本重新驗證；跨電腦連線的後續紀錄及現行操作見 [遠端 API](Remote_API.md)。

Host：17 項 HTTP、4 項按鍵、3 項封裝驗證通過；Visual Studio x64 Release 建置通過。

同機透過 HTTP API 完成實機控制，47 項測試可查詢；74 組遠端／本地按鍵之測試識別值及完整設定全部一致。原有 Host C++ 核心沒有因拆分改變。

封裝工具只產生 Host ZIP，runtime 來源及 SHA-256 固定。未在第二台電腦驗證防火牆與網路。

證據位於 build-output/split-*.log；這些產物不提交 Git。
