"""OpenJarvis as Cortana's brain and toolbox (1.8, owner request, D-042).

Cortana stays the face: hologram, voice, wake word, phone, approval cards. When Systems -> Brain is set to OpenJarvis,
conversations go to the user's own local OpenJarvis server (`jarvis serve`, OpenAI-compatible, default
http://127.0.0.1:8000), whose agent runs its tools, connectors, memory and MCP servers (for example Windows-MCP for
desktop control). Its approval queue is shown as Cortana approval cards. Everything stays on this PC: only loopback
addresses are accepted. If OpenJarvis isn't running, Cortana starts it from ~/OpenJarvis when found, and otherwise
answers with her own brain.
"""
import json, os, re, subprocess, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

DEFAULT_URL = 'http://127.0.0.1:8000'
LOOPBACK = re.compile(r'^http://(127\.0\.0\.1|localhost|\[::1\]):(\d{2,5})/?$')
# Commands, files, registry and processes stay with Cortana's approved run_command; Windows-MCP only sees and uses the UI.
WINDOWS_MCP = {'name': 'windows', 'command': 'uvx', 'args': ['windows-mcp', 'serve', '--exclude-tools', 'PowerShell,Registry,FileSystem,Process']}
# Tools for a Cortana-ready OpenJarvis (its server never runs shell_exec: that needs an interactive confirmation).
STARTER_TOOLS = ['web_search', 'browser_navigate', 'browser_axtree', 'browser_click', 'browser_type', 'browser_extract', 'http_request',
                 'code_interpreter', 'file_read', 'pdf_extract', 'calculator', 'think', 'memory_store', 'memory_search',
                 'knowledge_search', 'get_weather', 'calendar_upcoming']


def check_url(url):
    """Only this PC: OpenJarvis gets the conversation, so it may never point anywhere else."""
    url = str(url or '').strip() or DEFAULT_URL
    m = LOOPBACK.match(url)
    if not m or not 1 <= int(m.group(2)) <= 65535:
        raise ValueError('OpenJarvis must run on this PC, e.g. http://127.0.0.1:8000')
    return url.rstrip('/')


class OpenJarvis:
    def __init__(self, runtime):
        self.runtime = runtime   # .store and .spawn are read from it each time (tests swap the store)
        self.started = None          # the server process Cortana started, if any
        self.cache = {'at': 0, 'approvals': []}
        self.info = None

    @property
    def store(self):
        return self.runtime.store

    @property
    def spawn(self):
        return getattr(self.runtime, 'spawn', None)

    # ---- connection
    @property
    def url(self):
        try:
            return check_url(self.store.get('openjarvis_url', DEFAULT_URL))
        except ValueError:
            return DEFAULT_URL

    def request(self, path, data=None, timeout=10, method=None):
        headers = {'Content-Type': 'application/json', 'User-Agent': 'Cortana/1.8'}
        key = self.store.get('openjarvis_key', '')
        if key:
            headers['Authorization'] = 'Bearer ' + key
        req = urllib.request.Request(self.url + path, json.dumps(data).encode() if data is not None else None, headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b'{}')

    def alive(self):
        try:
            self.request('/health', timeout=2)
            return True
        except (OSError, ValueError):
            return False

    def status(self):
        """{'running', 'model', 'agent', 'install'} for Systems."""
        running = self.alive()
        info = {}
        if running:
            try:
                info = self.request('/v1/info', timeout=3)
            except (OSError, ValueError):
                pass
        return {'running': running, 'model': info.get('model') or '', 'agent': info.get('agent') or '',
                'install': str(find_install() or '')}

    def ensure_running(self, wait=40):
        """Start `jarvis serve` from the user's OpenJarvis folder when it isn't already running (Windows venv layout)."""
        if self.alive():
            return True
        exe = find_install()
        if not exe or not self.spawn:
            return False
        if not self.started or self.started.poll() is not None:
            port = urllib.parse.urlsplit(self.url).port or 8000
            self.started = self.spawn([str(exe), 'serve', '--host', '127.0.0.1', '--port', str(port)])
        end = time.monotonic() + wait
        while time.monotonic() < end:
            if self.alive():
                return True
            time.sleep(1)
        return False

    # ---- conversation
    def model(self):
        if self.info is None:
            try:
                self.info = self.request('/v1/info', timeout=3)
            except (OSError, ValueError):
                self.info = {}
        return self.info.get('model') or 'default'

    def stream(self, messages, check=lambda: None, watch=None, timeout=600):
        """Yield text pieces of the reply. OpenJarvis's agent runs its own tool loop server-side."""
        body = {'model': self.model(), 'messages': messages, 'stream': True, 'max_tokens': 2048, 'temperature': .45}
        headers = {'Content-Type': 'application/json', 'Accept': 'text/event-stream'}
        key = self.store.get('openjarvis_key', '')
        if key:
            headers['Authorization'] = 'Bearer ' + key
        req = urllib.request.Request(self.url + '/v1/chat/completions', json.dumps(body).encode(), headers)
        try:
            response = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            detail = ''
            try:
                detail = json.loads(e.read() or b'{}').get('detail', '')
            except ValueError:
                pass
            raise RuntimeError(f'OpenJarvis error {e.code}' + (f': {str(detail)[:120]}' if detail else ''))
        with response:
            if watch:
                watch(response)
            for raw in response:
                check()
                line = raw.decode('utf-8', 'replace').strip()
                if not line.startswith('data:'):
                    continue
                data = line[5:].strip()
                if data == '[DONE]':
                    return
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                for choice in chunk.get('choices') or []:
                    piece = (choice.get('delta') or {}).get('content') or ''
                    if piece:
                        yield piece

    # ---- approvals (OpenJarvis's own queue, shown as Cortana cards)
    def approvals(self, max_age=3.0):
        if time.monotonic() - self.cache['at'] < max_age:
            return self.cache['approvals']
        items = []
        try:
            for a in self.request('/v1/approvals/pending', timeout=2).get('actions', [])[:10]:
                items.append({'id': str(a.get('id', ''))[:80], 'kind': str(a.get('action_type', ''))[:60],
                              'summary': ' '.join(str(a.get('description') or a.get('action_type') or 'An action').split())[:300],
                              'detail': json.dumps(a.get('payload') or {}, ensure_ascii=False)[:600]})
        except (OSError, ValueError):
            pass
        self.cache = {'at': time.monotonic(), 'approvals': items}
        return items

    def decide(self, action_id, approve):
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}', str(action_id or '')):
            raise ValueError('Unknown OpenJarvis action.')
        try:
            self.request(f"/v1/approvals/{action_id}/{'approve' if approve else 'deny'}", {}, timeout=5, method='POST')
        except urllib.error.HTTPError as e:
            raise ValueError('That OpenJarvis action has expired.' if e.code == 404 else f'OpenJarvis error {e.code}.')
        except OSError:
            raise ValueError('OpenJarvis is not running.')
        self.cache['at'] = 0
        return {'ok': True, 'say': 'Approved.' if approve else 'Cancelled.'}


def find_install():
    """The user's OpenJarvis install: ~/OpenJarvis/.venv/Scripts/jarvis.exe (Windows) or .venv/bin/jarvis."""
    root = Path(os.environ.get('CORTANA_OPENJARVIS_DIR') or (Path.home() / 'OpenJarvis'))
    for p in (root / '.venv' / 'Scripts' / 'jarvis.exe', root / '.venv' / 'bin' / 'jarvis'):
        if p.is_file():
            return p
    return None


# ---- give OpenJarvis Windows control (Windows-MCP) by adding it to ~/.openjarvis/config.toml
def config_path():
    return Path(os.environ.get('CORTANA_OPENJARVIS_CONFIG') or (Path.home() / '.openjarvis' / 'config.toml'))


def setup_config(ollama_url, model, path=None, port=8000):
    """Create ~/.openjarvis/config.toml for Cortana when OpenJarvis has none (owner's install had none): a tool-using
    orchestrator agent on Cortana's own Ollama and model (one copy of the model in graphics memory), loopback server.
    An existing config is never replaced. Returns a message."""
    path = Path(path or config_path())
    if path.exists():
        return 'OpenJarvis already has settings; Cortana left them as they are.'
    if not re.match(r'^http://(127\.0\.0\.1|localhost):\d{2,5}$', str(ollama_url)):
        ollama_url = 'http://127.0.0.1:11434'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'''# Written by Cortana (D-042). OpenJarvis is Cortana's brain and toolbox; Cortana is the face and voice.
[engine]
default = "ollama"

[engine.ollama]
host = "{ollama_url}"

[intelligence]
default_model = "{model}"

[agent]
default_agent = "orchestrator"
max_turns = 12

[tools]
enabled = {json.dumps(STARTER_TOOLS)}

[tools.mcp]
enabled = true

[server]
host = "127.0.0.1"
port = {int(port)}
''', encoding='utf-8')
    return 'OpenJarvis is set up for Cortana.'


def add_windows_control(path=None):
    """Add Windows-MCP to OpenJarvis's [tools.mcp] servers, keeping any servers already listed. Returns a message.
    Only this one section is touched; the original file is kept as config.toml.cortana-backup."""
    path = Path(path or config_path())
    text = path.read_text(encoding='utf-8') if path.exists() else ''
    if 'windows-mcp' in text:
        return 'Windows control is already set up in OpenJarvis.'
    section = re.search(r'(?ms)^\[tools\.mcp\]\s*$(.*?)(?=^\[|\Z)', text)
    existing = []
    if section:
        m = re.search(r"(?m)^servers\s*=\s*'(.*)'\s*$", section.group(1))
        if m:
            try:
                existing = json.loads(m.group(1))
                existing = existing if isinstance(existing, list) else [existing]
            except ValueError:
                raise ValueError("OpenJarvis's MCP server list isn't plain JSON; add Windows-MCP to it by hand.")
        elif re.search(r'(?m)^servers\s*=', section.group(1)):
            raise ValueError("OpenJarvis's MCP server list uses a format Cortana can't edit safely; add Windows-MCP to it by hand.")
    line = "servers = '" + json.dumps(existing + [WINDOWS_MCP]) + "'"
    if section:
        body = re.sub(r"(?m)^servers\s*=.*$\n?", '', section.group(1))
        body = re.sub(r'(?m)^enabled\s*=.*$', 'enabled = true', body) if re.search(r'(?m)^enabled\s*=', body) else '\nenabled = true' + body
        new = text[:section.start(1)] + body.rstrip('\n') + '\n' + line + '\n\n' + text[section.end(1):].lstrip('\n')
    else:
        new = text.rstrip('\n') + ('\n\n' if text else '') + '[tools.mcp]\nenabled = true\n' + line + '\n'
    if path.exists():
        path.with_name(path.name + '.cortana-backup').write_text(text, encoding='utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding='utf-8')
    return 'Windows control added to OpenJarvis. Restart OpenJarvis to load it (Cortana restarts it if she started it).'
