"""Bring only the managed renderer forward and conservatively inspect overlap.

Win32 references: SetForegroundWindow, SetWindowPos, GetWindow,
SetThreadDpiAwarenessContext, and DwmGetWindowAttribute (Microsoft Learn).
This is a window-state check, not proof of the monitor's optical output.
"""
import argparse
import ctypes as C
from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HOST_CLASS = 'DisplayHDRComplianceTestsWindowClass'
HWND, U32, I32 = C.c_void_p, C.c_uint32, C.c_int32


class Rect(C.Structure):
    _fields_ = [('left', I32), ('top', I32), ('right', I32), ('bottom', I32)]


class Point(C.Structure):
    _fields_ = [('x', I32), ('y', I32)]


class GuiThreadInfo(C.Structure):
    _fields_ = [('cbSize', U32), ('flags', U32), ('hwndActive', HWND), ('hwndFocus', HWND),
                ('hwndCapture', HWND), ('hwndMenuOwner', HWND), ('hwndMoveSize', HWND),
                ('hwndCaret', HWND), ('rcCaret', Rect)]


class NativeWindowApi:
    def __init__(self):
        if os.name != 'nt':
            raise OSError('Windows is required')
        self.u = C.WinDLL('user32', use_last_error=True)
        self.dwm = C.WinDLL('dwmapi')
        self.callback_type = C.WINFUNCTYPE(I32, HWND, C.c_ssize_t)
        declarations = {
            'EnumWindows': ([self.callback_type, C.c_ssize_t], I32),
            'GetWindow': ([HWND, U32], HWND),
            'GetForegroundWindow': ([], HWND),
            'GetWindowThreadProcessId': ([HWND, C.POINTER(U32)], U32),
            'GetClassNameW': ([HWND, C.c_wchar_p, I32], I32),
            'GetWindowTextW': ([HWND, C.c_wchar_p, I32], I32),
            'GetWindowLongPtrW': ([HWND, I32], C.c_ssize_t),
            'IsWindowVisible': ([HWND], I32), 'IsIconic': ([HWND], I32),
            'GetWindowRect': ([HWND, C.POINTER(Rect)], I32),
            'GetClientRect': ([HWND, C.POINTER(Rect)], I32),
            'ClientToScreen': ([HWND, C.POINTER(Point)], I32),
            'SetThreadDpiAwarenessContext': ([HWND], HWND),
            'ShowWindow': ([HWND, I32], I32),
            'SetWindowPos': ([HWND, HWND, I32, I32, I32, I32, U32], I32),
            'SetForegroundWindow': ([HWND], I32),
            'GetGUIThreadInfo': ([U32, C.POINTER(GuiThreadInfo)], I32),
            'AttachThreadInput': ([U32, U32, I32], I32),
            'SetFocus': ([HWND], HWND),
        }
        for name, (arguments, result) in declarations.items():
            getattr(self.u, name).argtypes, getattr(self.u, name).restype = arguments, result
        self.kernel = C.WinDLL('kernel32')
        self.kernel.GetCurrentThreadId.argtypes, self.kernel.GetCurrentThreadId.restype = [], U32
        self.dwm.DwmGetWindowAttribute.argtypes = [HWND, U32, C.c_void_p, U32]
        self.dwm.DwmGetWindowAttribute.restype = I32

    @staticmethod
    def check(value):
        if not value:
            raise C.WinError(C.get_last_error())

    @contextmanager
    def coordinates(self):
        previous = self.u.SetThreadDpiAwarenessContext(HWND(-4))  # Per-monitor aware V2.
        self.check(previous)
        try:
            yield
        finally:
            self.check(self.u.SetThreadDpiAwarenessContext(previous))

    def windows(self):
        handles = []

        @self.callback_type
        def collect(hwnd, parameter):
            handles.append(hwnd)
            return 1

        self.check(self.u.EnumWindows(collect, 0))
        return handles

    def identity(self, hwnd):
        pid, name = U32(), C.create_unicode_buffer(256)
        self.check(self.u.GetWindowThreadProcessId(hwnd, C.byref(pid)))
        self.check(self.u.GetClassNameW(hwnd, name, len(name)))
        return pid.value, name.value

    def above(self, hwnd):
        handles, seen = [], {hwnd}
        while hwnd := self.u.GetWindow(hwnd, 3):  # GW_HWNDPREV.
            if hwnd in seen or len(handles) >= 10000:
                raise RuntimeError('Window order changed during inspection')
            seen.add(hwnd)
            handles.append(hwnd)
        return handles

    def foreground(self):
        return self.u.GetForegroundWindow()

    def info(self, hwnd, client=False):
        pid, name = self.identity(hwnd)
        title, rect, cloaked = C.create_unicode_buffer(4096), Rect(), U32()
        self.u.GetWindowTextW(hwnd, title, len(title))
        if self.dwm.DwmGetWindowAttribute(hwnd, 9, C.byref(rect), C.sizeof(rect)) != 0:
            self.check(self.u.GetWindowRect(hwnd, C.byref(rect)))
        cloak_status = self.dwm.DwmGetWindowAttribute(hwnd, 14, C.byref(cloaked), C.sizeof(cloaked))
        row = {'pid': pid, 'class': name, 'title': title.value,
               'visible': bool(self.u.IsWindowVisible(hwnd)), 'minimized': bool(self.u.IsIconic(hwnd)),
               'cloaked': bool(cloaked.value) if cloak_status == 0 else None,
               'topmost': bool(self.u.GetWindowLongPtrW(hwnd, -20) & 8),
               'rect': [rect.left, rect.top, rect.right, rect.bottom]}
        if client:
            self.check(self.u.GetClientRect(hwnd, C.byref(rect)))
            first, last = Point(rect.left, rect.top), Point(rect.right, rect.bottom)
            self.check(self.u.ClientToScreen(hwnd, C.byref(first)))
            self.check(self.u.ClientToScreen(hwnd, C.byref(last)))
            row['clientRect'] = [first.x, first.y, last.x, last.y]
        return row

    def restore(self, hwnd):
        self.u.ShowWindow(hwnd, 9)  # SW_RESTORE; return value is prior visibility.

    def raise_window(self, hwnd):
        self.check(self.u.SetWindowPos(hwnd, HWND(0), 0, 0, 0, 0, 0x43))

    def keyboard_focused(self, hwnd):
        pid, info = U32(), GuiThreadInfo()
        thread = self.u.GetWindowThreadProcessId(hwnd, C.byref(pid))
        self.check(thread)
        info.cbSize = C.sizeof(info)
        self.check(self.u.GetGUIThreadInfo(thread, C.byref(info)))
        return info.hwndFocus == hwnd

    def set_foreground(self, hwnd):
        requested = bool(self.u.SetForegroundWindow(hwnd))
        if self.foreground() == hwnd and self.keyboard_focused(hwnd):
            return requested
        pid = U32()
        current_thread = self.kernel.GetCurrentThreadId()
        threads = []
        for window in (self.foreground(), hwnd):
            if window:
                thread = self.u.GetWindowThreadProcessId(window, C.byref(pid))
                self.check(thread)
                if thread != current_thread and thread not in threads:
                    threads.append(thread)
        with ExitStack() as stack:
            for thread in threads:
                self.check(self.u.AttachThreadInput(current_thread, thread, True))
                stack.callback(lambda tid: self.check(self.u.AttachThreadInput(current_thread, tid, False)), thread)
            requested = bool(self.u.SetForegroundWindow(hwnd))
            self.u.SetFocus(hwnd)  # A null return can mean there was no previous focus.
            return requested

    def pin_window(self, hwnd):
        self.check(self.u.SetWindowPos(hwnd, HWND(-1), 0, 0, 0, 0, 0x53))

    def unpin_window(self, hwnd):
        self.check(self.u.SetWindowPos(hwnd, HWND(-2), 0, 0, 0, 0, 0x13))


def overlaps(first, second):
    return (min(first[2], second[2]) > max(first[0], second[0]) and
            min(first[3], second[3]) > max(first[1], second[1]))


class WindowPresentation:
    def __init__(self, api=None):
        self.isolated = api is None
        self.api = api if api is not None else NativeWindowApi()

    def _main(self, pid):
        if type(pid) is not int or not 0 < pid <= 0xFFFFFFFF:
            raise ValueError('A valid renderer PID is required')
        matches = []
        for hwnd in self.api.windows():
            try:
                if self.api.identity(hwnd) == (pid, HOST_CLASS):
                    matches.append(hwnd)
            except OSError:
                continue  # A different window may disappear during enumeration.
        if len(matches) != 1:
            raise RuntimeError('Exactly one renderer main window must match its PID and class')
        return matches[0]

    def _verify(self, hwnd, pid):
        if self.api.identity(hwnd) != (pid, HOST_CLASS):
            raise RuntimeError('Renderer window identity changed')

    def _inspect(self, hwnd, pid):
        self._verify(hwnd, pid)
        host = self.api.info(hwnd, client=True)
        blockers, errors = [], []
        for other in self.api.above(hwnd):
            try:
                row = self.api.info(other)
                if row['visible'] and not row['minimized'] and row['cloaked'] is not True and overlaps(
                        host['clientRect'], row['rect']):
                    blockers.append(row)
            except OSError as exc:
                errors.append(str(exc))
        self._verify(hwnd, pid)
        foreground = self.api.foreground() == hwnd
        rect = host['clientRect']
        topmost = host.get('topmost', False)
        try:
            focused = self.api.keyboard_focused(hwnd)
        except OSError as exc:
            focused = False
            errors.append(str(exc))
        unobstructed = (host['visible'] and not host['minimized'] and host['cloaked'] is False
                        and (foreground or topmost)
                        and rect[2] > rect[0] and rect[3] > rect[1] and not blockers and not errors)
        return {'checkedAt': time.time(), 'pid': pid, 'hwnd': hwnd, 'foreground': foreground, 'keyboardFocused': focused,
                'visible': host['visible'], 'minimized': host['minimized'], 'clientRect': rect,
                'topmost': topmost,
                'possibleObstructions': blockers, 'inspectionErrors': errors, 'unobstructed': unobstructed}

    def inspect(self, pid):
        with self.api.coordinates():
            return self._inspect(self._main(pid), pid)

    def bring_front(self, pid, keep_on_top=False):
        if self.isolated:
            if type(pid) is not int or not 0 < pid <= 0xFFFFFFFF:
                raise ValueError('A valid renderer PID is required')
            command = [sys.executable, '-B', str(Path(__file__).resolve()), '--pid', str(pid)]
            if keep_on_top:
                command.append('--keep-on-top')
            try:
                completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                           timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError('DisplayHDR foreground operation timed out after 5 seconds; current output retained.') from exc
            result = json.loads(completed.stdout)
            if completed.returncode or not isinstance(result, dict) or result.get('pid') != pid:
                error = result.get('error', 'Renderer window could not be verified') if isinstance(result, dict) else 'Invalid window worker response'
                raise RuntimeError(str(error)[:1024])
            return result
        with self.api.coordinates():
            hwnd = self._main(pid)
            host = self.api.info(hwnd, client=True)
            if not host['visible'] or host['minimized']:
                self._verify(hwnd, pid)
                self.api.restore(hwnd)
            self._verify(hwnd, pid)
            self.api.raise_window(hwnd)
            self._verify(hwnd, pid)
            if keep_on_top:
                self._verify(hwnd, pid)
                self.api.pin_window(hwnd)
            self._verify(hwnd, pid)
            requested = self.api.set_foreground(hwnd)
            result = self._inspect(hwnd, pid)
            result['foregroundRequestAccepted'] = requested
            result['verificationTopmostRequested'] = keep_on_top
            return result

    def release(self, pid):
        with self.api.coordinates():
            hwnd = self._main(pid)
            self._verify(hwnd, pid)
            self.api.unpin_window(hwnd)
            return self._inspect(hwnd, pid)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--keep-on-top', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(WindowPresentation(NativeWindowApi()).bring_front(args.pid, args.keep_on_top)))
    except Exception as exc:
        print(json.dumps({'error': str(exc)[:1024]}))
        raise SystemExit(1)
