"""Offline test suite: no GPU, no Windows, no internet, no Ollama needed.

Run from the repository root:   python -m unittest discover -s tests -v

Covers the sentence streamer, local storage, tools, calendar parsing, the HTTP API (streaming chat with tools,
objectives, memory, settings), and the security rules (phone pairing cookie, origin check, private files).
"""
import base64, http.client, io, json, os, sys, tempfile, threading, time, types, unittest, urllib.request, wave, zipfile
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['CORTANA_DATA_DIR'] = tempfile.mkdtemp(prefix='cortana-test-')
os.environ['CORTANA_FAKE_VRAM_GB'] = '8'      # pretend to be the RTX 3070 the project targets
os.environ['CORTANA_FAKE_RAM_GB'] = '32'

import fake_ollama  # noqa: E402
OLLAMA = fake_ollama.start()
os.environ['CORTANA_OLLAMA_URL'] = f'http://127.0.0.1:{OLLAMA.server_address[1]}'

import files, hardware, runtime, server, store, tools  # noqa: E402


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
        self.assertFalse(rows['qwen3.5:35b']['selectable'])
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


def make_docx(paragraphs):
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        body = ''.join(f'<w:p><w:r><w:t>{t}</w:t></w:r></w:p>' for t in paragraphs)
        z.writestr('word/document.xml', '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                                        f'<w:body>{body}</w:body></w:document>')
    return b.getvalue()

def make_pptx(slides):
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        for i, text in enumerate(slides, 1):
            z.writestr(f'ppt/slides/slide{i}.xml', '<p:sld xmlns:p="p" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                                                    f'<a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:sld>')
    return b.getvalue()

def make_pdf(pages):
    """A real minimal PDF (one text line per page) with a correct cross-reference table."""
    objs = ['<< /Type /Catalog /Pages 2 0 R >>', None, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    kids = []
    for text in pages:
        stream = f'BT /F1 12 Tf 72 720 Td ({text}) Tj ET'.encode()
        objs.append(f'<< /Length {len(stream)} >>\nstream\n{stream.decode()}\nendstream')
        objs.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {len(objs)} 0 R >>')
        kids.append(f'{len(objs)} 0 R')
    objs[1] = f'<< /Type /Pages /Kids [{" ".join(kids)}] /Count {len(kids)} >>'
    out, offsets = b'%PDF-1.4\n', []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f'{i} 0 obj\n{o}\nendobj\n'.encode()
    xref = len(out)
    out += f'xref\n0 {len(objs) + 1}\n0000000000 65535 f \n'.encode() + b''.join(f'{o:010d} 00000 n \n'.encode() for o in offsets)
    out += f'trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    return out


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.s = store.Store(os.path.join(tempfile.mkdtemp(), 'd.db'))

    def tearDown(self):
        self.s.close()

    def add(self, name, data):
        text, pages = files.extract_text(name, data)
        return self.s.add_document(name, text, files.chunks(text), pages)

    def test_extracts_pdf_word_powerpoint_and_text(self):
        text, pages = files.extract_text('brief.pdf', make_pdf(['Coursework brief', 'Deadline is 5 March']))
        self.assertEqual(pages, 2)
        self.assertIn('[page 2]', text)
        self.assertIn('Deadline is 5 March', text)
        self.assertIn('Word limit 3000', files.extract_text('n.docx', make_docx(['Intro', 'Word limit 3000']))[0])
        text, slides = files.extract_text('talk.pptx', make_pptx(['Title slide', 'Results']))
        self.assertEqual(slides, 2)
        self.assertIn('[slide 2]', text)
        self.assertEqual(files.extract_text('a.html', b'<p>Hi</p><script>bad()</script>')[0].split(), ['Hi'])
        for bad in ('virus.exe', 'photo.png'):
            with self.assertRaises(ValueError):
                files.extract_text(bad, b'x')
        with self.assertRaises(ValueError):
            files.extract_text('broken.docx', b'not a zip')

    def test_search_finds_the_right_passage_with_its_page(self):
        pages = [f'Chapter {i}. ' + ('Filler text about other topics. ' * 30) for i in range(1, 6)]
        pages[2] = 'Chapter 3. Photosynthesis turns light into chemical energy in the chloroplast. ' + 'More detail. ' * 30
        self.add('biology.pdf', make_pdf(pages))
        self.add('notes.docx', make_docx(['The essay deadline is Friday 14 March at noon.']))
        out, _ = tools.run('search_documents', {'query': 'what is photosynthesis'}, self.s)
        self.assertEqual(out['results'][0]['document'], 'biology.pdf')
        self.assertEqual(out['results'][0]['where'], 'page 3')
        out, _ = tools.run('search_documents', {'query': 'essay deadline', 'document': 'notes'}, self.s)
        self.assertIn('14 March', out['results'][0]['text'])
        self.assertIn('error', tools.run('search_documents', {'query': 'x', 'document': 'nonexistent'}, self.s)[0])

    def test_summary_uses_the_model_per_part_and_is_cached(self):
        self.add('long.docx', make_docx([f'Paragraph {i}: ' + 'words ' * 120 for i in range(40)]))
        calls = []
        llm = lambda prompt, images=None, max_tokens=300: calls.append(prompt) or f'note {len(calls)}'
        out, _ = tools.run('summarise_document', {}, self.s, llm)    # empty = most recent document
        self.assertEqual(out['document'], 'long.docx')
        self.assertEqual(len(calls), 8)                                # at most 8 parts, evenly spaced
        self.assertIn('note 8', out['section_notes'])
        self.assertIn('parts of', out['note'])
        tools.run('summarise_document', {'document': 'long'}, self.s, llm)
        self.assertEqual(len(calls), 8)                                # cached
        self.add('short.txt', b'Just one short line.')
        out, _ = tools.run('summarise_document', {'document': 'short'}, self.s, llm)
        self.assertIn('short line', out['text'])                       # short files go straight to the model

    def test_no_documents_explains_how_to_add(self):
        self.assertIn('paperclip', tools.run('search_documents', {'query': 'x'}, self.s)[0]['error'])

    def test_replace_and_remove(self):
        a = self.add('notes.txt', b'old text')
        b = self.add('notes.txt', b'new text')
        self.assertEqual([d['id'] for d in self.s.documents()], [b])
        self.assertIn('new', self.s.document_text(b))
        self.s.remove_document(b)
        self.assertEqual(self.s.documents(), [])
        self.assertEqual(self.s.document_chunks(), [])

    def test_documents_reach_the_prompt(self):
        self.add('brief.txt', b'x')
        self.assertIn('brief.txt', runtime.system_prompt(self.s))


class PcAccessTests(unittest.TestCase):
    def setUp(self):
        self.s = store.Store(os.path.join(tempfile.mkdtemp(), 'p.db'))
        self.dir = tempfile.mkdtemp()
        self._shot, self._clip, self._clipimg, self._setclip, self._roots = files.screenshot, files.clipboard_text, files.clipboard_image, files.set_clipboard_text, files.search_roots
        files.search_roots = lambda extra=(): [__import__('pathlib').Path(self.dir)]

    def tearDown(self):
        files.screenshot, files.clipboard_text, files.clipboard_image, files.set_clipboard_text, files.search_roots = self._shot, self._clip, self._clipimg, self._setclip, self._roots
        self.s.close()

    def touch(self, rel, data=b'x', age_days=0):
        p = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'wb').write(data)
        t = time.time() - age_days * 86400
        os.utime(p, (t, t))
        return p

    def test_find_open_and_read_files(self):
        self.touch('Uni/Coursework Brief.pdf', make_pdf(['Submit by 5 March']), age_days=2)
        self.touch('Uni/old coursework.docx', make_docx(['Old']), age_days=40)
        self.touch('Downloads/coursework.exe')
        self.touch('node_modules/coursework.pdf')                       # skipped folder
        out, _ = tools.run('find_files', {'query': 'my coursework from last week', 'days': 7}, self.s)
        self.assertEqual(sorted(f['name'] for f in out['files']), ['Coursework Brief.pdf', 'coursework.exe'])   # not the 40-day-old one
        card = tools.screen_for('find_files', out)
        self.assertIn('# Files found', card)
        out, _ = tools.run('find_files', {'query': 'coursework', 'kind': 'pdf'}, self.s)
        self.assertEqual([f['name'] for f in out['files']], ['Coursework Brief.pdf'])
        # the .exe is found but never opened
        listed = [f['name'] for f in tools.run('find_files', {'query': 'coursework', 'days': 7}, self.s)[0]['files']]
        exe, pdf = listed.index('coursework.exe') + 1, listed.index('Coursework Brief.pdf') + 1
        self.assertIn('does not open programs', tools.run('open_file', {'number': exe}, self.s)[0]['error'])
        self.assertIn('error', tools.run('open_file', {'number': 9}, self.s)[0])
        self.assertIn('error', tools.run('open_file', {'number': 'C:/Windows/system32/cmd.exe'}, self.s)[0])
        out, change = tools.run('open_file', {'number': pdf, 'read': True}, self.s)
        self.assertEqual(change, 'documents')
        self.assertIn('5 March', out['start'])
        self.assertEqual(self.s.documents()[0]['name'], 'Coursework Brief.pdf')

    def test_screen_and_clipboard(self):
        files.screenshot = lambda: 'PNGDATA'
        seen = {}
        def llm(prompt, images=None, max_tokens=300):
            seen.update(prompt=prompt, images=images)
            return 'NameError on line 3'
        out, _ = tools.run('look_at_screen', {'question': "what's this error?"}, self.s, llm)
        self.assertEqual(out['from_screen'], 'NameError on line 3')
        self.assertEqual(seen['images'], ['PNGDATA'])
        self.assertIn("what's this error?", seen['prompt'])
        files.clipboard_text = lambda: 'Dear Sam, ' * 600
        out, _ = tools.run('clipboard', {'action': 'read'}, self.s, llm)
        self.assertEqual(len(out['clipboard']), 3200)
        self.assertIn('cut to 3,200', out['note'])
        files.clipboard_text, files.clipboard_image = (lambda: None), (lambda: 'IMG')
        self.assertEqual(tools.run('clipboard', {'action': 'read'}, self.s, llm)[0]['clipboard_image'], 'NameError on line 3')
        files.clipboard_image = lambda: None
        self.assertIn('empty', tools.run('clipboard', {'action': 'read'}, self.s, llm)[0]['error'])
        copied = []
        files.set_clipboard_text = copied.append
        self.assertEqual(tools.run('clipboard', {'action': 'write', 'text': 'Hello'}, self.s)[0]['done'], 'copied to the clipboard')
        self.assertEqual(copied, ['Hello'])

    def test_switch_off(self):
        self.s.set('pc_access', False)
        for name, args in (('look_at_screen', {'question': 'x'}), ('clipboard', {'action': 'read'}), ('find_files', {'query': 'x'}), ('open_file', {'number': 1})):
            self.assertIn('switched off', tools.run(name, args, self.s, lambda *a, **k: 'x')[0]['error'], name)

    def test_not_on_windows_is_a_clear_error(self):
        if os.name == 'nt':
            self.skipTest('Windows')
        files.screenshot = self._shot
        self.assertIn('Windows', tools.run('look_at_screen', {'question': 'x'}, self.s, lambda *a, **k: 'x')[0]['error'])


class EventTests(unittest.TestCase):
    def setUp(self):
        self.s = store.Store(os.path.join(tempfile.mkdtemp(), 'e.db'))

    def tearDown(self):
        self.s.close()

    def test_resolve_day(self):
        from datetime import datetime as dt
        thu = dt(2026, 11, 5, 16, 0)                                    # a Thursday, 4 pm
        self.assertEqual(tools.resolve_day('thursday', '17:00', thu), dt(2026, 11, 5, 17, 0))
        self.assertEqual(tools.resolve_day('Thursday', '15:00', thu), dt(2026, 11, 12, 15, 0))   # already passed: next week
        self.assertEqual(tools.resolve_day('mon', '09:30', thu), dt(2026, 11, 9, 9, 30))
        self.assertEqual(tools.resolve_day('tomorrow', '8:05', thu), dt(2026, 11, 6, 8, 5))
        self.assertEqual(tools.resolve_day('2026-12-01', '10:00', thu), dt(2026, 12, 1, 10, 0))
        for day, t in (('someday', '10:00'), ('today', '25:00'), ('today', 'three')):
            with self.assertRaises(ValueError):
                tools.resolve_day(day, t, thu)

    def test_add_event_makes_reminder_card_and_google_link(self):
        out, change = tools.run('add_event', {'title': 'Study time', 'day': 'tomorrow', 'time': '15:00'}, self.s)
        self.assertEqual(change, 'objectives')
        self.assertTrue(out['google_link'].startswith('https://calendar.google.com/calendar/render?action=TEMPLATE'))
        ev = self.s.upcoming_events()[0]
        self.assertEqual(ev['end'] - ev['start'], 3600)
        rem = [i for i in self.s.items() if i['kind'] == 'reminder'][0]
        self.assertEqual(rem['due'], ev['start'] - 600)
        self.assertIn('starts in 10 minutes', rem['text'])
        card = tools.screen_for('add_event', out)
        self.assertIn('[Add to Google Calendar](https://calendar.google.com/', card)
        day = tools.run('get_calendar', {'day': 'tomorrow'}, self.s)[0]
        self.assertEqual(day['events'][0]['title'], 'Study time')
        self.assertEqual(day['events'][0]['source'], 'Cortana')
        self.assertIn('error', tools.run('add_event', {'title': 'X', 'day': 'today', 'time': '00:00'}, self.s)[0])
        self.assertIn('error', tools.run('add_event', {'title': '', 'day': 'today', 'time': '23:59'}, self.s)[0])

    def test_google_events_get_a_reminder_once(self):
        rt = runtime.Runtime(lambda text: None)
        rt.store.set('calendar_url', 'https://example.com/cal.ics')
        now = time.time()
        old = tools.ical_upcoming
        tools.ical_upcoming = lambda url, hours=12, now=None: [('Lecture', now + 3600), ('Starting now', now + 30)]
        try:
            before = len(rt.store.items())
            self.assertEqual(rt.calendar_tick(now), 1)
            self.assertEqual(rt.calendar_tick(now), 0)                 # not twice
            new = [i for i in rt.store.items() if 'Lecture starts in 10 minutes' == i['text']]
            self.assertEqual(len(rt.store.items()), before + 1)
            self.assertAlmostEqual(new[0]['due'], now + 3000, delta=1)
        finally:
            tools.ical_upcoming = old
            for i in rt.store.items():
                rt.store.delete_item(i['id'])
            rt.store.set('calendar_url', '')
            rt.store.set('cal_reminded', [])
            rt.close()



class WakeWordTests(unittest.TestCase):
    def test_spellings_whisper_produces(self):
        for heard, rest in [('Hey Cortana.', ''), ('Hey, Cortana, what time is it?', 'what time is it?'),
                            ('Hey Katana, set a timer.', 'set a timer.'), ('Courtana what is the weather', 'what is the weather'),
                            ('Um, hey Cortona.', ''), ('OK Cortina', ''), ('Hey Quartana!', ''), ('Cor tana, hello there', 'hello there'),
                            ('Cortana', ''), ('Hey Gortana pause the music', 'pause the music'), ('Hey cortanna.', '')]:
            self.assertEqual(runtime.wake_match(heard), rest, heard)

    def test_ordinary_speech_does_not_trigger(self):
        for heard in ['I need to contain this.', 'Katana is a sword.', 'Certainly, sir.', 'Hey Montana', 'The curtains are open',
                      'Call Santana later', 'I asked Cortana yesterday', 'Cortana is my assistant.', '', 'Thank you.',
                      'Contact me tomorrow', 'Hey Carter']:
            self.assertIsNone(runtime.wake_match(heard), heard)


DDG_PAGE = """<div class="result results_links results_links_deep result--ad"><div class="links_main links_deep result__body">
<h2 class="result__title"><a rel="nofollow" class="result__a" href="https://duckduckgo.com/y.js?ad_domain=x&amp;u3=1">Buy tickets</a></h2>
<a class="result__snippet" href="#">An advert</a></div></div>
<div class="result results_links results_links_deep web-result "><div class="links_main links_deep result__body">
<h2 class="result__title"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.bbc.co.uk%2Fsport%2Ffootball&amp;rut=abc">Premier League - <b>Scores</b> &amp; Fixtures</a></h2>
<div class="result__extras"><div class="result__extras__url"><a class="result__url" href="#">www.bbc.co.uk</a></div></div>
<a class="result__snippet" href="#">Premier League <b>scores</b>, results and fixtures on BBC Sport.</a><div class="clear"></div></div></div>"""

BING_RSS = """<?xml version="1.0" encoding="utf-8" ?><rss version="2.0"><channel><title>Bing: q</title>
<item><title>Premier League - Scores &amp; Fixtures - BBC Sport</title><link>https://www.bbc.co.uk/sport/football/premier-league/scores-fixtures</link>
<description>Premier League scores, results and fixtures on BBC Sport, including live football scores.</description></item>
<item><title>Results | Premier League</title><link>https://www.premierleague.com/results</link><description>Latest results.</description></item>
<item><title>Bad link</title><link>javascript:alert(1)</link><description>x</description></item></channel></rss>"""

ARTICLE = """<html><head><script>var ignore='me';</script><style>.a{}</style></head><body><nav>Home News Sport Weather Menu links here</nav>
<p>Cookie banner text that is long enough to count as a block of page text.</p>
<article><h1>Premier League results</h1><p>Arsenal 2-1 Chelsea: Saka scored the winner in the 89th minute at the Emirates on Saturday.</p>
<p>Liverpool 3-0 Everton in the Merseyside derby, with two goals from Salah in the Premier League.</p></article>
<footer>Copyright and footer links that should never be read out as results.</footer></body></html>"""


class WebSearchTests(unittest.TestCase):
    def setUp(self):
        self._fetch, self._public, self._get_json = tools.fetch, tools._public_url, tools.get_json
        self.calls = []
        def offline(url, *a, **k):   # no real network in the offline suite (CI runners do have internet)
            raise OSError('offline test')
        tools.get_json = offline

    def tearDown(self):
        tools.fetch, tools._public_url, tools.get_json = self._fetch, self._public, self._get_json

    def fake(self, pages):
        def fetch(url, timeout=8, limit=0):
            self.calls.append(url)
            for key, (body, ctype) in pages.items():
                if key in url:
                    if body is None:
                        raise OSError('blocked')
                    return body, ctype
            raise OSError('not found')
        tools.fetch = fetch

    def test_ddg_parser_skips_ads_and_decodes_links(self):
        self.fake({'duckduckgo.com/html': (DDG_PAGE, 'text/html')})
        res = tools.ddg_results('premier league scores')
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['url'], 'https://www.bbc.co.uk/sport/football')
        self.assertEqual(res[0]['title'], 'Premier League - Scores & Fixtures')
        self.assertIn('results and fixtures', res[0]['snippet'])

    def test_bing_rss_and_page_reading_without_key(self):
        self.fake({'bing.com/search': (BING_RSS, 'application/rss+xml'), 'bbc.co.uk': (ARTICLE, 'text/html')})
        out = tools.web_search('premier league results')
        self.assertEqual(out['engine'], 'Bing')
        self.assertEqual([r['source'] for r in out['results']], ['bbc.co.uk', 'premierleague.com'])   # javascript: link dropped
        self.assertIn('Arsenal 2-1 Chelsea', out['page']['text'])
        self.assertIn('Liverpool 3-0 Everton', out['page']['text'])
        for junk in ('ignore', 'Menu links', 'footer links'):
            self.assertNotIn(junk, out['page']['text'])
        self.assertEqual(out['page']['source'], 'bbc.co.uk')
        self.assertFalse(any('api.search.brave.com' in c for c in self.calls))
        self.assertLessEqual(len(json.dumps(out)), 3500)            # fits the tool-result budget

    def test_falls_back_to_duckduckgo_when_bing_fails(self):
        self.fake({'bing.com/search': (None, ''), 'duckduckgo.com/html': (DDG_PAGE, 'text/html'), 'bbc.co.uk': (ARTICLE, 'text/html')})
        out = tools.web_search('premier league results')
        self.assertEqual(out['engine'], 'DuckDuckGo')
        self.assertIn('Arsenal 2-1 Chelsea', out['page']['text'])

    def test_unreachable_is_a_clear_error(self):
        self.fake({})
        self.assertIn('unreachable', tools.web_search('anything')['error'])

    def test_never_reads_private_addresses(self):
        tools.fetch = self._fetch
        for url in ['http://127.0.0.1:8080/', 'http://localhost/', 'http://192.168.1.1/admin', 'file:///C:/Windows/win.ini', 'ftp://x.org/']:
            self.assertFalse(tools._public_url(url), url)
            with self.assertRaises(ValueError):
                tools.fetch(url)


class WeatherFirstTests(unittest.TestCase):
    def test_weather_questions_and_places(self):
        cases = {"What's the weather in London?": 'London', 'Will it rain tomorrow?': '', 'Do I need an umbrella in New York today?': 'New York',
                 'weather for leeds this weekend': 'leeds', 'Forecast at Lake Como please': 'Lake Como', "What's the temperature in the room?": '',
                 'How cold is it in Oslo right now': 'Oslo'}
        for q, place in cases.items():
            self.assertEqual(runtime.weather_question(q), place, q)
        for q in ('Tell me a joke', 'Set a timer', 'What is a rainbow made of?', 'Summarise this', 'Let us brainstorm ideas'):
            self.assertIsNone(runtime.weather_question(q), q)

    def test_forecast_is_fetched_before_the_model_answers(self):
        rt = runtime.Runtime(lambda text: None)
        rt.tag_exists = {m['tag']: True for m in hardware.CATALOG}
        rt.ensure_ai()
        asked = []
        old = tools.weather
        tools.weather = lambda place, home: asked.append(place) or {'error': 'offline'}
        fake_ollama.CHAT_REQUESTS.clear()
        try:
            events = list(rt.chat_stream([{'role': 'user', 'content': "What's the weather in Paris?"}]))
        finally:
            tools.weather = old
        self.assertEqual(asked[0], 'Paris')
        self.assertEqual(events[0], {'type': 'tool', 'name': 'get_weather', 'label': 'CHECKING WEATHER'})
        first = fake_ollama.CHAT_REQUESTS[0]['messages']
        self.assertEqual(first[-1]['role'], 'user')  # No Python intent pre-routing: the model chose the weather tool.
        second = fake_ollama.CHAT_REQUESTS[1]['messages']
        self.assertEqual([m['role'] for m in second[-3:]], ['user', 'assistant', 'tool'])
        self.assertIn('offline', second[-1]['content'])
        rt.close()


class WeatherDisplayTests(unittest.TestCase):
    def test_weather_always_shows_the_forecast_card(self):
        today = date.today()
        fake = {'place': 'London, England, United Kingdom', 'source': 'Open-Meteo',
                'now': {'summary': 'overcast', 'temp_c': 12, 'feels_like_c': 10, 'wind_kmh': 18},
                'days': [{'date': (today + timedelta(days=i)).isoformat(), 'summary': s, 'high_c': 13 - i, 'low_c': 8 - i, 'rain_chance_pct': r}
                         for i, (s, r) in enumerate([('overcast', 20), ('rain', 85), ('partly cloudy', 10)])]}
        old = tools.weather
        tools.weather = lambda place, home: fake
        try:
            rt = runtime.Runtime(lambda text: None)
            rt.tag_exists = {m['tag']: True for m in hardware.CATALOG}
            rt.ensure_ai()
            events = list(rt.chat_stream([{'role': 'user', 'content': "What's the weather in London?"}]))
        finally:
            tools.weather = old
        screens = [e['markdown'] for e in events if e['type'] == 'screen']
        self.assertEqual(len(screens), 1)
        card = screens[0]
        self.assertTrue(card.startswith('# Weather · London'))
        for part in ('12°C', 'overcast', '| Today |', '| Tomorrow |', '13° / 8°', '85%'):
            self.assertIn(part, card)
        spoken = ' '.join(e['text'] for e in events if e['type'] == 'sentence')
        self.assertIn('12 degrees', spoken)
        self.assertNotIn('|', spoken)
        self.assertEqual(tools.weather_screen({'error': 'x'}), '')


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
        self.assertEqual([t for t in types_ if t!='activity'][:2], ['tool', 'refresh'])
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
        for path in ('/runtime.py', '/server.py', '/store.py', '/tools.py', '/voice.py', '/files.py', '/hardware.py', '/assets/%2e%2e/runtime.py'):
            self.assertEqual(self.request('GET', path)[0], 404, path)
        for path in ('/', '/app.js', '/pages.js', '/agent-pages.js', '/avatar.js', '/responsive.css'):
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

    def test_documents_api(self):
        data = base64.b64encode(make_docx(['The project is due on 9 May.'])).decode()
        status, _, raw = self.request('POST', '/api/documents', {'action': 'add', 'name': '../../brief.docx', 'data': data})
        self.assertEqual(status, 200, raw)
        added = json.loads(raw)['added']
        self.assertEqual(added['name'], 'brief.docx')                 # path parts dropped
        listed = json.loads(self.request('GET', '/api/documents')[2])
        self.assertIn('brief.docx', [d['name'] for d in listed['documents']])
        self.assertTrue(listed['canAddFolder'])
        bad = base64.b64encode(b'MZ').decode()
        self.assertEqual(self.request('POST', '/api/documents', {'action': 'add', 'name': 'x.exe', 'data': bad})[0], 400)
        folder = tempfile.mkdtemp()
        open(os.path.join(folder, 'a.txt'), 'w').write('Alpha notes')
        os.makedirs(os.path.join(folder, 'sub')); open(os.path.join(folder, 'sub', 'b.md'), 'w').write('# Beta')
        open(os.path.join(folder, 'c.exe'), 'wb').write(b'MZ')
        status, _, raw = self.request('POST', '/api/documents', {'action': 'add_folder', 'path': folder})
        self.assertEqual(json.loads(raw)['added_count'], 2)
        status, headers, _ = self.request('GET', '/?pair=' + self.rt.token, host=self.TUNNEL)
        session = headers['Set-Cookie'].split(';')[0]
        status, _, raw = self.request('POST', '/api/documents', {'action': 'add_folder', 'path': folder}, {'Cookie': session}, host=self.TUNNEL)
        self.assertEqual(status, 400)
        self.assertIn('on the PC itself', json.loads(raw)['error'])        # the phone can't index PC folders
        self.assertFalse(json.loads(self.request('GET', '/api/documents', headers={'Cookie': session}, host=self.TUNNEL)[2])['canAddFolder'])
        for d in json.loads(self.request('GET', '/api/documents')[2])['documents']:
            self.request('POST', '/api/documents', {'action': 'remove', 'id': d['id']})
        self.assertEqual(json.loads(self.request('GET', '/api/documents')[2])['documents'], [])

    def test_events_and_pc_access_setting(self):
        events = self.chat('Book study time tomorrow at 3')
        screens = [e['markdown'] for e in events if e['type'] == 'screen']
        self.assertTrue(screens and screens[0].startswith('# Event added'))
        listed = json.loads(self.request('GET', '/api/events')[2])['events']
        self.assertEqual(listed[0]['title'], 'Study time')
        self.request('POST', '/api/events', {'action': 'remove', 'id': listed[0]['id']})
        self.assertEqual(json.loads(self.request('GET', '/api/events')[2])['events'], [])
        self.assertTrue(json.loads(self.request('GET', '/api/settings')[2])['pc_access'])
        self.request('POST', '/api/settings', {'pc_access': False})
        self.assertFalse(json.loads(self.request('GET', '/api/settings')[2])['pc_access'])
        self.request('POST', '/api/settings', {'pc_access': True})

    def test_model_completion_sends_images(self):
        fake_ollama.COMPLETIONS.clear()
        self.assertIn('NameError', self.rt.complete('What is on screen?', images=['QUJD']))
        self.assertEqual(fake_ollama.COMPLETIONS[-1]['images'], ['QUJD'])
        self.assertEqual(fake_ollama.LAST_REQUEST['stream'], False)

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
