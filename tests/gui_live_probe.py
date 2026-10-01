"""Run with the extracted Client's Python against a live packaged Host."""
import json
from pathlib import Path
import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from displayhdr_gui import RemoteWindow
from displayhdr_remote import DisplayHDRRemoteClient

app = QApplication([])
window = RemoteWindow()
window.show()
window.activateWindow()
window.host.setText("127.0.0.1")
window.port.setValue(int(sys.argv[1]))


def wait(condition):
    end = time.monotonic() + 15
    while not condition() and time.monotonic() < end:
        QTest.qWait(10)
    assert condition(), window.connection_status.text()


def key(name):
    QTest.mouseClick(window.buttons[name], Qt.MouseButton.LeftButton)
    wait(lambda: not window.busy)
    assert window.connected, window.connection_status.text()
    return client.request()["state"]


try:
    window.connect_host()
    wait(lambda: window.connected and not window.busy)
    window.poll.stop()
    client = DisplayHDRRemoteClient(f"http://127.0.0.1:{sys.argv[1]}")
    assert window.tests.count() == 47
    state = client.request("set_state", test="ColorPatchesFull", settings={"color": "Red", "textVisible": True})
    assert state["ok"]
    assert key("Down")["settings"]["color"] == "Green"
    assert key("Down")["settings"]["color"] == "Blue"
    assert key("Space")["settings"]["textVisible"] is False
    assert key("Shift+4")["test"]["id"] == "SubTitleFlicker"
    before = client.request()["state"]["settings"]["subtitlesVisible"]
    assert key("Control")["settings"]["subtitlesVisible"] != before
    assert key("C")["test"]["id"] == "Cooldown"
    assert key("Home")["test"]["id"] == "StartOfTest"
    client.request("set_state", test="ActiveDimming", settings={"activeDimmingPq": 450, "textVisible": True})
    window.shift.setChecked(True)
    window.raise_()
    window.activateWindow()
    QTest.qWait(150)
    QTest.mousePress(window.buttons["Up"], Qt.MouseButton.LeftButton)
    end = time.monotonic() + .9
    while time.monotonic() < end:
        QTest.qWait(10)
    QTest.mouseRelease(window.buttons["Up"], Qt.MouseButton.LeftButton)
    wait(lambda: not window.busy)
    state = client.request()["state"]
    assert state["settings"]["activeDimmingPq"] >= 470, (state["settings"], window.connection_status.text())
    window.dispatch("get_state")
    wait(lambda: not window.busy)
    window.grab().save(sys.argv[2])
    print(json.dumps({"ok": True, "platform": app.platformName(), "tests": window.tests.count(),
                      "state": state, "python": sys.executable}, ensure_ascii=False))
finally:
    window.close()
