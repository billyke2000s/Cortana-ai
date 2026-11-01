"""Agent regression tests: real files, result verification, permissions and model-selected dispatch."""
import base64
import http.client
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import test_offline as b
import agent
import connections

class AgentTests(unittest.TestCase):
    def setUp(self):
        self.r=b.runtime.Runtime();self.r.store.close();self.r.store=b.store.Store(':memory:');self.r.ai_ready=True
        self.a=self.r.agent;self.w=self.a.workspace;self.w.home=Path(tempfile.mkdtemp(dir=b.runtime.DATA));self.w.journal=Path(tempfile.mkdtemp(dir=b.runtime.DATA))
    def tearDown(self):self.r.close();self.r.store.close()
    def run_tool(self,name,args,category):return self.a.run(name,args,[category])[0]
    def test_changes_undo_and_newer_edit_guard(self):
        result=self.run_tool('manage_files',{'action':'write','path':'notes.txt','text':'first'},'files')
        self.assertTrue(result['verified']);self.assertEqual((self.w.home/'notes.txt').read_text(),'first')
        self.assertEqual(self.r.store.agent_get(result['artifact']['id'],'artifact')['name'],'notes.txt')
        next_result=self.w.files({'action':'append','path':'notes.txt','text':' second'})
        with self.assertRaises(ValueError):self.w.undo(result['undo'])
        self.w.undo(next_result['undo']);self.assertEqual((self.w.home/'notes.txt').read_text(),'first')
        self.w.undo(result['undo']);self.assertFalse((self.w.home/'notes.txt').exists())
    def test_boundaries_symlinks_internal_data_and_off_switches(self):
        for path in ('../escape.txt',str(b.runtime.DATA/'cortana.db')):
            with self.assertRaises(ValueError):self.w.path(path)
        if os.name!='nt':
            (self.w.home/'escape').symlink_to(Path('/tmp'),target_is_directory=True)
            with self.assertRaises(ValueError):self.w.path('escape/out.txt')
        self.r.store.set('pc_access',False)
        self.assertIn('error',self.run_tool('manage_files',{'action':'write','path':'x.txt','text':'bad'},'files'))
        self.assertFalse((self.w.home/'x.txt').exists())
        self.r.store.set('tools_enabled',False)
        self.assertIn('error',self.a.run('discover_tools',{'category':'files'},[])[0])
    def test_move_duplicates_and_recovery(self):
        self.w.files({'action':'write','path':'a.txt','text':'same'})
        copied=self.w.files({'action':'copy','path':'a.txt','destination':'b.txt'})
        self.assertEqual(len(self.w.files({'action':'duplicates','path':str(self.w.home)})['duplicates']),1)
        removed=self.w.files({'action':'trash','path':'b.txt'});self.assertFalse((self.w.home/'b.txt').exists())
        self.w.undo(removed['undo']);self.assertEqual((self.w.home/'b.txt').read_text(),'same')
    def test_document_and_spreadsheet_outputs(self):
        try:import docx,reportlab,openpyxl
        except ImportError:self.skipTest('Install requirements.txt for office output tests.')
        for fmt in ('docx','pdf'):
            result=self.w.document({'format':fmt,'path':'report.'+fmt,'title':'Test <report>','sections':[{'heading':'Results','text':'Calculated total is 30.','bullets':['First','Second'],'table':[['A','B'],['1','2']]}]})
            self.assertTrue(result['verified']);self.assertGreater((self.w.home/('report.'+fmt)).stat().st_size,100)
        for fmt in ('csv','xlsx'):
            self.w.spreadsheet({'action':'write','path':'costs.'+fmt,'rows':[['Item','Cost'],['A',10],['B',20]]})
            self.assertEqual(self.w.spreadsheet({'action':'analyse','path':'costs.'+fmt,'column':1})['sum'],30)
        result=self.w.spreadsheet({'action':'chart','path':'costs.xlsx','column':1,'label_column':0})
        wb=openpyxl.load_workbook(self.w.home/'costs.xlsx');self.assertEqual(len(wb.active._charts),1);wb.close()
        with self.assertRaises(ValueError):self.w.spreadsheet({'action':'write','path':'bad.csv','rows':[["=cmd|' /C bad'!A0"]]})
    def test_discovery_is_model_decision_with_unfamiliar_wording(self):
        replies=iter([
            {'tool_calls':[{'function':{'name':'discover_tools','arguments':{'category':'files'}}}]},
            {'tool_calls':[{'function':{'name':'manage_files','arguments':{'action':'write','path':'haiku.txt','text':'Quiet blue light'}}}]},
            {'content':'Saved the poem in haiku.txt.'}])
        payloads=[]
        def model(payload):payloads.append(json.loads(json.dumps(payload)));yield {'message':next(replies)}
        with patch.object(self.r,'ollama_stream',model),patch('runtime.weather_question',side_effect=AssertionError('No phrase routing allowed')):
            events=list(self.r.chat_stream([{'role':'user','content':'Give those words a home on disk, call it haiku.'}]))
        self.assertEqual((self.w.home/'haiku.txt').read_text(),'Quiet blue light')
        self.assertEqual(payloads[0]['messages'][-1]['role'],'user')
        self.assertNotIn('manage_files',[t['function']['name'] for t in payloads[0]['tools']])
        self.assertIn('manage_files',[t['function']['name'] for t in payloads[1]['tools']])
        self.assertTrue(any(e['type']=='activity' and e.get('artifact') for e in events));self.assertEqual(events[-1]['type'],'done')
    def test_rejects_unadvertised_or_invalid_tools(self):
        self.assertIn('error',self.a.run('manage_files',{'action':'write','path':'bad.txt'},[])[0])
        self.assertIn('error',self.a.run('discover_tools',{'category':'not_real'},[])[0])
        self.assertIn('error',self.run_tool('spreadsheet',{'action':'analyse','path':'x.csv','column':'0'},'spreadsheets'))
    def test_approval_is_exact_once_and_cannot_be_set_by_model(self):
        calls=[]
        def browser(args,approved=False):
            if not approved:return {'approval_required':True,'reason':'Submit test form','context':{'to':'test@example.invalid','body':'Reviewed body'}}
            calls.append(args);return {'verified':True}
        with patch.object(self.a.browser,'call',browser):
            pending=self.run_tool('browser',{'action':'click','ref':'1','revision':2},'browser')
            self.assertFalse(calls);self.assertTrue(pending['approval_required'])
            self.assertTrue(self.a.review(pending['approval_id'],True)['verified'])
            self.assertEqual(calls,[{'action':'click','ref':'1','revision':2}])
            with self.assertRaises(ValueError):self.a.review(pending['approval_id'],True)
            another=self.run_tool('browser',{'action':'click','ref':'2','revision':2},'browser')
            self.a.review(another['approval_id'],False);self.assertEqual(len(calls),1)
    def test_background_goals_and_context_limits(self):
        job=self.a.automation({'action':'create','goal':'Summarise the files','interval_seconds':60})
        self.assertTrue(job['enabled']);self.assertEqual(self.a.automation({'action':'pause','id':job['id']})['enabled'],False)
        with self.assertRaises(ValueError):self.a.automation({'action':'create','goal':'bad','interval_seconds':1})
        with self.assertRaises(ValueError):self.a.automation({'action':'create','goal':'bad','watch':True,'folder':'../'})
        self.r.hw={'vram_gb':8,'ram_gb':32};self.assertEqual(self.a.context_choices(),[6144])
        self.r.hw={'vram_gb':24,'ram_gb':64};self.assertIn(32768,self.a.context_choices())
    def test_missing_docker_is_error_without_host_execution(self):
        with patch('workspace.shutil.which',return_value=None),patch('workspace.subprocess.run') as run:
            result=self.run_tool('run_python',{'code':'print(2+2)'},'code')
        self.assertIn('Docker',result['error']);run.assert_not_called()
    def test_service_config_secrets_and_email_draft_review(self):
        configs=connections.configure(self.r.store,{'name':'inbox','config':{'type':'email','imap':'imap.example.invalid','smtp':'smtp.example.invalid','username':'test@example.invalid','password':'secret-value'}})
        self.assertNotIn('secret-value',json.dumps(configs))
        draft=connections.operate(self.a,{'action':'email_draft','connection':'inbox','to':'other@example.invalid','subject':'Test','body':'A reviewable message'})
        with patch('connections.smtplib.SMTP_SSL') as smtp:
            pending=self.run_tool('connected_service',{'action':'email_send','connection':'inbox','id':draft['draft_id']},'connections')
            smtp.assert_not_called();self.assertEqual(pending['context']['body'],'A reviewable message')
        for url in ('file:///tmp','https://name:secret@example.com/api','https://example.com/api?token=secret','http://example.com'):
            with self.assertRaises(ValueError):connections.endpoint(url)
    def test_local_image_is_passed_to_local_vision(self):
        try:from PIL import Image
        except ImportError:self.skipTest('Pillow not installed')
        Image.new('RGB',(100,100),'blue').save(self.w.home/'diagram.png')
        with patch.object(self.r,'complete',return_value='A blue diagram') as model:
            result=self.run_tool('inspect_media',{'paths':['diagram.png'],'question':'Describe this'},'vision')
        self.assertEqual(result['answer'],'A blue diagram');self.assertEqual(len(model.call_args.args[1]),1)

class AgentApiTests(unittest.TestCase):
    # Only HTTP-specific methods; inherited checks also run against this fixture.
    def setUp(self):
        AgentTests.setUp(self);self.srv=b.server.AppServer(('127.0.0.1',0),self.r);threading.Thread(target=self.srv.serve_forever,daemon=True).start()
    def tearDown(self):self.srv.shutdown();self.srv.server_close();AgentTests.tearDown(self)
    def request(self,method,path,data=None,extra=None):
        c=http.client.HTTPConnection('127.0.0.1',self.srv.server_address[1]);headers={'Content-Type':'application/json',**(extra or {})}
        c.request(method,path,json.dumps(data) if data is not None else None,headers);r=c.getresponse();status=r.status;headers=dict(r.headers);body=r.read();c.close();return status,headers,body
    def test_agent_routes_artifacts_and_authorisation(self):
        status,_,body=self.request('POST','/api/agent-upload',{'name':'notes.txt','data':base64.b64encode(b'Uploaded notes').decode()})
        self.assertEqual(status,200);item=json.loads(body)
        status,headers,body=self.request('GET',item['download']);self.assertEqual(body,b'Uploaded notes');self.assertIn('attachment',headers['Content-Disposition'])
        self.assertEqual(self.request('GET',item['download'],extra={'Host':'unpaired.example'})[0],403)
        self.assertEqual(self.request('POST','/api/agent',{'action':'preferences','reasoning':'deep','context_tokens':32768})[0],400)
        self.assertEqual(self.request('POST','/api/agent',{'action':'preferences','reasoning':'deep','context_tokens':6144})[0],200)
        self.assertEqual(self.request('POST','/api/agent',{'action':'preferences','reasoning':'fast','context_tokens':6144},extra={'Origin':'https://evil.invalid'})[0],403)
        for module in ('agent','workspace','browser_agent','pc_agent','connections'):
            self.assertEqual(self.request('GET','/'+module+'.py')[0],404)

class ConnectionProtocolTests(unittest.TestCase):
    def setUp(self):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        self.calls=[];outer=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def send(self,value,mime='application/json'):
                raw=value.encode() if isinstance(value,str) else json.dumps(value).encode();self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Mcp-Session-Id','fixture-session');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));outer.calls.append((self.path,body,dict(self.headers)))
                method=body['method']
                if method=='notifications/initialized':self.send({});return
                result={'initialize':{'protocolVersion':'2025-11-25','capabilities':{}},'tools/list':{'tools':[{'name':'calendar_list','description':'Read calendar fixture','inputSchema':{'type':'object','properties':{}}}]},'tools/call':{'content':[{'type':'text','text':'Study at 15:00'}]}}[method]
                self.send({'jsonrpc':'2.0','id':body['id'],'result':result})
            def do_REPORT(self):
                outer.calls.append(('REPORT',self.rfile.read(int(self.headers['Content-Length'])),dict(self.headers)))
                self.send('<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:response><d:propstat><d:prop><c:calendar-data>BEGIN:VEVENT\nSUMMARY:Study\nEND:VEVENT</c:calendar-data></d:prop></d:propstat></d:response></d:multistatus>','application/xml')
            def do_PUT(self):
                outer.calls.append(('PUT',self.rfile.read(int(self.headers['Content-Length'])),dict(self.headers)));self.send('','text/plain')
        self.srv=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=self.srv.serve_forever,daemon=True).start()
        self.url='http://127.0.0.1:'+str(self.srv.server_address[1]);self.r=b.runtime.Runtime();self.r.store.close();self.r.store=b.store.Store(':memory:')
    def tearDown(self):self.srv.shutdown();self.srv.server_close();self.r.close();self.r.store.close()
    def test_real_mcp_handshake_catalog_and_explicit_read_tool(self):
        connections.configure(self.r.store,{'name':'plugin','config':{'type':'mcp','url':self.url+'/mcp','token':'do-not-return','read_tools':['calendar_list']}})
        catalog=connections.operate(self.r.agent,{'action':'tools','connection':'plugin'})
        self.assertEqual(catalog['tools'][0]['name'],'calendar_list')
        result=connections.operate(self.r.agent,{'action':'call','connection':'plugin','tool':'calendar_list','arguments':{}})
        self.assertIn('Study at 15:00',json.dumps(result));self.assertEqual(self.calls[-1][2]['Mcp-Session-Id'],'fixture-session')
        self.assertNotIn('do-not-return',json.dumps(connections.summaries(self.r.store)))
    def test_real_caldav_report_and_reviewed_write(self):
        connections.configure(self.r.store,{'name':'calendar','config':{'type':'caldav','url':self.url+'/calendar','username':'user','password':'never-return'}})
        result=connections.operate(self.r.agent,{'action':'calendar_list','connection':'calendar'});self.assertIn('SUMMARY:Study',result['calendar_data'][0])
        args={'action':'calendar_add','connection':'calendar','arguments':{'title':'Study, revision','day':'tomorrow','time':'15:00','minutes':45}}
        pending=self.r.agent.run('connected_service',args,['connections'])[0]
        self.assertTrue(pending['approval_required']);self.assertFalse(any(c[0]=='PUT' for c in self.calls))
        result=self.r.agent.review(pending['approval_id'],True);self.assertTrue(result['created_on_server'])
        written=next(c for c in self.calls if c[0]=='PUT');self.assertIn(b'SUMMARY:Study\\, revision',written[1]);self.assertIn('Basic ',written[2]['Authorization'])
