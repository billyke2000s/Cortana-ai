"""Real-model check (AGENTS.md §6.6) against a running Ollama: does the model pick the right ability with the real
system prompt and tool schemas, and can it read an image? Run by .github/workflows/live-check.yml on a CPU runner.

Usage: python tests/ci_model_check.py [model]   (default qwen3.5:4b; OLLAMA_URL defaults to http://127.0.0.1:11434)
"""
import base64, io, json, os, sys, tempfile, time, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')   # Windows consoles default to cp1252
os.environ.setdefault('CORTANA_DATA_DIR', tempfile.mkdtemp())
import runtime, store, tools  # noqa: E402

MODEL = sys.argv[1] if len(sys.argv) > 1 else 'qwen3.5:4b'
URL = os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11434')

def chat(messages, use_tools=True, images=None, predict=400):
    body = {'model': MODEL, 'messages': messages, 'stream': False, 'think': False,
            'options': {'num_ctx': runtime.CONTEXT, 'num_predict': predict, 'temperature': .45}}
    if use_tools:
        body['tools'] = tools.TOOLS
    req = urllib.request.Request(URL + '/api/chat', json.dumps(body).encode(), {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.load(r)['message']

s = store.Store(os.path.join(tempfile.mkdtemp(), 'm.db'))
s.add_document('Coursework Brief.pdf', 'Deadline 5 March.', [('page 1', 'Deadline 5 March.')], 2)
system = {'role': 'system', 'content': runtime.system_prompt(s)}

CASES = [   # (ask, expected tool or None, check on arguments)
    ('Summarise the document I just added.', 'summarise_document', None),
    ('What does my brief say about the deadline?', 'search_documents', None),
    ("What's this error on my screen?", 'look_at_screen', None),
    ('Reword what I just copied so it sounds more professional.', 'clipboard', lambda a: a.get('action') == 'read'),
    ('Find my coursework PDF from last week.', 'find_files', lambda a: 'coursework' in str(a.get('query', '')).lower()),
    ('Book study time on Thursday at 3pm.', 'add_event', lambda a: str(a.get('day', '')).lower().startswith('thu') and a.get('time') in ('15:00', '15:00:00')),
    ('Set a timer for 10 minutes for the pasta.', 'set_timer', lambda a: float(a.get('minutes', 0)) == 10),
    ('Remind me to call mum at 6pm.', 'set_reminder', lambda a: '18:00' in str(a.get('at', ''))),
    ("What's the weather in London?", 'get_weather', lambda a: 'london' in str(a.get('place', '')).lower()),
    ('Tell me a joke.', None, None),
    ('How do I build a table in Python?', None, None),
]

results = []
print(f'=== Tool choice: {MODEL}, real prompt ({len(system["content"])} chars) and {len(tools.TOOLS)} tool schemas ===')
for ask, want, check in CASES:
    t = time.time()
    msg = chat([system, {'role': 'user', 'content': ask}])
    calls = [c['function'] for c in msg.get('tool_calls') or []]
    got = calls[0]['name'] if calls else None
    args = calls[0].get('arguments') if calls else {}
    args = json.loads(args) if isinstance(args, str) else (args or {})
    ok = got == want and (check is None or (got and check(args)))
    if want is None and 'table' in ask:
        ok = ok and '[[SCREEN]]' in (msg.get('content') or '')
    results.append(ok)
    print(f"{'OK ' if ok else 'BAD'} {time.time() - t:5.1f}s  {ask!r} -> {got} {json.dumps(args)[:120]}"
          + ('' if calls else f" | reply: {(msg.get('content') or '')[:100]!r}"))

print('\n=== Vision: can the model read an error from a screenshot-like image? ===')
try:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new('RGB', (1280, 720), (30, 30, 30))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype('DejaVuSansMono.ttf', 28)
    except OSError:
        font = ImageFont.load_default()
    for i, line in enumerate(['Traceback (most recent call last):', '  File "report.py", line 12, in <module>',
                              '    print(totl)', "NameError: name 'totl' is not defined"]):
        d.text((40, 60 + i * 44), line, fill=(230, 230, 230), font=font)
    buf = io.BytesIO(); img.save(buf, 'PNG')
    t = time.time()
    answer = chat([{'role': 'user', 'content': "This is a screenshot of the user's PC screen. What's this error? Quote it exactly.",
                    'images': [base64.b64encode(buf.getvalue()).decode()]}], use_tools=False, predict=200)['content']
    ok = 'totl' in answer and 'NameError' in answer
    results.append(ok)
    print(f"{'OK ' if ok else 'BAD'} {time.time() - t:5.1f}s  {answer[:300]!r}")
except Exception as e:
    results.append(False)
    print('BAD vision check failed:', e)

print(f'\nPASSED {sum(results)}/{len(results)}')
sys.exit(0 if all(results) else 1)
