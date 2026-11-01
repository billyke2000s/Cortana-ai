"""A tiny stand-in for Ollama's /api/tags, /api/generate and streaming /api/chat, used by the offline tests.

It asks for a tool on the first round when the user's message mentions a timer or remembering, then answers using the
tool result. 'table' answers use the [[SCREEN]] marker. Everything streams in small chunks like the real thing.
"""
import json, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LAST_REQUEST = {}
INSTALLED = ['qwen3.5:9b', 'qwen3.5:4b']
COMPLETIONS = []
CHAT_REQUESTS = []   # non-streaming requests (document notes, screenshots), newest last


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, value):
        data = json.dumps(value).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _stream(self, chunks):
        self.send_response(200)
        self.send_header('Content-Type', 'application/x-ndjson')
        self.end_headers()
        for c in chunks:
            self.wfile.write((json.dumps(c) + '\n').encode())
            self.wfile.flush()
            time.sleep(.005)

    def do_GET(self):
        self._json({'models': [{'name': n} for n in INSTALLED]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path == '/api/generate':
            return self._json({'done': True})
        if self.path == '/api/pull':
            if body.get('model') == 'qwen3.5:missing':
                return self._stream([{'error': 'pull model manifest: file does not exist'}])
            INSTALLED.append(body['model'])
            return self._stream([{'status': 'pulling manifest'}] + [{'status': 'downloading', 'total': 100, 'completed': c} for c in (25, 50, 100)] + [{'status': 'success'}])
        LAST_REQUEST.clear()
        LAST_REQUEST.update(body)
        if body.get('stream') is not False:
            CHAT_REQUESTS.append(body)   # every streaming chat request, oldest first
        messages = body['messages']
        if body.get('stream') is False:   # real Ollama returns one JSON object when stream is false
            m = messages[-1]
            COMPLETIONS.append(m)
            text = ("The screen shows a Python error: NameError: name 'x' is not defined." if m.get('images')
                    else 'This part covers the deadline of 5 March and the 3000 word limit.')
            return self._json({'model': body['model'], 'message': {'role': 'assistant', 'content': text}, 'done': True})
        user = [m for m in messages if m['role'] == 'user'][-1]['content'].lower()
        last = messages[-1]
        words = lambda text: [{'message': {'content': w + ' '}} for w in text.split()] + [{'done': True}]
        if last['role'] == 'tool':
            reply = {'set_timer': 'Done, Chief. Your pasta timer is running.',
                     'remember': "Got it. I'll remember that.",
                     'get_weather': "It's 12 degrees and cloudy in London, with rain likely tomorrow.",
                     'find_files': 'I found these files. I have put them on screen.',
                     'add_event': 'Done. Study time is in your calendar for tomorrow at three.'}.get(last.get('tool_name'), 'Done.')
            return self._stream(words(reply))
        if 'timer' in user and body.get('tools'):
            return self._stream([{'message': {'content': '', 'tool_calls': [
                {'function': {'name': 'set_timer', 'arguments': {'minutes': 10, 'label': 'pasta'}}}]}}, {'done': True}])
        if 'find my' in user and body.get('tools'):
            return self._stream([{'message': {'content': '', 'tool_calls': [
                {'function': {'name': 'find_files', 'arguments': {'query': 'coursework'}}}]}}, {'done': True}])
        if 'book' in user and body.get('tools'):
            return self._stream([{'message': {'content': '', 'tool_calls': [
                {'function': {'name': 'add_event', 'arguments': {'title': 'Study time', 'day': 'tomorrow', 'time': '15:00'}}}]}}, {'done': True}])
        if 'weather' in user and body.get('tools'):
            return self._stream([{'message': {'content': '', 'tool_calls': [
                {'function': {'name': 'get_weather', 'arguments': {'place': 'Paris' if 'paris' in user else 'London'}}}]}}, {'done': True}])
        if 'remember' in user and body.get('tools'):
            return self._stream([{'message': {'content': '', 'tool_calls': [
                {'function': {'name': 'remember', 'arguments': {'fact': "The user's dog is called Max"}}}]}}, {'done': True}])
        if 'table' in user:
            text = ("Here's a quick way to build a table in Python. I've put it on screen.\n[[SCREEN]]\n# Python table\n"
                    "```python\nfrom tabulate import tabulate\nprint(tabulate([[1, 2]]))\n```")
            return self._stream([{'message': {'content': text[i:i + 4]}} for i in range(0, len(text), 4)] + [{'done': True}])
        return self._stream(words("Good evening, Chief. What do you need?"))


def start(port=0):
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
