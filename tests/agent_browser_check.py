"""Actual Playwright browser actions against a local fixture, with the production approval implementation."""
import os,sys,tempfile,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
sys.path[:0]=['app'];os.environ['CORTANA_BROWSER_HEADLESS']='1';os.environ.setdefault('CORTANA_DATA_DIR',tempfile.mkdtemp())
from runtime import Runtime
from browser_agent import Browser
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        body=b'<title>Browser fixture</title><h1>Mission form</h1><form method="POST"><label>Name<input name="name" aria-label="Name"></label><button>Send report</button></form>'
        self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length',0)));body=b'<title>Submitted</title><h1>Report accepted</h1>'
        self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
s=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=s.serve_forever,daemon=True).start();url='http://127.0.0.1:'+str(s.server_address[1])
r=Runtime();r.agent.browser=Browser(r,allowed=lambda u:u.startswith(url+'/'))
b=r.agent.browser
try:
    snapshot=b.call({'action':'navigate','url':url+'/'})
    field=next(e for e in snapshot['elements'] if e['name']=='Name');snapshot=b.call({'action':'fill','ref':field['ref'],'revision':snapshot['revision'],'text':'Blue team'})
    submit=next(e for e in snapshot['elements'] if e['name']=='Send report')
    args={'action':'click','ref':submit['ref'],'revision':snapshot['revision']}
    pending=r.agent.run('browser',args,['browser'])[0];assert pending['approval_required'],pending
    assert pending['context']['fields'][0]['value']=='Blue team',pending
    result=r.agent.review(pending['approval_id'],True);assert 'Report accepted' in result['text'],result
    try:b.call(args);raise AssertionError('Old reference accepted')
    except (ValueError,RuntimeError):pass
    print('BROWSER: navigate, snapshot, fill verification, concrete review, submit and stale-reference guard PASS',flush=True)
finally:r.close();b.thread.join(10) if b.thread else None;s.shutdown();s.server_close();r.store.close()
