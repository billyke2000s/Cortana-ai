"""A tiny stand-in for OpenJarvis's server (`jarvis serve`): /health, /v1/info, streaming /v1/chat/completions (SSE,
like its agent stream: role chunk, content chunks, finish chunk, [DONE]) and the approval queue."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REQUESTS = []          # chat bodies, newest last
HEADERS = []           # request headers of chat calls
APPROVALS = {}         # id -> {'status', ...}
REPLY = "Done, Chief. I checked your inbox: two new emails, nothing urgent."


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, value, status=200):
        data = json.dumps(value).encode()
        self.send_response(status);self.send_header('Content-Type', 'application/json');self.send_header('Content-Length', str(len(data)))
        self.end_headers();self.wfile.write(data)

    def do_GET(self):
        if self.path == '/health':
            return self.send({'status': 'ok'})
        if self.path == '/v1/info':
            return self.send({'model': 'qwen3.5:9b', 'agent': 'orchestrator', 'engine': 'ollama'})
        if self.path == '/v1/approvals/pending':
            acts = [{'id': k, 'action_type': 'send_email', 'description': v['description'], 'payload': {'to': 'boss@example.com'},
                     'status': 'pending'} for k, v in APPROVALS.items() if v['status'] == 'pending']
            return self.send({'actions': acts, 'count': len(acts)})
        self.send({'detail': 'Not found'}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
        if self.path == '/v1/chat/completions':
            REQUESTS.append(body);HEADERS.append(dict(self.headers))
            self.send_response(200);self.send_header('Content-Type', 'text/event-stream');self.end_headers()
            chunks = [{'choices': [{'delta': {'role': 'assistant'}}]}] + [{'choices': [{'delta': {'content': w + ' '}}]} for w in REPLY.split()] + \
                     [{'choices': [{'delta': {}, 'finish_reason': 'stop'}], 'usage': {}}]
            for c in chunks:
                self.wfile.write(f'data: {json.dumps(c)}\n\n'.encode());self.wfile.flush()
            self.wfile.write(b'data: [DONE]\n\n');return
        for verb in ('approve', 'deny'):
            prefix = '/v1/approvals/'
            if self.path.startswith(prefix) and self.path.endswith('/' + verb):
                aid = self.path[len(prefix):-len(verb) - 1]
                if aid not in APPROVALS:
                    return self.send({'detail': 'Action not found'}, 404)
                APPROVALS[aid]['status'] = verb + ('d' if verb == 'approve' else 'ied')
                return self.send({'status': APPROVALS[aid]['status'], 'id': aid})
        self.send({'detail': 'Not found'}, 404)


def start():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
