#!/usr/bin/python
"""Separate, acknowledged native screensaver-only reload. Python 2.7 compatible."""
from __future__ import print_function
import sys
sys.dont_write_bytecode = True
import argparse
import hashlib
import json
import os
try:
    from pipes import quote
except ImportError:
    from shlex import quote
import select
import signal
import subprocess
import time

BASE = '@BASE@'
APP = 'com.webos.app.screensaver'
MAIN_QML = 'file:///usr/palm/applications/com.webos.app.screensaver/qml/main.qml'
CLOSE_METHOD = 'com.webos.applicationManager/closeByAppId'
LAUNCH_METHOD = 'com.webos.applicationManager/launch'
RUNNING_METHOD = 'com.webos.applicationManager/running'
FOREGROUND_METHOD = 'com.webos.applicationManager/getForegroundAppInfo'
CLOSE_PAYLOAD = {'id': APP}
LAUNCH_PAYLOAD = {'id': APP, 'spinner': False, 'noSplash': True, 'checkUpdateOnLaunch': False}

try:
    string_types = (basestring,)
except NameError:
    string_types = (str, bytes)


def require(value, message):
    if not value:
        raise RuntimeError(message)


def read(path):
    with open(path, 'rb') as stream:
        return stream.read()


def stamp(pid):
    try:
        raw = read('/proc/%s/stat' % pid)
        return raw.rsplit(')', 1)[1].split()[19]
    except (IOError, IndexError, ValueError):
        return None


def validate_payload(method, payload, schema_loader=None):
    if method not in (CLOSE_METHOD, LAUNCH_METHOD):
        raise ValueError('native method is not allowlisted')
    if method in (CLOSE_METHOD, LAUNCH_METHOD) and payload.get('id') != APP:
        raise ValueError('this tool controls only the native screensaver')
    if schema_loader is None:
        leaf = method.rsplit('/', 1)[1]
        path = '/etc/palm/schemas/sam/applicationManager.' + leaf + '.schema'
        schema = json.loads(read(path).decode('utf-8'))
    else:
        schema = schema_loader(method.rsplit('/', 1)[1])
    required = schema.get('required', [])
    properties = schema.get('properties', {})
    for key in required:
        if key not in payload:
            raise ValueError('native schema requires property: ' + key)
    for key, value in payload.items():
        if key not in properties:
            raise ValueError('native schema does not allow property: ' + key)
        expected = properties[key].get('type')
        matches = {
            'string': lambda x: isinstance(x, string_types),
            'boolean': lambda x: isinstance(x, bool),
            'integer': lambda x: isinstance(x, int) and not isinstance(x, bool),
            'number': lambda x: isinstance(x, (int, float)) and not isinstance(x, bool),
            'object': lambda x: isinstance(x, dict),
            'array': lambda x: isinstance(x, list),
        }
        if expected in matches and not matches[expected](value):
            raise ValueError('native schema expects %s for %s' % (expected, key))
        enum = properties[key].get('enum')
        if enum is not None and value not in enum:
            raise ValueError('native schema enum mismatch for ' + key)
    return True


def luna(method, payload):
    allowed = (RUNNING_METHOD, FOREGROUND_METHOD, CLOSE_METHOD, LAUNCH_METHOD)
    require(method in allowed, 'native method is not allowlisted')
    if method in (CLOSE_METHOD, LAUNCH_METHOD):
        require(payload.get('id') == APP, 'this tool controls only the native screensaver')
        validate_payload(method, payload)
    command = 'luna-send -w 5000 -n 1 %s %s' % (
        quote('luna://' + method),
        quote(json.dumps(payload, separators=(',', ':'))))
    process = subprocess.Popen(['script', '-q', '-e', '-c', command, '/dev/null'],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = []
    deadline = time.time() + 7.0
    fd = process.stdout.fileno()
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            process.terminate()
            raise RuntimeError('bounded PTY Luna request timed out: ' + method)
        ready, _, _ = select.select([fd], [], [], min(0.25, remaining))
        if ready:
            chunk = os.read(fd, 4096)
            if chunk:
                output.append(chunk)
            elif process.poll() is not None:
                break
        if process.poll() is not None:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
    returncode = process.poll()
    if returncode is None:
        process.terminate()
        raise RuntimeError('PTY Luna wrapper did not exit: ' + method)
    raw = b''.join(output).replace(b'\r', b'').strip()
    try:
        result = json.loads(raw.decode('utf-8'))
    except Exception as exc:
        raise RuntimeError('invalid native response for %s: %s; %s' %
                           (method, exc, raw[-1000:].decode('utf-8', 'replace')))
    if returncode != 0 or (method in (CLOSE_METHOD, LAUNCH_METHOD) and result.get('returnValue') is not True):
        raise RuntimeError('native request failed for %s: %s' % (method, json.dumps(result, sort_keys=True)))
    return result


def native_state(api=None):
    api = api or luna
    running = api(RUNNING_METHOD, {})
    foreground = api(FOREGROUND_METHOD, {})
    apps = running.get('running')
    require(isinstance(apps, list), 'native running-app response lacks a list')
    identities = []
    for app in apps:
        require(isinstance(app, dict) and 'id' in app and 'processid' in app,
                'native running-app entry lacks identity')
        pid = int(app['processid'])
        start = stamp(pid)
        require(start is not None, 'cannot read process start time for PID %s' % pid)
        identities.append({'id': app['id'], 'pid': pid, 'start': start})
    foreground_id = foreground.get('appId')
    require(isinstance(foreground_id, string_types), 'native foreground response lacks appId')
    return {'foreground': foreground_id, 'apps': identities}


def _screensaver(state):
    return [entry for entry in state['apps'] if entry['id'] == APP]


def _runner(app):
    pid = app['pid']
    require(stamp(pid) == app['start'], 'screensaver PID/starttime changed: %s' % pid)
    executable = os.readlink('/proc/%s/exe' % pid)
    require(executable == '/usr/bin/qml-runner', 'screensaver PID is not the expected qml-runner')
    raw = read('/proc/%s/cmdline' % pid)
    argv = raw.split(b'\x00')
    if argv and not argv[-1]:
        argv.pop()
    require(len(argv) >= 2, 'native qml-runner arguments are incomplete')
    try:
        params = json.loads(argv[1].decode('utf-8'))
    except Exception as exc:
        raise RuntimeError('native qml-runner parameters are not JSON: %s' % exc)
    require(params.get('appId') == APP and params.get('main') == MAIN_QML,
            'native qml-runner appId/main path mismatch')
    return raw, params


def _has_snapshot(value):
    if isinstance(value, dict):
        if value.get('snapshot') is True:
            return True
        return any(_has_snapshot(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_snapshot(item) for item in value)
    return False


def _check_overlay(mode):
    command = [sys.executable, os.path.join(BASE, 'overlay_runtime.py'), '--check']
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()
    require(process.returncode == 0, 'overlay preflight failed: ' + error.decode('utf-8', 'replace'))
    status = json.loads(output.decode('utf-8'))
    expected = 'original' if mode == 'original' else 'owned-ro'
    require(all(value == expected for value in status.get('mounts', {}).values()),
            'screensaver targets are not all in the requested %s state' % mode)
    require(status.get('disabled') is (mode == 'original'),
            'rollback marker does not match requested reload mode')
    return status


def _wait_for(predicate, timeout, interval=0.2):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    return last


def _wait_old_exit(old, api):
    def remaining():
        return [entry for entry in old if stamp(entry['pid']) == entry['start']]
    _wait_for(lambda: not remaining(), 0.8)
    # Inspect again before the exact PID/starttime-checked TERM fallback.
    survivors = remaining()
    term_errors = []
    for entry in survivors:
        raw, params = _runner(entry)
        digest = hashlib.sha256(raw).hexdigest()
        if stamp(entry['pid']) == entry['start']:
            raw_again, ignored = _runner(entry)
            require(hashlib.sha256(raw_again).hexdigest() == digest,
                    'screensaver command line changed before TERM')
            try:
                os.kill(entry['pid'], signal.SIGTERM)
            except OSError as exc:
                term_errors.append('%s: %s' % (entry['pid'], exc))
    gone = _wait_for(lambda: not remaining(), 6.0)
    require(not remaining(), 'native screensaver did not exit after close/TERM; no KILL escalation')
    return term_errors


def _wait_fresh(old, api, timeout=12.0):
    old_ids = set((entry['pid'], entry['start']) for entry in old)
    def fresh():
        current = native_state(api)
        candidates = [entry for entry in _screensaver(current)
                      if (entry['pid'], entry['start']) not in old_ids]
        return (current, candidates) if candidates else None
    result = _wait_for(fresh, timeout, 0.25)
    require(result is not None, 'no fresh native screensaver appeared before timeout')
    current, candidates = result
    require(len(candidates) == 1, 'expected exactly one fresh native screensaver process')
    return current, candidates


def _other_identities(state):
    return sorted((entry['id'], entry['pid'], entry['start'])
                  for entry in state['apps'] if entry['id'] != APP)


def _bounded_relaunch_recovery(api, old, foreground):
    try:
        current = native_state(api)
        if current['foreground'] != foreground:
            return {'attempted': False, 'reason': 'foreground changed; no recovery launch issued'}
        existing = _screensaver(current)
        if existing:
            return {'attempted': False, 'reason': 'screensaver process remains; no duplicate launch issued',
                    'processes': existing, 'rendered_mode_verified': False}
        attempted = True
        request_error = None
        try:
            api(LAUNCH_METHOD, LAUNCH_PAYLOAD)
        except Exception as exc:
            request_error = str(exc)
        deadline = time.time() + 12.0
        fresh = []
        while time.time() < deadline:
            current = native_state(api)
            fresh = [entry for entry in _screensaver(current)
                     if (entry['pid'], entry['start']) not in set((x['pid'], x['start']) for x in old)]
            if fresh:
                return {'attempted': attempted, 'request_error': request_error,
                        'fresh_processes': fresh, 'rendered_mode_verified': False}
            time.sleep(0.25)
        return {'attempted': attempted, 'request_error': request_error,
                'fresh_processes': [], 'rendered_mode_verified': False,
                'error': 'no fresh screensaver process appeared within 12 seconds'}
    except Exception as exc:
        return {'attempted': False, 'error': str(exc), 'rendered_mode_verified': False}


def reload_screensaver(mode='rings', api=None, schema_loader=None, sleep=time.sleep):
    require(mode in ('rings', 'original'), 'reload mode must be rings or original')
    api = api or luna
    overlay_status = _check_overlay(mode)
    # Validate both mutating SAM payloads before closing the current screensaver.
    validate_payload(CLOSE_METHOD, CLOSE_PAYLOAD, schema_loader)
    validate_payload(LAUNCH_METHOD, LAUNCH_PAYLOAD, schema_loader)
    before = native_state(api)
    old = _screensaver(before)
    require(len(old) <= 1, 'multiple screensaver processes; no action')
    for entry in old:
        _runner(entry)
    close_attempted = False
    try:
        if old:
            close_attempted = True
            api(CLOSE_METHOD, CLOSE_PAYLOAD)
            _wait_old_exit(old, api)
        current = native_state(api)
        require(current['foreground'] == before['foreground'],
                'foreground changed during screensaver close; no launch issued')
        require(not _screensaver(current), 'old screensaver still present; no duplicate launch issued')
        close_attempted = True
        launch_error = None
        try:
            api(LAUNCH_METHOD, LAUNCH_PAYLOAD)
        except Exception as exc:
            launch_error = str(exc)
        fresh_state, fresh = _wait_fresh(old, api)
        require(fresh_state['foreground'] == before['foreground'],
                'foreground changed during native screensaver launch')
        for entry in fresh:
            raw, params = _runner(entry)
            require(not _has_snapshot(params), 'fresh screensaver restored a snapshot instead of loading QML')
        after = native_state(api)
        require(after['foreground'] == before['foreground'], 'foreground changed after reload')
        require(_other_identities(after) == _other_identities(before),
                'a preexisting non-screensaver application identity changed')
        return {
            'mode': mode,
            'foreground_unchanged': True,
            'fresh_screensaver': fresh,
            'other_app_identities_unchanged': True,
            'visible_rendering_verified': False,
            'overlay': overlay_status,
            'launch_response_error': launch_error,
        }
    except Exception as exc:
        if close_attempted:
            recovery = _bounded_relaunch_recovery(api, old, before['foreground'])
            recovery_hint = ('After confirming the overlay state, run rollback and then '
                             'reload with --original if you want the firmware screensaver.')
            raise RuntimeError('%s; bounded recovery: %s; rendered mode is not claimed restored. %s' %
                               (exc, json.dumps(recovery, sort_keys=True), recovery_hint))
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', action='store_true', help='reload original firmware screensaver after rollback')
    parser.add_argument('--ack-native-screensaver-reload', action='store_true',
                        help='explicitly approve closing/relaunching only the native screensaver')
    args = parser.parse_args(argv)
    if not args.ack_native_screensaver_reload:
        parser.error('explicit --ack-native-screensaver-reload is required')
    mode = 'original' if args.original else 'rings'
    result = reload_screensaver(mode=mode)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print('screensaver reload: ' + str(exc), file=sys.stderr)
        sys.exit(1)
