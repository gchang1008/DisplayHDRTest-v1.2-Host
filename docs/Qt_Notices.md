# Qt／PySide6 元件與授權

本 Client 使用未修改的 PySide6 Essentials、Shiboken6 與 Qt 6.11.1 動態函式庫，採 LGPLv3 選項。應用程式透過 Python 匯入與 DLL 動態載入，Qt 元件可在保留介面相容性的前提下替換；不限制為偵錯這些元件修改而進行的逆向工程。

隨包提供 `licenses/Qt` 中的 LGPLv3、GPLv3 及 Qt GPL exception 文件，與原始 wheel 的 METADATA／授權文件。各檔來源與 SHA-256 記錄於 manifest.json；Microsoft Runtime DLL 與 Python runtime 保留官方發行版本。

對應原始碼：

- [PySide6／Shiboken6 v6.11.1](https://code.qt.io/cgit/pyside/pyside-setup.git/tree/?h=v6.11.1)
- [Qt Base v6.11.1](https://code.qt.io/cgit/qt/qtbase.git/tree/?h=v6.11.1)，包含 QtCore／QtGui／QtWidgets／QtTest，以及各第三方元件的著作權、授權與 qt_attribution.json。
- [Qt 官方原始碼下載](https://download.qt.io/official_releases/qt/6.11/6.11.1/single/)

原專案授權見 `LICENSE-DisplayHDR.txt`；Python 及隨附元件授權見 `runtime/LICENSE.txt`。
