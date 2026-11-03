"""Gateway regressions: access checks and explicit settings/folder input."""
import json
import unittest
from unittest.mock import patch
import test_offline as base
import test_companion as companion_tests


class GatewayTests(unittest.TestCase):
    request = base.ApiTests.request
    setUpClass = classmethod(companion_tests.CompanionApiTests.setUpClass.__func__)
    tearDownClass = classmethod(companion_tests.CompanionApiTests.tearDownClass.__func__)

    def test_head_obeys_pairing_and_static_whitelist(self):
        for path in ('/', '/app.js', '/runtime.py'):
            self.assertEqual(self.request('HEAD', path, host='phone.example')[0], 403, path)
        session = {'Cookie': 'cortana_session=' + self.rt.token}
        for host, headers in ((None, {}), ('phone.example', session)):
            status, response_headers, body = self.request('HEAD', '/api/status', headers=headers, host=host)
            self.assertEqual(status, 405)
            self.assertEqual(response_headers['Allow'], 'GET, POST')
            self.assertEqual(body, b'')
            for path in ('/runtime.py', '/server.py', '/voice-profile/reference.wav',
                         '/assets/%2e%2e/runtime.py'):
                self.assertEqual(self.request('HEAD', path, headers=headers, host=host)[0], 404, path)
            for path in ('/', '/app.js'):
                status, response_headers, body = self.request('HEAD', path, headers=headers, host=host)
                self.assertEqual(status, 200, path)
                self.assertGreater(int(response_headers['Content-Length']), 0)
                self.assertEqual(body, b'')

    def test_boolean_settings_reject_coercion_before_any_change(self):
        keys = ('pc_controls', 'tools_enabled', 'pc_access', 'setup_complete',
                'native_notifications', 'watch_folders', 'watch_downloads', 'full_access')
        for key in keys:
            self.rt.store.set(key, False)
            for invalid in ('false', 'true', 0, 1, None, [], {}):
                with self.subTest(key=key, invalid=invalid):
                    status, _, _ = self.request('POST', '/api/settings', {key: invalid})
                    self.assertEqual(status, 400)
                    self.assertIs(self.rt.store.get(key), False)
        self.rt.store.set('home_location', 'Original')
        status, _, _ = self.request('POST', '/api/settings',
                                    {'home_location': 'Changed', 'pc_access': 'false'})
        self.assertEqual(status, 400)
        self.assertEqual(self.rt.store.get('home_location'), 'Original')
        status, _, _ = self.request('POST', '/api/settings',
                                    {'home_location': 'Changed', 'full_access': True},
                                    {'Cookie': 'cortana_session=' + self.rt.token}, host='phone.example')
        self.assertEqual(status, 400)
        self.assertEqual(self.rt.store.get('home_location'), 'Original')
        for value in (True, False):
            body = {key: value for key in keys}
            self.assertEqual(self.request('POST', '/api/settings', body)[0], 200)
            settings = json.loads(self.request('GET', '/api/settings')[2])
            for key in keys:
                self.assertIs(settings[key], value)

    def test_add_folder_requires_explicit_nonempty_path(self):
        with patch('proactive.folder_candidates') as scan:
            for body in ({}, {'path': ''}, {'path': '   '}, {'path': '""'},
                         {'path': None}, {'path': 42}, {'path': []}):
                with self.subTest(body=body):
                    status, _, _ = self.request('POST', '/api/documents',
                                                {'action': 'add_folder', **body})
                    self.assertEqual(status, 400)
            scan.assert_not_called()
