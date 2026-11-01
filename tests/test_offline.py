"""Offline test suite: no GPU, no Windows, no internet, no Ollama needed.

Run from the repository root:   python -m unittest discover -s tests -v

Covers the sentence streamer, local storage, tools, calendar parsing, the HTTP API (streaming chat with tools,
objectives, memory, settings), and the security rules (phone pairing cookie, origin check, private files).
"""
import base64, http.client, io, json, os, sys, tempfile, threading, time, types, unittest, urllib.request, wave
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['CORTANA_DATA_DIR'] = tempfile.mkdtemp(prefix='cortana-test-')
os.environ['CORTANA_FAKE_VRAM_GB'] = '8'      # pretend to be the RTX 3070 the project targets
os.environ['CORTANA_FAKE_RAM_GB'] = '32'

import fake_ollama  # noqa: E402
OLLAMA = fake_ollama.start()
os.environ['CORTANA_OLLAMA_URL'] = f'http://127.0.0.1:{OLLAMA.server_address[1]}'

import hardware, runtime, server, store, tools  # noqa: E402


def stream_all(text, chunk=3):
    s, out, i = runtime.SpokenStream(), [], 0
    while i < len(text):
        out += s.feed(text[i:i + chunk])
        i += chunk
    out += s.finish()
    return out, (s.screen or '').strip()


class SpokenStreamTests(unittest.TestCase):
    def test_sentences_abbreviations_and_decimals(self):
        out, screen = stream_all("It's 1:52 in the morning, Chief. Version 3.5 is fast. Dr. Smith agrees, e.g. on speed! Want more?")
        self.assertEqual(out, ["It's 1:52 in the morning, Chief.", 'Version 3.5 is fast.', 'Dr. Smith agrees, e.g. on speed!', 'Want more?'])
        self.assertEqual(screen, '')

    def test_screen_marker_splits_spoken_and_display(self):
        out, screen = stream_all("Here's how. I've put it on screen.\n[[SCREEN]]\n# Table\n```python\nprint(1)\n```")
        self.assertEqual(out, ["Here's how. I've put it on screen."])
        self.assertTrue(screen.startswith('# Table'))

    def test_code_without_marker_is_never_spoken(self):
        out, screen = stream_all("Sure thing.\n```python\nprint('hi')\n```")
        self.assertEqual(out, ['Sure thing.'])
        self.assertIn("print('hi')", screen)

    def test_table_without_marker_goes_to_screen(self):
        out, screen = stream_all('Here are the planets:\n| Planet | Moons |\n|---|---|\n| Mars | 2 |')
        self.assertEqual(out, ['Here are the planets:'])
        self.assertIn('| Mars | 2 |', screen)

    def test_markdown_symbols_are_removed_from_speech(self):
        out, _ = stream_all('The **answer** is `42`, according to [Wikipedia](https://x.org).')
        self.assertEqual(out, ['The answer is 42, according to Wikipedia.'])

    def test_marker_split_across_chunks(self):
        for size in (1, 2, 5, 7):
            out, screen = stream_all('Short answer here, Chief.\n[[SCREEN]]\n# T\nbody', chunk=size)
            self.assertEqual(out, ['Short answer here, Chief.'], size)
            self.assertTrue(screen.startswith('# T'), size)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.s = store.Store(os.path.join(tempfile.mkdtemp(), 't.db'))

    def tearDown(self):
        self.s.close()

    def test_settings_roundtrip(self):
        self.s.set('home_location', 'London')
        self.assertEqual(self.s.get('home_location'), 'London')
        self.assertEqual(self.s.get('missing', 'x'), 'x')

    def test_facts_dedupe_and_forget(self):
        self.s.add_fact('The user likes tea')
        self.s.add_fact('the user likes TEA')
        self.assertEqual(len(self.s.facts()), 1)
        self.assertEqual(len(self.s.forget_fact(match='likes tea')), 1)
        self.assertEqual(self.s.facts(), [])

    def test_due_alerts_and_acknowledge(self):
        tid = self.s.add_item('timer', 'Tea', time.time() - 1)
        rid = self.s.add_item('reminder', 'Call mum', time.time() - 1)
        self.s.add_item('task', 'Buy milk')
        self.assertEqual({a['id'] for a in self.s.due_alerts()}, {tid, rid})
        self.s.acknowledge(tid)
        self.s.acknowledge(rid)
        self.assertEqual(self.s.due_alerts(), [])
        self.assertTrue(self.s.item(tid)['done'])          # timers finish when announced
        self.assertFalse(self.s.item(rid)['done'])         # reminders stay until completed

    def test_rejects_unknown_kind(self):
        with self.assertRaises(ValueError):
            self.s.add_item('alarm', 'x')


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.s = store.Store(os.path.join(tempfile.mkdtemp(), 't.db'))

    def tearDown(self):
        self.s.close()

    def test_timer(self):
        result, change = tools.run('set_timer', {'minutes': 10, 'label': 'pasta'}, self.s)
        self.assertEqual(result['done'], 'timer set')
        self.assertEqual(change, 'objectives')
        self.assertEqual(self.s.items()[0]['text'], 'pasta')

    def test_timer_limits(self):
        result, _ = tools.run('set_timer', {'minutes': 0}, self.s)
        self.assertIn('error', result)

    def test_reminder_with_clock_time_is_in_the_next_day(self):
        result, _ = tools.run('set_reminder', {'text': 'Call mum', 'at': '18:00'}, self.s)
        due = self.s.items()[0]['due']
        self.assertGreater(due, time.time())
        self.assertLess(due - time.time(), 24 * 3600 + 60)
        self.assertEqual(result['done'], 'reminder set')

    def test_reminder_in_the_past_is_refused(self):
        result, _ = tools.run('set_reminder', {'text': 'x', 'at': '2001-01-01 10:00'}, self.s)
        self.assertIn('error', result)

    def test_memory_tools(self):
        tools.run('remember', {'fact': "The user's dog is called Max"}, self.s)
        self.assertEqual(self.s.facts()[0]['text'], "The user's dog is called Max")
        result, _ = tools.run('forget', {'match': 'dog Max'}, self.s)
        self.assertEqual(result['done'], 'forgotten')

    def test_complete_objective(self):
        self.s.add_item('task', 'Buy milk')
        result, _ = tools.run('complete_objective', {'match': 'milk'}, self.s)
        self.assertEqual(result['items'], ['Buy milk'])
        self.assertEqual(self.s.items(), [])

    def test_unknown_tool_and_bad_arguments_never_raise(self):
        self.assertIn('error', tools.run('format_disk', {}, self.s)[0])
        self.assertIn('error', tools.run('set_timer', {'minutes': 'lots'}, self.s)[0])

    def test_pc_controls_refuse_unknown_apps_and_off_switch(self):
        if os.name == 'nt':
            self.assertIn('error', tools.pc_control('open_app', 'cmd'))
        self.s.set('pc_controls', False)
        self.assertIn('error', tools.run('pc_control', {'action': 'mute'}, self.s)[0])

    def test_calendar_without_address_explains(self):
        self.assertIn('error', tools.run('get_calendar', {}, self.s)[0])

    def test_every_tool_has_a_label(self):
        for t in tools.TOOLS:
            self.assertIn(t['function']['name'], tools.TOOL_LABELS)


class HardwareTests(unittest.TestCase):
    def pick(self, vram, ram=32):
        return hardware.recommended_tag(hardware.recommend({'vram_gb': vram or None, 'ram_gb': ram}))

    def test_recommendation_by_card(self):
        self.assertEqual(self.pick(4), 'qwen3.5:2b')
        self.assertEqual(self.pick(6), 'qwen3.5:4b')
        self.assertEqual(self.pick(8), 'qwen3.5:9b')
        self.assertEqual(self.pick(12), 'qwen3.5:9b')
        self.assertEqual(self.pick(22), 'qwen3.5:27b')
        self.assertEqual(self.pick(0, 16), 'qwen3.5:2b')

    def test_too_big_models_are_not_selectable(self):
        rows = {r['tag']: r for r in hardware.recommend({'vram_gb': 8, 'ram_gb': 32})}
        self.assertFalse(rows['qwen3.5:27b']['selectable'])
        self.assertFalse(rows['qwen3.5:35b-a3b']['selectable'])
        self.assertTrue(rows['qwen3.5:9b']['selectable'])
        self.assertEqual(sum(r['recommended'] for r in rows.values()), 1)

    def test_low_ram_blocks_spilling(self):
        rows = {r['tag']: r for r in hardware.recommend({'vram_gb': 16, 'ram_gb': 8})}
        self.assertEqual(rows['qwen3.5:27b']['rating'], 'too_big')

    def test_unavailable_tags_are_hidden(self):
        rows = hardware.recommend({'vram_gb': 24, 'ram_gb': 64}, available={'qwen3.5:4b', 'qwen3.5:9b'})
        self.assertEqual({r['tag'] for r in rows}, {'qwen3.5:4b', 'qwen3.5:9b'})


ICS = '''BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART;TZID=Europe/London:20261101T093000
DTEND;TZID=Europe/London:20261101T100000
RRULE:FREQ=WEEKLY;BYDAY=SU
SUMMARY:Gym\\, legs day
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20261101
DTEND;VALUE=DATE:20261102
SUMMARY:All day thing
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=Europe/London:20261018T093000
RRULE:FREQ=WEEKLY;BYDAY=SU
EXDATE;TZID=Europe/London:20261108T093000
SUMMARY:Weekly with exception
END:VEVENT
BEGIN:VEVENT
DTSTART:20261101T120000Z
SUMMARY:Cancelled
STATUS:CANCELLED
END:VEVENT
END:VCALENDAR'''


class CalendarTests(unittest.TestCase):
    def test_parse_and_expand(self):
        try:
            import dateutil  # noqa: F401
        except ImportError:
            self.skipTest('python-dateutil not installed (pip install -r requirements.txt)')
        events = tools.parse_ics(ICS)
        day1 = [e['title'] for e in tools.events_on(events, date(2026, 11, 1))]
        day8 = [e['title'] for e in tools.events_on(events, date(2026, 11, 8))]
        self.assertEqual(day1[0], 'All day thing')                     # all-day events first
        self.assertIn('Gym, legs day', day1)                           # escaped comma
        self.assertIn('Weekly with exception', day1)
        self.assertNotIn('Cancelled', day1)
        self.assertIn('Gym, legs day', day8)                           # weekly repeat
        self.assertNotIn('Weekly with exception', day8)                # EXDATE honoured


class FirstLaunchTests(unittest.TestCase):
    def test_waits_for_model_choice(self):
        """First launch with the window open: nothing loads until the user picks a model on the page."""
        rt = runtime.Runtime(lambda text: None)
        rt.tag_exists = {m['tag']: True for m in hardware.CATALOG}
        rt.ask_model, rt.model_chosen = True, False
        t = threading.Thread(target=rt.ensure_ai, daemon=True)
        t.start()
        for _ in range(50):
            if rt.awaiting_choice:
                break
            time.sleep(.05)
        self.assertTrue(rt.awaiting_choice)
        self.assertIn('Choose your AI model', rt.status)
        self.assertIn('Qwen', rt.status)                     # names the recommended model
        time.sleep(.3)
        self.assertFalse(rt.ai_ready)                        # still waiting, nothing auto-picked
        self.assertIsNone(rt.models_info()['current'])      # every model offers Use/Download, incl. the default
        rt.use_model('qwen3.5:4b')
        t.join(5)
        self.assertFalse(t.is_alive())
        self.assertTrue(rt.ai_ready)
        self.assertFalse(rt.awaiting_choice)
        self.assertEqual(rt.model, 'qwen3.5:4b')
        rt.store.set('model', None)
        rt.close()


def silent_voice(text, rate=0):
    b = io.BytesIO()
    w = wave.open(b, 'wb')
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050); w.writeframes(b'\0\0' * 2205); w.close()
    return {'audio': base64.b64encode(b.getvalue()).decode(), 'voice': 'Test voice', 'visemes': []}


class ApiTests(unittest.TestCase):
    TUNNEL = 'phone.example'

    @classmethod
    def setUpClass(cls):
        cls.rt = runtime.Runtime(lambda text: None)
        cls.rt.tag_exists = {m['tag']: True for m in hardware.CATALOG}   # no registry lookups in tests
        cls.rt.ensure_ai()
        cls.rt.voice.speak = silent_voice
        cls.rt.voice.status = 'Test voice'
        cls.rt.tunnel_host = cls.TUNNEL
        cls.srv = server.AppServer(('127.0.0.1', 0), cls.rt)
        cls.port = cls.srv.server_address[1]
        cls.rt.local_url = f'http://127.0.0.1:{cls.port}'
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def request(self, method, path, body=None, headers=None, host=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        h = {'Host': host or f'127.0.0.1:{self.port}', **(headers or {})}
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            h.setdefault('Content-Type', 'application/json')
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        return r.status, dict(r.getheaders()), r.read()

    def chat(self, text):
        status, _, raw = self.request('POST', '/api/chat-stream', {'messages': [{'role': 'user', 'content': text}]})
        self.assertEqual(status, 200)
        return [json.loads(line) for line in raw.decode().splitlines() if line.strip()]

    def test_status(self):
        status, _, raw = self.request('GET', '/api/status')
        data = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertTrue(data['ai'])
        for key in ('alerts', 'voice', 'model', 'canPair'):
            self.assertIn(key, data)

    def test_stream_plain_reply(self):
        events = self.chat('hello')
        self.assertEqual(events[-1]['type'], 'done')
        self.assertTrue(any(e['type'] == 'sentence' for e in events))

    def test_stream_with_tool_updates_objectives(self):
        events = self.chat('Set a 10 minute timer for the pasta')
        types_ = [e['type'] for e in events]
        self.assertEqual(types_[:2], ['tool', 'refresh'])
        self.assertEqual(types_[-1], 'done')
        items = json.loads(self.request('GET', '/api/objectives')[2])['items']
        self.assertTrue(any(i['text'] == 'pasta' for i in items))

    def test_stream_screen_event(self):
        events = self.chat('How do I build a table in python')
        screen = [e for e in events if e['type'] == 'screen']
        self.assertEqual(len(screen), 1)
        self.assertTrue(screen[0]['markdown'].startswith('# Python table'))
        spoken = ' '.join(e['text'] for e in events if e['type'] == 'sentence')
        self.assertNotIn('import', spoken)

    def test_memory_reaches_the_prompt(self):
        self.chat('Remember my dog is called Max')
        self.chat('hi')
        self.assertIn('Max', fake_ollama.LAST_REQUEST['messages'][0]['content'])
        self.assertIn('tools', fake_ollama.LAST_REQUEST)

    def test_objectives_api(self):
        status, _, raw = self.request('POST', '/api/objectives', {'action': 'add', 'kind': 'task', 'text': 'Buy milk'})
        item = [i for i in json.loads(raw)['items'] if i['text'] == 'Buy milk'][0]
        self.request('POST', '/api/objectives', {'action': 'complete', 'id': item['id']})
        items = json.loads(self.request('GET', '/api/objectives')[2])['items']
        self.assertFalse(any(i['id'] == item['id'] for i in items))

    def test_settings_never_return_secrets(self):
        self.request('POST', '/api/settings', {'calendar_url': 'https://example.com/secret-abc/basic.ics', 'brave_key': 'KEY123'})
        raw = self.request('GET', '/api/settings')[2].decode()
        data = json.loads(raw)
        self.assertTrue(data['calendar_connected'])
        self.assertTrue(data['brave_connected'])
        self.assertNotIn('secret-abc', raw)
        self.assertNotIn('KEY123', raw)

    def test_settings_validation(self):
        status, _, _ = self.request('POST', '/api/settings', {'calendar_url': 'http://not-https.example/cal.ics'})
        self.assertEqual(status, 400)
        status, _, _ = self.request('POST', '/api/settings', {'model': 'bad model; rm -rf'})
        self.assertEqual(status, 400)

    def test_cross_origin_post_is_blocked(self):
        status, _, _ = self.request('POST', '/api/chat-stream', {'messages': []}, {'Origin': 'https://evil.example'})
        self.assertEqual(status, 403)

    def test_private_files_are_not_served(self):
        for path in ('/runtime.py', '/server.py', '/store.py', '/tools.py', '/voice.py', '/assets/%2e%2e/runtime.py'):
            self.assertEqual(self.request('GET', path)[0], 404, path)
        for path in ('/', '/app.js', '/pages.js', '/avatar.js', '/responsive.css'):
            self.assertEqual(self.request('GET', path)[0], 200, path)

    def test_models_api_and_guards(self):
        info = json.loads(self.request('GET', '/api/models')[2])
        self.assertEqual(info['recommended'], 'qwen3.5:9b')
        self.assertEqual(info['hardware']['vram_gb'], 8.0)
        # too big for an 8 GB card: refused with a reason
        status, _, raw = self.request('POST', '/api/models', {'action': 'download', 'tag': 'qwen3.5:27b'})
        self.assertEqual(status, 400)
        self.assertIn('too big', json.loads(raw)['error'])
        status, _, _ = self.request('POST', '/api/settings', {'model': 'qwen3.5:27b'})
        self.assertEqual(status, 400)
        # not downloaded yet: can't switch to it
        status, _, raw = self.request('POST', '/api/models', {'action': 'use', 'tag': 'qwen3.5:2b'})
        self.assertIn('not downloaded', json.loads(raw)['error'])
        # download with progress, then it becomes the active model
        self.assertEqual(self.request('POST', '/api/models', {'action': 'download', 'tag': 'qwen3.5:2b'})[0], 200)
        for _ in range(100):
            info = json.loads(self.request('GET', '/api/models')[2])
            if not info['pull']['active']:
                break
            time.sleep(.05)
        self.assertEqual(info['pull']['status'], 'done')
        self.assertEqual(info['current'], 'qwen3.5:2b')
        self.assertEqual(self.rt.store.get('model'), 'qwen3.5:2b')
        self.request('POST', '/api/models', {'action': 'use', 'tag': 'qwen3.5:9b'})
        self.assertEqual(self.rt.model, 'qwen3.5:9b')

    def test_phone_pairing(self):
        # Unpaired phone: friendly 403 page
        status, _, body = self.request('GET', '/', host=self.TUNNEL)
        self.assertEqual(status, 403)
        self.assertIn(b'Scan the QR code', body)
        # Wrong token: still refused
        self.assertEqual(self.request('GET', '/?pair=wrong', host=self.TUNNEL)[0], 403)
        # Right token: cookie must be SameSite=Lax (Strict breaks QR scanners - see docs/DECISIONS.md)
        status, headers, _ = self.request('GET', '/?pair=' + self.rt.token, host=self.TUNNEL)
        self.assertEqual(status, 303)
        cookie = headers.get('Set-Cookie', '')
        for part in ('HttpOnly', 'Secure', 'SameSite=Lax'):
            self.assertIn(part, cookie)
        session = cookie.split(';')[0]
        self.assertEqual(self.request('GET', '/api/status', headers={'Cookie': session}, host=self.TUNNEL)[0], 200)
        # Paired phone still cannot read the pairing QR or post cross-site
        self.assertEqual(self.request('GET', '/api/phone-qr', headers={'Cookie': session}, host=self.TUNNEL)[0], 403)
        status, _, _ = self.request('POST', '/api/chat-stream', {'messages': []},
                                    {'Cookie': session, 'Origin': 'https://evil.example'}, host=self.TUNNEL)
        self.assertEqual(status, 403)


if __name__ == '__main__':
    unittest.main()
