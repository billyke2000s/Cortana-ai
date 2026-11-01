"""Live checks for a Windows machine with internet (run by .github/workflows/live-check.yml, or by hand).

1. Keyless web search: real Bing/DuckDuckGo requests and page reading, no Brave key.
2. Wake word: Windows text-to-speech says phrases into a 16 kHz WAV, the real whisper.cpp transcribes them with the
   wake hint, and runtime.wake_match decides. Usage: python tests/ci_live_check.py [whisper-cli.exe] [ggml-model.bin]
"""
import base64, json, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')   # Windows consoles default to cp1252
import tools, runtime  # noqa: E402

failures = []
print('=== Web search (no key) ===')
for q in ['Premier League results this weekend', 'current UK inflation rate', 'who is the Prime Minister of the UK', 'price of bitcoin today']:
    out = tools.web_search(q)
    size = len(json.dumps(out, ensure_ascii=False))
    print(f"\n# {q}\n engine={out.get('engine')} results={len(out.get('results', []))} page={'page' in out} json={size} chars")
    for r in out.get('results', [])[:3]:
        print('  -', r['source'], '|', r['title'][:70])
    if 'page' in out:
        print('  page from', out['page']['source'], ':', out['page']['text'][:300].replace('\n', ' '))
    if out.get('error') or out.get('engine') not in ('Bing', 'DuckDuckGo') or not out.get('results'):
        failures.append('search: ' + q)
for name, fn in (('Bing', tools.bing_results), ('DuckDuckGo', tools.ddg_results)):
    try:
        print(f'{name} direct: {len(fn("weather London"))} results')
    except Exception as e:
        print(f'{name} direct FAILED: {e}')

if len(sys.argv) == 3:
    print('\n=== Wake word (Windows TTS -> whisper.cpp) ===')
    whisper, model = sys.argv[1:]
    cases = [('Hey Cortana', True), ('Hey Cortana, what time is it?', True), ('Cortana, set a timer for five minutes.', True),
             ('OK Cortana, pause the music.', True), ('I need to contain this problem.', False), ('Hey Montana, how are you?', False),
             ('The curtains are open today.', False)]
    tmp = tempfile.mkdtemp()
    for i, (phrase, expect) in enumerate(cases):
        wav = os.path.join(tmp, f'{i}.wav')
        ps = ("Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              "$f=New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,[System.Speech.AudioFormat.AudioChannel]::Mono); "
              f"$s.SetOutputToWaveFile('{wav}',$f); $s.Speak('{phrase}'); $s.Dispose()")
        subprocess.run(['powershell', '-NoProfile', '-Command', ps], check=True)
        res = {}
        for label, extra in (('plain', []), ('hint', ['--prompt', runtime.WAKE_PROMPT])):
            p = subprocess.run([whisper, '-m', model, '-f', wav, '-l', 'en', '-nt', '-np'] + extra, capture_output=True, text=True)
            heard = p.stdout.strip()
            res[label] = (heard, runtime.wake_match(heard))
        got = res['hint'][1] is not None
        ok = got == expect
        print(f"{'OK ' if ok else 'BAD'} said={phrase!r} | plain={res['plain'][0]!r} -> {res['plain'][1]!r} | hint={res['hint'][0]!r} -> {res['hint'][1]!r}")
        if not ok:
            failures.append('wake: ' + phrase)

print('\n=== PC access (Windows) ===')
import files  # noqa: E402
try:
    shot = files.screenshot()
    print(f'Screenshot: {len(base64.b64decode(shot)):,} bytes PNG')
except Exception as e:
    print('Screenshot FAILED:', e); failures.append('screenshot')
try:
    files.set_clipboard_text('Cortana clipboard test ✓')
    back = files.clipboard_text()
    print('Clipboard round trip:', repr(back))
    if back != 'Cortana clipboard test ✓':
        failures.append('clipboard')
except Exception as e:
    print('Clipboard FAILED:', e); failures.append('clipboard')
try:
    print('Clipboard image (none expected):', files.clipboard_image())
except Exception as e:
    print('Clipboard image FAILED:', e); failures.append('clipboard image')
home_test = os.path.join(os.path.expanduser('~'), 'Documents', 'Cortana Test Coursework Brief.txt')
os.makedirs(os.path.dirname(home_test), exist_ok=True)
open(home_test, 'w').write('The deadline is 5 March.')
found, scanned, partial = files.find('cortana test coursework')
print(f'find_files: {[f["name"] for f in found]} (scanned {scanned:,}, partial={partial})')
if not any(f['path'] == home_test for f in found):
    failures.append('find_files')
os.remove(home_test)

print('\nFAILURES:', failures or 'none')
sys.exit(1 if failures else 0)
