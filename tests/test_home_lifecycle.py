"""Synthetic regressions for the CX native Home initialization/dismissal path."""
import os
from pathlib import Path
import tempfile
import unittest

from test_optional_preview import reload_home


class HomeLifecycleTests(unittest.TestCase):
    def test_hidden_boot_never_requests_native_preload_or_hidden_initialization(self):
        payload = reload_home.launch_payload('--hidden')
        self.assertNotIn('preload', payload)
        self.assertFalse(payload['launchHidden'])
        self.assertNotEqual(payload.get('params', {}).get('activateType'), 'preload')

    def exercise_dismiss(self, api_action, starttime=None):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / 'home.log'
            log.write_bytes(b'[main.cpp] windowHide received\n')
            current = {'time': 0.0}
            calls = []
            def api(method, payload):
                calls.append((method, payload))
                api_action(log)
                return {'returnValue': True}
            def sleep(seconds):
                current['time'] += seconds
            result = reload_home.dismiss_initialized_home(
                {101: 'fresh'}, api=api, sleep=sleep,
                clock=lambda: current['time'], starttime=starttime or (lambda pid: 'fresh'),
                log_path=str(log))
            self.assertEqual(calls, [('com.webos.applicationManager/closeByAppId', {'id': reload_home.APP})])
            return result

    def test_only_new_native_hide_event_verifies_dismissal(self):
        def action(log):
            with log.open('ab') as stream:
                stream.write(b'[main.cpp] windowHide received\n')
        result = self.exercise_dismiss(action)
        self.assertTrue(result['native_window_hide_verified'])
        self.assertFalse(result['navigation_verified'])

    def test_luna_success_or_stale_log_marker_does_not_prove_hidden_state(self):
        with self.assertRaisesRegex(RuntimeError, 'hide acknowledgement timed out'):
            self.exercise_dismiss(lambda log: None)

    @unittest.skipIf(os.name == 'nt', 'native POSIX log rotation; TV runtime is Linux')
    def test_rotated_log_is_not_accepted_as_fresh_evidence(self):
        def action(log):
            os.rename(log, str(log) + '.old')
            log.write_bytes(b'[main.cpp] windowHide received\n')
        with self.assertRaisesRegex(RuntimeError, 'rotated or truncated'):
            self.exercise_dismiss(action)

    def test_reused_or_dead_home_pid_cannot_be_dismissed(self):
        with self.assertRaisesRegex(RuntimeError, 'identity changed before'):
            self.exercise_dismiss(lambda log: self.fail('must not send close'),
                                  starttime=lambda pid: 'different')

    def test_pid_change_after_request_cannot_pass(self):
        identity = {'stamp': 'fresh'}
        def action(log):
            identity['stamp'] = 'reused'
        with self.assertRaisesRegex(RuntimeError, 'identity changed during'):
            self.exercise_dismiss(action, starttime=lambda pid: identity['stamp'])


if __name__ == '__main__':
    unittest.main()
