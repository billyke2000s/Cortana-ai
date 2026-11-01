"""Text-to-speech for Cortana.

Piper (natural neural voices, runs on this PC) is the main engine. Any Piper .onnx voice placed in
%LOCALAPPDATA%\\CortanaAI\\voices (with its .onnx.json) can be chosen in Settings, including a voice trained with
the Voice Trainer. The Windows voice is kept as a backup and is the only engine that reports mouth shapes itself;
for Piper the page derives mouth movement from the audio.
"""
import base64, hashlib, json, queue, subprocess, threading, time, wave, io, uuid
from pathlib import Path
from runtime import DATA, RESOURCES, HIDDEN, request_json, download, extract

PIPER_RELEASE = 'https://api.github.com/repos/rhasspy/piper/releases/tags/2023.11.14-2'
PIPER_ASSET = 'piper_windows_amd64.zip'
VOICE_BASE = 'https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/'
DEFAULT_VOICE = 'en_US-hfc_female-medium'
# Stock voices offered in Settings (downloaded on demand from the Piper voice collection).
STOCK = {
    'en_US-hfc_female-medium': 'en/en_US/hfc_female/medium/', 'en_US-amy-medium': 'en/en_US/amy/medium/',
    'en_US-kristin-medium': 'en/en_US/kristin/medium/', 'en_US-lessac-high': 'en/en_US/lessac/high/',
    'en_US-ljspeech-high': 'en/en_US/ljspeech/high/', 'en_GB-jenny_dioco-medium': 'en/en_GB/jenny_dioco/medium/',
    'en_GB-cori-high': 'en/en_GB/cori/high/', 'en_GB-alba-medium': 'en/en_GB/alba/medium/',
}
VOICES = DATA / 'voices'
RATE_SCALE = {-1: 1.15, 0: 1.0, 1: 0.88}   # Piper length_scale: bigger = slower


def wav_b64(path_or_bytes):
    data = path_or_bytes if isinstance(path_or_bytes, bytes) else Path(path_or_bytes).read_bytes()
    return base64.b64encode(data).decode()


def wav_complete(path):
    """Piper prints the file path just before closing the file: only read it once the WAV is whole."""
    try:
        with wave.open(str(path)) as w:
            frames = w.getnframes()
            expected = 44 + frames * w.getsampwidth() * w.getnchannels()
        return frames > 0 and Path(path).stat().st_size >= expected
    except Exception:
        return False


class PiperProcess:
    """One long-running Piper process: loads the voice once, then synthesises one sentence per line."""
    def __init__(self, exe, model, length_scale, log):
        self.model, self.length_scale = str(model), length_scale
        self.out = DATA / 'speech-tmp'
        self.out.mkdir(parents=True, exist_ok=True)
        self.p = subprocess.Popen([str(exe), '--model', self.model, '--json-input', '--output_dir', str(self.out),
                                   '--length_scale', str(length_scale), '--sentence_silence', '0.15'],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, creationflags=HIDDEN)
        self.lines = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in iter(self.p.stdout.readline, b''):
            self.lines.put(line.decode('utf-8', 'replace').strip())
        self.lines.put(None)

    def alive(self):
        return self.p.poll() is None

    def synth(self, text, timeout=60):
        target = self.out / f'{uuid.uuid4().hex}.wav'
        self.p.stdin.write((json.dumps({'text': text, 'output_file': str(target)}, ensure_ascii=False) + '\n').encode('utf-8'))
        self.p.stdin.flush()
        deadline = time.monotonic() + timeout
        while True:
            line = self.lines.get(timeout=max(.1, deadline - time.monotonic()))
            if line is None:
                raise RuntimeError('Piper stopped unexpectedly. See piper.log in the app data folder.')
            if Path(line) == target or line.endswith(target.name):
                break
        while not wav_complete(target):
            if time.monotonic() > deadline:
                raise RuntimeError('Piper did not finish the audio in time.')
            time.sleep(.01)
        try:
            return target.read_bytes()
        finally:
            target.unlink(missing_ok=True)

    def close(self):
        if self.alive():
            self.p.terminate()


class Voice:
    def __init__(self, runtime):
        self.runtime = runtime
        self.lock = threading.Lock()
        self.prepare_lock = threading.Lock()
        self.proc = None
        self.exe = next((DATA / 'piper').rglob('piper.exe'), None) if (DATA / 'piper').exists() else None
        self.log = None
        self.status = 'Voice not prepared yet.'
        self.ready = False

    # ---- installation
    def voices(self):
        """Installed Piper voices (name -> .onnx path). Trained voices dropped into the voices folder appear here."""
        if not VOICES.exists():
            return {}
        return {p.name[:-5]: p for p in sorted(VOICES.glob('*.onnx')) if Path(str(p) + '.json').exists()}

    def catalog(self):
        installed = self.voices()
        return [{'name': n, 'installed': n in installed, 'stock': n in STOCK} for n in sorted(set(STOCK) | set(installed))]

    def ensure_piper(self):
        if not self.exe:
            self.runtime.update('Preparing natural voice (Piper)...')
            release = request_json(PIPER_RELEASE)
            asset = next(a for a in release['assets'] if a['name'] == PIPER_ASSET)
            checksum = asset.get('digest', '').removeprefix('sha256:') or None
            download(asset['browser_download_url'], DATA / 'piper-runtime.zip', self.runtime.update, checksum)
            extract(DATA / 'piper-runtime.zip', DATA / 'piper')
            self.exe = next((DATA / 'piper').rglob('piper.exe'))

    def ensure_voice(self, name):
        if name in self.voices():
            return self.voices()[name]
        if name not in STOCK:
            raise RuntimeError(f'Voice {name} is not installed.')
        meta = request_json(VOICE_BASE + 'voices.json', timeout=30)[name]['files']
        VOICES.mkdir(parents=True, exist_ok=True)
        for suffix in ('.onnx.json', '.onnx'):
            rel = STOCK[name] + name + suffix
            target = VOICES / (name + suffix)
            self.runtime.update(f'Downloading voice {name}...')
            download(VOICE_BASE + rel, target, self.runtime.update)
            if hashlib.md5(target.read_bytes()).hexdigest() != meta[rel]['md5_digest']:
                target.unlink(missing_ok=True)
                raise RuntimeError('Voice download verification failed: ' + target.name)
        return VOICES / (name + '.onnx')

    def prepare(self):
        with self.prepare_lock:self._prepare()

    def _prepare(self):
        """Called at startup: install Piper and the chosen voice, then warm it up."""
        store = self.runtime.store
        store.set('voice_engine_failed', False)   # try Piper again on every launch
        if store.get('voice_engine','piper')=='zipvoice':
            try:
                with self.runtime.neural.tts_lock:self.runtime.neural.prepare_voice()
                self.ready,self.status=True,'Reference voice ready (experimental, CPU).'
                return
            except Exception:
                self.status='Reference voice unavailable; preparing Piper fallback.'
                store.set('voice_engine_failed',True)
        if store.get('voice_engine','piper')=='windows':
            self.ready, self.status = True, 'Using the Windows voice.'
            return
        try:
            self.ensure_piper()
            self.ensure_voice(store.get('voice', DEFAULT_VOICE))
            with self.lock:
                self._process(0)
            self.ready,self.status=True,('Reference voice unavailable; Piper fallback ready.' if store.get('voice_engine_failed') else 'Natural voice ready.')
        except Exception as e:
            self.ready, self.status = True, f'Natural voice unavailable ({str(e)[:120]}); using the Windows voice.'
            store.set('voice_engine_failed', True)

    def _process(self, rate):
        name = self.runtime.store.get('voice', DEFAULT_VOICE)
        model = self.voices().get(name) or self.ensure_voice(name)
        scale = RATE_SCALE.get(rate, 1.0)
        if self.proc and self.proc.alive() and self.proc.model == str(model) and self.proc.length_scale == scale:
            return self.proc
        if self.proc:
            self.proc.close()
        if not self.log:
            self.log = (DATA / 'piper.log').open('ab')
            self.runtime.logs.append(self.log)
        self.proc = PiperProcess(self.exe, model, scale, self.log)
        self.runtime.children.append(self.proc.p)
        return self.proc

    # ---- speaking
    def speak(self,text,rate=0):
        store=self.runtime.store;jobs=self.runtime.jobs;started=time.perf_counter();jobs.check()
        if store.get('voice_engine','piper')=='zipvoice' and not store.get('voice_engine_failed',False):
            try:
                audio=self.runtime.neural.speak(text,rate,jobs)
                result={'audio':wav_b64(audio),'voice':'Reference voice · ZipVoice (experimental)','visemes':self.runtime.lips.align(audio,jobs)}
                jobs.measure('tts_ms',started);return result
            except Exception:
                jobs.check();self.status='Reference voice failed; using Piper/Windows fallback.'
        use_piper=store.get('voice_engine','piper') in ('piper','zipvoice') and self.exe and (store.get('voice_engine')=='zipvoice' or not store.get('voice_engine_failed',False))
        if use_piper:
            try:
                with self.lock:
                    jobs.check();audio=self._process(rate).synth(text);jobs.check()
                result={'audio':wav_b64(audio),'voice':'Piper · '+store.get('voice',DEFAULT_VOICE),'visemes':self.runtime.lips.align(audio,jobs)}
                jobs.measure('tts_ms',started);return result
            except Exception:
                jobs.check();self.status='Piper unavailable; using the Windows voice.'
        jobs.check();result=self.windows(text,rate);jobs.check();jobs.measure('tts_ms',started);return result

    def windows(self, text, rate=0):
        with self.lock:
            self.runtime.jobs.check()
            p = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                                (RESOURCES / 'speech.ps1').read_text(encoding='utf8')],
                               input=json.dumps({'text': text, 'rate': max(-1, min(1, int(rate)))}, ensure_ascii=False).encode('utf8'),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, creationflags=HIDDEN)
        if p.returncode:
            raise RuntimeError('Windows speech could not render the audio.')
        result = json.loads(p.stdout.decode('utf-8-sig'))
        if not result.get('audio'):
            raise RuntimeError('The Windows voice returned no audio.')
        return result

    def switch(self, engine=None, voice=None):
        store = self.runtime.store
        if engine:
            store.set('voice_engine', engine)
        if voice:
            store.set('voice', voice)
        store.set('voice_engine_failed', False)
        with self.lock:
            if self.proc:
                self.proc.close()
                self.proc = None
        threading.Thread(target=self.prepare, daemon=True).start()
