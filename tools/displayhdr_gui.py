"""DisplayHDR LAN remote control, using Qt Widgets and the existing HTTP client."""
import json
import sys
import threading

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QPushButton, QSpinBox, QTextEdit,
                               QVBoxLayout, QWidget)
from displayhdr_remote import DisplayHDRRemoteClient


class RemoteWindow(QMainWindow):
    completed = Signal(str, object, str)

    def __init__(self, client_factory=DisplayHDRRemoteClient):
        super().__init__()
        self.client_factory = client_factory
        self.client = None
        self.busy = False
        self.connected = False
        self.closed = False
        self.held = None
        self.pressed = {}
        self.control_used = False
        self.setWindowTitle("DisplayHDR 遙控器")
        self.resize(760, 740)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        connection = QHBoxLayout()
        self.host = QLineEdit()
        self.host.setPlaceholderText("Host IP，例如 192.168.1.107")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(8765)
        self.connect_button = QPushButton("連線／重新查詢")
        self.connect_button.clicked.connect(self.connect_host)
        for widget in (QLabel("Host"), self.host, QLabel("連接埠"), self.port, self.connect_button):
            connection.addWidget(widget)
        layout.addLayout(connection)
        self.connection_status = QLabel("尚未連線")
        self.connection_status.setWordWrap(True)
        layout.addWidget(self.connection_status)
        self.controls = QWidget()
        controls = QVBoxLayout(self.controls)
        controls.setContentsMargins(0, 0, 0, 0)
        choose = QHBoxLayout()
        self.tests = QComboBox()
        self.tests.setMinimumContentsLength(30)
        select = QPushButton("切換測試")
        select.clicked.connect(lambda: self.dispatch("set_state", test=self.tests.currentData()))
        choose.addWidget(self.tests, 1)
        choose.addWidget(select)
        controls.addLayout(choose)
        body = QHBoxLayout()
        arrows = QGroupBox("方向控制")
        grid = QGridLayout(arrows)
        self.buttons = {}
        for key, label, row, column in (("Up", "↑ 上", 0, 1), ("Left", "← 上一項", 1, 0),
                                         ("Right", "下一項 →", 1, 2), ("Down", "↓ 下", 2, 1)):
            button = self.button(key, label)
            if key in ("Up", "Down"):
                button.pressed.connect(lambda k=key: self.start_hold(k))
                button.released.connect(self.stop_hold)
            grid.addWidget(button, row, column)
        self.shift = QCheckBox("Shift：上下以原版加大步進調整")
        grid.addWidget(self.shift, 3, 0, 1, 3)
        body.addWidget(arrows)
        functions = QGroupBox("功能控制")
        grid = QGridLayout(functions)
        actions = (("Space", "空白鍵：說明文字"), ("Control", "Ctrl：字幕"),
                   ("C", "C：Cool-down"), ("Home", "Home：Start Screen"),
                   ("P", "P：暫停／繼續"), ("A", "A：自動換色"),
                   ("AltEnter", "Alt＋Enter：全螢幕"), ("Escape", "Esc：離開全螢幕"))
        for index, (key, label) in enumerate(actions):
            grid.addWidget(self.button(key, label), index // 2, index % 2)
        body.addWidget(functions, 1)
        controls.addLayout(body)
        jump = QGroupBox("測試跳轉：數字鍵與 Shift＋數字鍵")
        grid = QGridLayout(jump)
        for index in range(10):
            grid.addWidget(self.button(str(index), str(index)), 0, index)
        for index in range(1, 6):
            grid.addWidget(self.button(f"Shift+{index}", f"Shift＋{index}"), 1, index)
        controls.addWidget(jump)
        extra = QHBoxLayout()
        for key, label in (("Comma", ", 棋盤格−"), ("Period", ". 棋盤格＋"),
                           ("Minus", "− 換色時間"), ("Plus", "＋ 換色時間"),
                           ("LeftBracket", "[ 白階−"), ("RightBracket", "] 白階＋")):
            extra.addWidget(self.button(key, label))
        controls.addLayout(extra)
        controls.addWidget(QLabel("上下可長按；各操作僅在原版支援的測試生效。鍵盤控制僅在此視窗取得焦點時啟用。"))
        layout.addWidget(self.controls)
        self.controls.setEnabled(False)
        self.title = QLabel("目前測試：—")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.summary = QLabel("設定：—")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(150)
        layout.addWidget(self.details, 1)
        self.completed.connect(self.finished)
        self.poll = QTimer(self)
        self.poll.setInterval(1000)
        self.poll.timeout.connect(lambda: self.dispatch("get_state"))
        self.poll.start()
        self.repeat = QTimer(self)
        self.repeat.timeout.connect(self.repeat_hold)
        QApplication.instance().installEventFilter(self)

    def button(self, key, label):
        button = QPushButton(label)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setMinimumHeight(32)
        self.buttons[key] = button
        if key not in ("Up", "Down"):
            button.clicked.connect(lambda: self.send_key(key))
        return button

    def connect_host(self):
        if self.busy:
            return
        host = self.host.text().strip()
        if not host or any(c in host for c in "/?# "):
            self.connection_status.setText("請輸入 Host IP 或主機名稱，不含 http:// 或連接埠。")
            return
        self.stop_hold()
        self.connected = False
        self.controls.setEnabled(False)
        self.client = self.client_factory(f"http://{host}:{self.port.value()}")
        self.dispatch("connect")

    def dispatch(self, command, **fields):
        if self.busy or self.closed or (command != "connect" and not self.connected):
            if self.busy and command in ("key", "set_state"):
                self.connection_status.setText("Host 忙碌中，此操作未送出；請待回覆後再操作。")
            return False
        self.busy = True
        self.connect_button.setEnabled(False)
        client = self.client

        def work():
            try:
                if command == "connect":
                    result = client.request("catalog")
                    if result.get("ok"):
                        state = client.request("get_state")
                        result = {**state, "catalog": result["catalog"]}
                else:
                    result = client.request(command, **fields)
                if result.get("ok") and command in ("key", "set_state"):
                    if result.get("state", {}).get("lastSetRequestId") != result.get("id"):
                        raise ValueError("Host 回讀的操作識別值不符。")
                self.completed.emit(command, result, "")
            except Exception as error:
                if not self.closed:
                    self.completed.emit(command, None, str(error))

        threading.Thread(target=work, daemon=True).start()
        return True

    def finished(self, command, result, error):
        if self.closed:
            return
        self.busy = False
        self.connect_button.setEnabled(True)
        if error or not result.get("ok"):
            self.stop_hold()
            self.connected = False
            self.controls.setEnabled(False)
            message = error or json.dumps(result.get("error"), ensure_ascii=False)
            self.connection_status.setText(f"狀態未確認，操作已停用。請連線／重新查詢；指令不會自動重送。\n{message}")
            return
        if command == "connect":
            self.tests.clear()
            for test in result["catalog"]["tests"]:
                self.tests.addItem(f"{test['title'] or test['id']}  [{test['id']}]", test["id"])
            self.connected = True
            self.controls.setEnabled(True)
            self.setFocus()
        state = result["state"]
        self.connection_status.setText("已連線，已讀回 Host 狀態")
        self.title.setText(f"目前測試：{state['test']['title']}  [{state['test']['id']}]")
        settings = state["settings"]
        effective = state.get("effective", {})
        nits = effective.get("nitsText") or effective.get("nits")
        flag = lambda key: "開" if settings.get(key) else "關"
        self.summary.setText(f"Nits（程式值）：{nits if nits is not None else '—'}　"
                             f"文字：{flag('textVisible')}　字幕：{flag('subtitlesVisible')}　"
                             f"暫停：{flag('paused')}　顏色：{settings.get('color', '—')}")
        index = self.tests.findData(state["test"]["id"])
        if command != "get_state" and index >= 0:
            self.tests.setCurrentIndex(index)
        shown = {key: state.get(key) for key in ("settings", "effective", "timing", "presentation", "lastSetRequestId")}
        self.details.setPlainText(json.dumps(shown, ensure_ascii=False, indent=2))

    def send_key(self, key):
        return self.dispatch("key", key=key)

    def start_hold(self, key):
        if not self.connected:
            return
        self.held = key
        self.repeat.setInterval(400)
        self.repeat.start()
        self.repeat_hold(first=True)

    def repeat_hold(self, first=False):
        if self.held:
            shift = self.shift.isChecked() or bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
            self.send_key(("Shift+" if shift else "") + self.held)
            if not first:
                self.repeat.setInterval(100)

    def stop_hold(self):
        self.repeat.stop()
        self.held = None

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.Type.WindowDeactivate and watched == self:
            self.stop_hold()
            self.pressed.clear()
            self.control_used = False
        if kind not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) or not self.isActiveWindow():
            return False
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QSpinBox, QComboBox)) or not self.connected:
            return False
        key = event.key()
        if event.isAutoRepeat():
            return True
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if kind == QEvent.Type.KeyPress and ctrl and key != Qt.Key.Key_Control:
            self.control_used = True
            return False
        names = {Qt.Key.Key_Up: "Up", Qt.Key.Key_Down: "Down", Qt.Key.Key_Left: "Left",
                 Qt.Key.Key_Right: "Right", Qt.Key.Key_PageUp: "PageUp", Qt.Key.Key_PageDown: "PageDown",
                 Qt.Key.Key_Space: "Space", Qt.Key.Key_Control: "Control", Qt.Key.Key_C: "C",
                 Qt.Key.Key_Home: "Home", Qt.Key.Key_P: "P", Qt.Key.Key_Pause: "Pause", Qt.Key.Key_A: "A",
                 Qt.Key.Key_Escape: "Escape", Qt.Key.Key_Period: "Period", Qt.Key.Key_Comma: "Comma",
                 Qt.Key.Key_Plus: "Plus", Qt.Key.Key_Equal: "Plus", Qt.Key.Key_Minus: "Minus",
                 Qt.Key.Key_BracketLeft: "LeftBracket", Qt.Key.Key_BracketRight: "RightBracket"}
        name = names.get(key)
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            name = chr(key)
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                name = "Shift+" + name
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.AltModifier:
            name = "AltEnter"
        if name and not name.startswith("Shift+") and name not in ("Up", "Down", "Control", "AltEnter") and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            name = "Shift+" + name
        if kind == QEvent.Type.KeyPress:
            if name:
                self.pressed[key] = name
                if name in ("Up", "Down"):
                    self.start_hold(name)
                return True
        else:
            name = self.pressed.pop(key, None)
            if name in ("Up", "Down"):
                self.stop_hold()
            elif name == "Control" and self.control_used:
                self.control_used = False
            elif name:
                self.send_key(name)
            return name is not None
        return False

    def closeEvent(self, event):
        self.closed = True
        self.stop_hold()
        self.poll.stop()
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    window = RemoteWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
