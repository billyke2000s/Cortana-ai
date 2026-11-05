"""Copy this folder to create an extension. Run with Python, then import extension.json.

Change NAME, ID, DESCRIPTION, TOOLS and handle(). Cortana never imports this file.
"""
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ID, NAME = 'example.echo', 'Echo example'
DESCRIPTION = 'A small example for extension authors.'
TOOLS = [{'name': 'echo', 'description': 'Echo some text through the local example service.',
          'path': '/v1/echo', 'approval': False,
          'parameters': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}}]


def handle(path, arguments, approved):
    if path != '/v1/echo' or not isinstance(arguments.get('text'), str):
        raise ValueError('Supply text for the echo tool.')
    return {'text': arguments['text'][:1000]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        value, status = {}, 200
        try:
            if (self.headers.get('Host') != '127.0.0.1:' + str(self.server.server_port) or
                self.headers.get('Origin') or not secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + self.server.token)):
                raise PermissionError()
            if self.headers.get_content_type() != 'application/json': raise ValueError('JSON required.')
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 16000: raise ValueError('Invalid request size.')
            body = json.loads(self.rfile.read(size))
            tool = next((t for t in TOOLS if t['path'] == self.path), None)
            if tool is None: raise ValueError('Unknown tool.')
            if tool['approval'] and body.get('approved') is not True: raise PermissionError()
            value = handle(self.path, body['arguments'], body.get('approved') is True)
        except PermissionError: value, status = {'error': 'Unauthorized or approval required.'}, 403
        except Exception: value, status = {'error': 'Invalid extension request.'}, 400
        raw = json.dumps(value).encode();self.send_response(status)
        self.send_header('Content-Type', 'application/json');self.send_header('Content-Length', str(len(raw)));self.end_headers();self.wfile.write(raw)


if __name__ == '__main__':
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    server.token = secrets.token_urlsafe(32)
    manifest = {'manifest_version': 1, 'id': ID, 'name': NAME, 'description': DESCRIPTION, 'version': '1.0.0',
                'connection': {'url': 'http://127.0.0.1:' + str(server.server_port), 'token': server.token}, 'tools': TOOLS}
    output = Path(__file__).with_name('extension.json')
    output.write_text(json.dumps(manifest, indent=2))
    try: output.chmod(0o600)
    except OSError: pass
    print('Import', output, 'in Cortana > Systems > Extensions. Keep this service running.', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
