"""Real local HTTP transport and extension lifecycle; no remote model needed."""
import copy
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from extensions import ExtensionManager, checked, tool_name, revision
from store import Store
import test_offline as base
import test_companion as companion


def manifest(port=47831):
    return {'manifest_version': 1, 'id': 'example.echo', 'name': 'Example extension', 'description': 'An example local ability.',
            'version': '1.0.0', 'connection': {'url': 'http://127.0.0.1:' + str(port), 'token': 'x' * 40},
            'tools': [{'name': 'echo', 'description': 'Return the supplied text.', 'approval': True,
                       'path': '/v1/echo', 'parameters': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}}]}


class Echo(BaseHTTPRequestHandler):
    calls = []
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        type(self).calls.append((self.path, self.headers.get('Authorization'), body))
        value = json.dumps({'done': body['arguments']['text'], 'private': 'x' * 40}).encode()
        self.send_response(200); self.send_header('Content-Length', str(len(value))); self.end_headers(); self.wfile.write(value)


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(':memory:')
        self.manager = ExtensionManager(self.store)
    def tearDown(self): self.store.close()
    def install(self, m=None):
        m = m or manifest()
        self.manager.manage({'action': 'install', 'manifest': m})
        self.manager.manage({'action': 'enable', 'id': m['id']})
        return tool_name(m, m['tools'][0])
    def test_disabled_install_secret_redaction_and_lifecycle(self):
        m = manifest()
        self.manager.manage({'action': 'install', 'manifest': m})
        self.assertEqual(self.manager.schemas(True), [])
        self.assertNotIn('x' * 40, json.dumps(self.manager.listing()))
        self.assertNotIn('token', json.dumps(self.manager.manage({'action': 'preview', 'manifest': m})))
        name = self.install()
        self.assertEqual(len(self.manager.schemas(True)), 1)
        self.assertEqual(self.manager.schemas(False), [])
        self.manager.manage({'action': 'disable', 'id': m['id']})
        with self.assertRaises(ValueError): self.manager.resolve(name)
        self.manager.manage({'action': 'remove', 'id': m['id']})
        self.assertEqual(self.manager.listing()['extensions'], [])
    def test_refuses_remote_and_malicious_connections(self):
        for url in ['https://example.com', 'http://localhost:47831', 'http://127.0.0.1:80',
                    'http://127.0.0.1:47831/path', 'http://user@127.0.0.1:47831', 'file:///tmp/a',
                    'http://127.0.0.1:47831/?token=x']:
            m = manifest(); m['connection']['url'] = url
            with self.subTest(url=url), self.assertRaises(ValueError): checked(m)
    def test_argument_validation_and_approval(self):
        name = self.install()
        for args in [{}, {'text': 3}, {'text': 'x', 'command': 'whoami'}]:
            with self.assertRaises(ValueError): self.manager.prepare(name, args)
        with self.assertRaises(ValueError): self.manager.call(name, {'text': 'x'}, local=True)
        with self.assertRaises(ValueError): self.manager.call(name, {'text': 'x'}, approved=True)
        self.store.set('tools_enabled', False)
        self.assertEqual(self.manager.schemas(True), [])
        with self.assertRaises(ValueError): self.manager.resolve(name)
    def test_context_budget_and_duplicates(self):
        self.install()
        m = manifest(); m['tools'] *= 2
        with self.assertRaises(ValueError): checked(m)
        for i in range(3):
            m = manifest(); m['id'] = 'example.tool' + str(i); self.install(m)
        m = manifest(); m['id'] = 'example.fifth'
        with self.assertRaises(ValueError): self.install(m)
    def test_real_http_token_and_changed_manifest(self):
        srv = ThreadingHTTPServer(('127.0.0.1', 0), Echo)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            m = manifest(srv.server_port); name = self.install(m)
            r = self.manager.call(name, {'text': 'hello'}, local=True, approved=True, expected=revision(m))
            self.assertEqual(r['done'], 'hello'); self.assertNotIn('x' * 40, json.dumps(r))
            self.assertEqual(Echo.calls[-1][1], 'Bearer ' + 'x' * 40)
            m['version'] = '1.0.1'; self.install(m)
            with self.assertRaises(ValueError):
                self.manager.call(name, {'text': 'hello'}, local=True, approved=True, expected='old')
        finally: srv.shutdown(); srv.server_close()


class ExtensionApiTests(unittest.TestCase):
    request = base.ApiTests.request
    setUpClass = classmethod(companion.CompanionApiTests.setUpClass.__func__)
    tearDownClass = classmethod(companion.CompanionApiTests.tearDownClass.__func__)
    def test_pc_only_import_origin_and_static_privacy(self):
        m = manifest()
        self.assertEqual(self.request('POST', '/api/extensions', {'action': 'install', 'manifest': m})[0], 200)
        phone = {'Cookie': 'cortana_session=' + self.rt.token}
        for method, body in [('GET', None), ('POST', {'action': 'enable', 'id': m['id']})]:
            self.assertEqual(self.request(method, '/api/extensions', body, phone, host='phone.example')[0], 403)
        self.assertEqual(self.request('POST', '/api/extensions', {'action': 'enable', 'id': m['id']}, {'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.request('GET', '/extensions.py')[0], 404)
        self.assertNotIn('x' * 40, self.request('GET', '/api/extensions')[2].decode())
    def test_pending_extension_requires_pc_and_current_manifest(self):
        m = manifest(); manager = self.rt.extensions
        manager.manage({'action': 'install', 'manifest': m}); manager.manage({'action': 'enable', 'id': m['id']})
        name = tool_name(m, m['tools'][0])
        pid = self.rt.hold(name, {'text': 'hello'}, True)
        self.rt.pending[pid]['extension_revision'] = revision(m)
        with self.assertRaises(ValueError): self.rt.confirm(pid, True, False)
        self.assertIn(pid, self.rt.pending)
        manager.manage({'action': 'disable', 'id': m['id']})
        with self.assertRaises(ValueError): self.rt.confirm(pid, True, True)
        manager.manage({'action': 'remove', 'id': m['id']})

class ExtensionResultDisplayTests(unittest.TestCase):
    def test_read_tool_results_always_reach_screen_without_model_summary(self):
        from unittest.mock import patch
        import runtime
        rt = runtime.Runtime(); rt.store.close(); rt.store = Store(':memory:'); rt.ai_ready = True
        m = manifest(); m['tools'][0]['approval'] = False
        rt.extensions.manage({'action': 'install', 'manifest': m}); rt.extensions.manage({'action': 'enable', 'id': m['id']})
        name = tool_name(m, m['tools'][0]); rounds = [
            [{'message': {'tool_calls': [{'function': {'name': name, 'arguments': {'text': 'show diff'}}}]}}],
            [{'message': {'content': 'The proposed change is on screen.'}}]]
        def stream(payload): return iter(rounds.pop(0))
        try:
            with patch.object(rt, 'ollama_stream', side_effect=stream), patch.object(rt.extensions, 'call', return_value={'diff': '-old selector\n+new selector'}):
                events = list(rt.chat_stream([{'role': 'user', 'content': 'Inspect the extension proposal'}], local=True))
            screens = [e['markdown'] for e in events if e['type'] == 'screen']
            self.assertEqual(len(screens), 1); self.assertIn('+new selector', screens[0])
        finally: rt.close(); rt.store.close()
