"""Launch the actual bundle with a scripted Ollama transport; verify office/PDF-vision/browser dependencies execute."""
import base64,json,os,subprocess,sys,tempfile,threading,time,urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
scenario={};observed=[]
class Model(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def respond(self,value,stream=False):
        raw=(json.dumps(value)+('\n' if stream else '')).encode();self.send_response(200);self.send_header('Content-Type','application/x-ndjson' if stream else 'application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_GET(self):self.respond({'models':[{'name':'qwen3.5:4b'}]})
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path!='/api/chat':self.respond({'done':True});return
        if body.get('stream') is False:
            assert body['messages'][-1].get('images'),'Vision did not send an image'
            self.respond({'message':{'content':'The rendered report says Systems online.'}});return
        last=body['messages'][-1]
        if last['role']!='tool':name='discover_tools';args={'category':scenario['category']}
        elif last.get('tool_name')=='discover_tools':name=scenario['tool'];args=scenario['arguments']
        else:
            observed.append(json.loads(last['content']));self.respond({'message':{'content':'Completed the bundle check.'},'done':True},True);return
        self.respond({'message':{'tool_calls':[{'function':{'name':name,'arguments':args}}]},'done':True},True)
model=ThreadingHTTPServer(('127.0.0.1',0),Model);threading.Thread(target=model.serve_forever,daemon=True).start()
data=Path(tempfile.mkdtemp(prefix='cortana-agent-bundle-'));env={**os.environ,'CORTANA_DATA_DIR':str(data),'CORTANA_MODEL':'qwen3.5:4b','CORTANA_OLLAMA_URL':'http://127.0.0.1:'+str(model.server_address[1]),'CORTANA_BROWSER_HEADLESS':'1'}
p=subprocess.Popen([sys.argv[1] if len(sys.argv)>1 else 'dist/Cortana.exe','--headless','--no-open','--no-tunnel'],env=env)
def call(path,body=None):
    req=urllib.request.Request(url+path,json.dumps(body).encode() if body is not None else None,{'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=120) as r:return r.read()
try:
    deadline=time.monotonic()+120
    while not (data/'launch-state.json').exists():
        if p.poll() is not None:raise RuntimeError('Bundle exited before opening its gateway.')
        if time.monotonic()>deadline:raise RuntimeError('Bundle startup timed out.')
        time.sleep(.2)
    url=json.loads((data/'launch-state.json').read_text())['url']
    while not json.loads(call('/api/status'))['ai']:
        if time.monotonic()>deadline:raise RuntimeError('Bundle model startup timed out.')
        time.sleep(.2)
    tests=[('documents','create_document',{'format':'docx','path':'smoke.docx','title':'Status','sections':[{'text':'Systems online.'}]}),
           ('documents','create_document',{'format':'pdf','path':'smoke.pdf','title':'Status','sections':[{'text':'Systems online.'}]}),
           ('spreadsheets','spreadsheet',{'action':'write','path':'smoke.xlsx','rows':[['Item','Cost'],['A',10]]}),
           ('vision','inspect_media',{'paths':['smoke.pdf'],'question':'Read this report'}),
           ('browser','browser',{'action':'navigate','url':'https://example.com'})]
    for category,tool,arguments in tests:
        scenario.update(category=category,tool=tool,arguments=arguments)
        result=call('/api/chat-stream',{'messages':[{'role':'user','content':'Execute the current bundle fixture.'}],'request_id':'bundle_'+str(len(observed))})
        assert observed and 'error' not in observed[-1],(tool,result,observed)
        if tool in ('create_document','spreadsheet'):
            artifact=observed[-1]['artifact'];raw=call(artifact['download']);assert len(raw)>100
        if tool=='browser':assert 'Example Domain' in observed[-1]['text'],observed[-1]
        print('BUILT EXE',category,tool,'PASS',flush=True)
finally:
    subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True,timeout=20) if os.name=='nt' else p.terminate()
    p.wait(timeout=20);model.shutdown();model.server_close()
