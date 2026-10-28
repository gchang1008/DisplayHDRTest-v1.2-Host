"""CCD display selection; persistent selection requires manual mode.

Layouts/flags follow Microsoft wingdi.h and Query/SetDisplayConfig documentation.
Timed trials restore in finally on normal Python errors; persistent selection
keeps the current output on success or failure. No scheduler or HDR/pattern changes.
"""

import ctypes as C
import json
import os
import time
from dataclasses import dataclass

U32, I32 = C.c_uint32, C.c_int32
QDC_ALL_PATHS, QDC_ONLY_ACTIVE_PATHS = 1, 2
QDC_DATABASE_CURRENT = 4
SDC_USE_SUPPLIED_DISPLAY_CONFIG = 0x20
SDC_VALIDATE, SDC_APPLY, SDC_ALLOW_CHANGES = 0x40, 0x80, 0x400
SDC_NO_OPTIMIZATION = 0x100
SDC_SAVE_TO_DATABASE = 0x200
INVALID_MODE = 0xFFFFFFFF


class Luid(C.Structure):
    _fields_ = [('low', U32), ('high', I32)]


class Rational(C.Structure):
    _fields_ = [('numerator', U32), ('denominator', U32)]


class Point(C.Structure):
    _fields_ = [('x', I32), ('y', I32)]


class Region(C.Structure):
    _fields_ = [('width', U32), ('height', U32)]


class Source(C.Structure):
    _fields_ = [('adapter', Luid), ('id', U32), ('modeIndex', U32), ('status', U32)]


class Target(C.Structure):
    _fields_ = [('adapter', Luid), ('id', U32), ('modeIndex', U32),
                ('technology', U32), ('rotation', U32), ('scaling', U32),
                ('refresh', Rational), ('scanline', U32), ('available', I32),
                ('status', U32)]


class Path(C.Structure):
    _fields_ = [('source', Source), ('target', Target), ('flags', U32)]


class SourceMode(C.Structure):
    _fields_ = [('width', U32), ('height', U32), ('pixelFormat', U32), ('position', Point)]


class Signal(C.Structure):
    _fields_ = [('pixelRate', C.c_uint64), ('hSync', Rational), ('vSync', Rational),
                ('activeSize', Region), ('totalSize', Region),
                ('videoStandard', U32), ('scanline', U32)]


class ModeData(C.Union):
    _fields_ = [('source', SourceMode), ('signal', Signal)]


class Mode(C.Structure):
    _fields_ = [('type', U32), ('id', U32), ('adapter', Luid), ('data', ModeData)]


class Header(C.Structure):
    _fields_ = [('type', U32), ('size', U32), ('adapter', Luid), ('id', U32)]


class TargetName(C.Structure):
    _fields_ = [('header', Header), ('flags', U32), ('technology', U32),
                ('manufacturer', C.c_uint16), ('product', C.c_uint16),
                ('connector', U32), ('name', C.c_uint16 * 64),
                ('devicePath', C.c_uint16 * 128)]


def key(endpoint):
    return f'{endpoint.adapter.high & 0xFFFFFFFF:08X}:{endpoint.adapter.low:08X}/{endpoint.id}'


def clone(value):
    return type(value).from_buffer_copy(bytes(value))


@dataclass
class Snapshot:
    paths: list
    modes: list
    topology: int | None = None


class WindowsApi:
    def __init__(self):
        if os.name != 'nt':
            raise OSError('Windows is required')
        if (C.sizeof(Path), C.sizeof(Mode), C.sizeof(TargetName)) != (72, 64, 420):
            raise RuntimeError('Unexpected CCD structure layout')
        self.dll = C.WinDLL('user32')
        self.dll.GetDisplayConfigBufferSizes.argtypes = [U32, C.POINTER(U32), C.POINTER(U32)]
        self.dll.QueryDisplayConfig.argtypes = [U32, C.POINTER(U32), C.POINTER(Path),
                                                C.POINTER(U32), C.POINTER(Mode), C.c_void_p]
        self.dll.SetDisplayConfig.argtypes = [U32, C.POINTER(Path), U32, C.POINTER(Mode), U32]
        self.dll.DisplayConfigGetDeviceInfo.argtypes = [C.POINTER(Header)]
        for name in ('GetDisplayConfigBufferSizes', 'QueryDisplayConfig',
                     'SetDisplayConfig', 'DisplayConfigGetDeviceInfo'):
            getattr(self.dll, name).restype = I32

    @staticmethod
    def check(code):
        if code:
            raise OSError(code, f'Windows CCD error {code}')

    def query(self, flags):
        for _ in range(3):
            count, mode_count = U32(), U32()
            self.check(self.dll.GetDisplayConfigBufferSizes(flags, C.byref(count), C.byref(mode_count)))
            paths, modes = (Path * count.value)(), (Mode * mode_count.value)()
            topology = U32() if flags == QDC_DATABASE_CURRENT else None
            code = self.dll.QueryDisplayConfig(flags, C.byref(count), paths,
                                               C.byref(mode_count), modes,
                                               C.byref(topology) if topology is not None else None)
            if code == 122:
                continue
            self.check(code)
            return Snapshot([clone(p) for p in paths[:count.value]],
                            [clone(m) for m in modes[:mode_count.value]],
                            topology.value if topology is not None else None)
        raise RuntimeError('Display configuration changed during all three queries')

    def device_path(self, path):
        name = TargetName()
        name.header = Header(2, C.sizeof(TargetName), path.target.adapter, path.target.id)
        self.check(self.dll.DisplayConfigGetDeviceInfo(C.byref(name.header)))
        return bytes(name.devicePath).decode('utf-16-le').split('\0', 1)[0]

    def set(self, snapshot, flags):
        paths = (Path * len(snapshot.paths))(*snapshot.paths)
        modes = (Mode * len(snapshot.modes))(*snapshot.modes) if snapshot.modes else None
        self.check(self.dll.SetDisplayConfig(len(snapshot.paths), paths,
                                             len(snapshot.modes), modes, flags))


class TrialError(RuntimeError):
    def __init__(self, report):
        self.report = report
        super().__init__(report.get('error') or report.get('restoreError') or 'Trial failed')


def describe(snapshot):
    rows = []
    for path in snapshot.paths:
        row = {'targetKey': key(path.target), 'sourceKey': key(path.source),
               'active': bool(path.flags & 1), 'available': bool(path.target.available),
               'sourceMode': None, 'targetMode': None,
               'targetProperties': {'rotation': path.target.rotation, 'scaling': path.target.scaling,
                                    'refreshNumerator': path.target.refresh.numerator,
                                    'refreshDenominator': path.target.refresh.denominator,
                                    'scanline': path.target.scanline}}
        index = path.source.modeIndex
        if index < len(snapshot.modes):
            mode = snapshot.modes[index]
            if mode.type == 1 and key(mode) == key(path.source):
                source = mode.data.source
                row['sourceMode'] = {'width': source.width, 'height': source.height,
                                     'pixelFormat': source.pixelFormat,
                                     'x': source.position.x, 'y': source.position.y}
        index = path.target.modeIndex
        if index < len(snapshot.modes):
            mode = snapshot.modes[index]
            if mode.type == 2 and key(mode) == key(path.target):
                signal = mode.data.signal
                row['targetMode'] = {'pixelRate': signal.pixelRate,
                                     'hSyncNumerator': signal.hSync.numerator,
                                     'hSyncDenominator': signal.hSync.denominator,
                                     'vSyncNumerator': signal.vSync.numerator,
                                     'vSyncDenominator': signal.vSync.denominator,
                                     'width': signal.activeSize.width, 'height': signal.activeSize.height,
                                     'scanline': signal.scanline}
        rows.append(row)
    return {'paths': rows}


def equivalent_paths(expected, actual):
    def properties(row):
        result = dict(row.get('targetProperties') or {})
        source, target = row.get('sourceMode'), row.get('targetMode')
        # SetDisplayConfig normalizes scaling to identity for equal source/target sizes.
        if source and target and all(source[k] == target[k] for k in ('width', 'height')):
            result['scaling'] = 1
        return result

    if (len({p['targetKey'] for p in expected['paths']}) != len(expected['paths']) or
            len({p['targetKey'] for p in actual['paths']}) != len(actual['paths'])):
        return False
    expected = {p['targetKey']: p for p in expected['paths']}
    actual = {p['targetKey']: p for p in actual['paths']}
    if expected.keys() != actual.keys():
        return False
    sources, reverse = {}, {}
    for target, before in expected.items():
        after = actual[target]
        if (before['sourceMode'] is None or after['sourceMode'] is None or
                any(before.get(k) != after.get(k) for k in
                    ('active', 'available', 'sourceMode', 'targetMode')) or
                properties(before) != properties(after)):
            return False
        old, new = before['sourceKey'], after['sourceKey']
        if old.rsplit('/', 1)[0] != new.rsplit('/', 1)[0]:
            return False
        if sources.setdefault(old, new) != new or reverse.setdefault(new, old) != old:
            return False
    return True


def encode_snapshot(snapshot, api):
    return {'paths': [bytes(p).hex() for p in snapshot.paths],
            'modes': [bytes(m).hex() for m in snapshot.modes],
            'devicePaths': [api.device_path(p) for p in snapshot.paths]}


class DisplayPaths:
    def __init__(self, api=None, sleep=time.sleep):
        self.api = api if api is not None else WindowsApi()
        self.sleep = sleep

    def inspect(self):
        def capture(snapshot):
            result = describe(snapshot)
            result['topology'] = snapshot.topology
            result['rawSnapshot'] = encode_snapshot(snapshot, self.api)
            for row, path in zip(result['paths'], snapshot.paths):
                row['monitorDevicePath'] = self.api.device_path(path)
                row['outputTechnology'] = path.target.technology
            return result

        report = {'capturedAt': time.time(),
                  'active': capture(self.api.query(QDC_ONLY_ACTIVE_PATHS))}
        try:
            report['database'] = capture(self.api.query(QDC_DATABASE_CURRENT))
            report['matchesDatabase'] = equivalent_paths(report['active'], report['database'])
        except OSError as exc:
            report['databaseError'] = str(exc)
        return report

    def trial(self, target_key, monitor_device_path, hold_seconds=15, observer=None, checkpoint=None,
              save_to_database=False, on_apply=None):
        report = {'targetKey': target_key, 'holdSeconds': hold_seconds,
                  'before': None, 'switched': None, 'after': None,
                  'restored': False, 'error': None, 'restoreError': None,
                  'validation': [], 'saveToDatabase': save_to_database}
        snapshot = None
        attempted = False

        def capture(snapshot):
            state = describe(snapshot)
            if observer:
                state['hostState'] = observer()
                json.dumps(state['hostState'])
            return state

        try:
            if type(save_to_database) is not bool or (save_to_database and hold_seconds is not None):
                raise ValueError('Saving display configuration requires manual confirmation mode')
            if hold_seconds is not None and (type(hold_seconds) is not int or not 5 <= hold_seconds <= 20):
                raise ValueError('hold_seconds must be an integer between 5 and 20')
            if not isinstance(monitor_device_path, str) or not monitor_device_path:
                raise ValueError('monitor_device_path is required')
            snapshot = self.api.query(QDC_ONLY_ACTIVE_PATHS)
            report['before'] = capture(snapshot)
            if not snapshot.paths or any(not path.flags & 1 for path in snapshot.paths):
                raise ValueError('Original active paths cannot be verified')
            original = snapshot.paths[0]
            if len(snapshot.paths) == 1 and key(original.target) == target_key:
                raise ValueError('Requested target is already active; no switch was applied')
            if any(path['sourceMode'] is None for path in report['before']['paths']):
                raise ValueError('An original source mode cannot be verified')
            database = self.api.query(QDC_DATABASE_CURRENT) if save_to_database else None
            if database is not None:
                report['databaseBefore'] = describe(database)
                if any(p['targetMode'] is None for p in report['before']['paths'] + report['databaseBefore']['paths']):
                    raise ValueError('Original active and saved target modes cannot be verified')
                if not equivalent_paths(describe(snapshot), report['databaseBefore']):
                    raise ValueError('Active and saved display configurations differ; no switch was applied')
            candidates = self.api.query(QDC_ALL_PATHS)
            matches = [p for p in candidates.paths
                       if key(p.target) == target_key and p.target.available
                       and bytes(p.target.adapter) == bytes(original.target.adapter)
                       and bytes(p.source.adapter) == bytes(original.source.adapter)
                       and self.api.device_path(p) == monitor_device_path]
            if not matches:
                raise ValueError('Target endpoint, source, availability or monitor device path mismatch')
            preferred = next((p.source for p in snapshot.paths if key(p.target) == target_key),
                             original.source)
            matches.sort(key=lambda p: (key(p.source) != key(preferred), p.source.id))
            flags = SDC_USE_SUPPLIED_DISPLAY_CONFIG | SDC_ALLOW_CHANGES
            seen = set()
            trial = None
            for candidate in matches:
                source_key = key(candidate.source)
                if source_key in seen:
                    continue
                seen.add(source_key)
                path = clone(candidate)
                path.flags = 1
                path.source.modeIndex = path.target.modeIndex = INVALID_MODE
                proposal = Snapshot([path], [])
                try:
                    self.api.set(proposal, flags | SDC_VALIDATE)
                except Exception as exc:
                    code = getattr(exc, 'winerror', None) or getattr(exc, 'errno', None)
                    report['validation'].append({'sourceKey': source_key, 'code': code})
                    if code != 1610:
                        raise
                else:
                    report['validation'].append({'sourceKey': source_key, 'code': 0})
                    trial = proposal
                    break
            if trial is None:
                raise OSError(1610, 'All candidate source configurations failed validation')
            if hold_seconds is None and checkpoint is not None:
                if save_to_database:
                    active_unchanged = equivalent_paths(describe(snapshot), describe(self.api.query(QDC_ONLY_ACTIVE_PATHS)))
                    database_unchanged = equivalent_paths(describe(database), describe(self.api.query(QDC_DATABASE_CURRENT)))
                    if not active_unchanged or not database_unchanged:
                        raise ValueError('Display configuration changed before saving the recovery snapshot')
                    checkpoint(snapshot, database)
                else:
                    checkpoint(snapshot)
            attempted = True
            if on_apply:
                on_apply()
            report['applyStartedAt'] = time.time()
            self.api.set(trial, flags | SDC_APPLY | SDC_NO_OPTIMIZATION |
                         (SDC_SAVE_TO_DATABASE if save_to_database else 0))
            report['applyCompletedAt'] = time.time()
            switched = self.api.query(QDC_ONLY_ACTIVE_PATHS)
            report['switched'] = capture(switched)
            switched = self.api.query(QDC_ONLY_ACTIVE_PATHS)
            report['switched']['paths'] = describe(switched)['paths']
            if (len(switched.paths) != 1 or not switched.paths[0].flags & 1
                    or key(switched.paths[0].target) != target_key
                    or bytes(switched.paths[0].source.adapter) != bytes(trial.paths[0].source.adapter)
                    or report['switched']['paths'][0]['sourceMode'] is None
                    or self.api.device_path(switched.paths[0]) != monitor_device_path):
                raise RuntimeError('Active display path does not match the requested endpoint')
            if save_to_database:
                report['databaseSelected'] = describe(self.api.query(QDC_DATABASE_CURRENT))
                if not equivalent_paths(report['switched'], report['databaseSelected']):
                    raise RuntimeError('Saved display configuration does not match the selected endpoint')
            if hold_seconds is not None:
                self.sleep(hold_seconds)
        except Exception as exc:
            report['error'] = f'{type(exc).__name__}: {exc}'
        finally:
            if attempted and hold_seconds is not None:
                try:
                    self.api.set(snapshot, SDC_APPLY | SDC_USE_SUPPLIED_DISPLAY_CONFIG | SDC_NO_OPTIMIZATION)
                    after = self.api.query(QDC_ONLY_ACTIVE_PATHS)
                    report['after'] = describe(after)
                    report['restored'] = equivalent_paths(describe(snapshot), report['after'])
                    if not report['restored']:
                        raise RuntimeError('Restored path/source mode does not match the original snapshot')
                    report['after'] = capture(after)
                except Exception as exc:
                    report['restoreError'] = f'{type(exc).__name__}: {exc}'
            if attempted and hold_seconds is None:
                report['waitingForConfirmation'] = True
        if report['error'] or report['restoreError']:
            raise TrialError(report)
        return report
