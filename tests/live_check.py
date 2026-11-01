"""Live end-to-end check of a running Cortana (real Ollama, Whisper, voice, phone tunnel). Not part of the offline suite."""
import urllib.request,urllib.error,json,http.cookiejar,base64,time
from pathlib import Path
import os
# Live check against a running Cortana on Windows:  Cortana.exe --port 8777   then   python tests/live_check.py
BASE=os.environ.get('CORTANA_URL','http://127.0.0.1:8777')
def get(url,opener=urllib.request):
 with (opener.open(url,timeout=35) if hasattr(opener,'open') else opener.urlopen(url,timeout=35)) as r:return r.read()
def post(path,data,headers=None):
 req=urllib.request.Request(BASE+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json',**(headers or {})})
 return json.loads(get(req))
def expect_error(url,code):
 try:get(url);raise AssertionError('Expected HTTP '+str(code))
 except urllib.error.HTTPError as e:assert e.code==code,(e.code,code)
report={}
status=json.loads(get(BASE+'/api/status'));assert status['ai'] and status['transcription'];report['local_ready']=True
for path in ['/server.py','/runtime.py','/assets/%2e%2e/runtime.py','/vendor/%2e%2e/launcher.py']:
 expect_error(BASE+path,404)
report['private_files_blocked']=True
phone=json.loads(get(BASE+'/api/phone'));assert phone['ready']
url=phone['url'];root=url.split('/?')[0]
expect_error(root+'/',403);report['remote_requires_pairing']=True
jar=http.cookiejar.CookieJar();opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
get(url,opener)
remote_status=json.loads(get(root+'/api/status',opener));assert remote_status['ai'] and not remote_status['canPair'];report['remote_pairing']=True
assert get(root+'/assets/cortana.glb',opener)[:4]==b'glTF';report['remote_model_loaded']=True
try:get(root+'/api/phone-qr',opener);raise AssertionError('Phone must not distribute pairing codes')
except urllib.error.HTTPError as e:assert e.code==403
report['pairing_control_restricted']=True
speech=post('/api/speech',{'text':'Hello Chief. The blue moon is bright tonight.','rate':0});report['speech_events']=len(speech['visemes'])
import wave,io
if wave.open(io.BytesIO(base64.b64decode(speech['audio']))).getframerate()==16000:
 started=time.monotonic();text=post('/api/transcribe',{'audio':speech['audio']})['text'];report['transcription_seconds']=round(time.monotonic()-started,2);report['transcription']=text;assert 'moon' in text.lower() and 'bright' in text.lower()
else:report['transcription']='skipped: the natural voice is 22 kHz; transcription test needs 16 kHz audio'
started=time.monotonic();reply=post('/api/chat',{'messages':[{'role':'user','content':'Hello Cortana. Briefly introduce yourself in one sentence.'}]})['reply'];report['reply_seconds']=round(time.monotonic()-started,2);report['reply']=reply;assert reply.strip()
try:post('/api/chat',{'messages':[]},headers={'Origin':'https://unrelated.example'});raise AssertionError('Cross-origin request must fail')
except urllib.error.HTTPError as e:assert e.code==403
report['cross_origin_blocked']=True
# Upgrade checks: streaming chat, objectives, memory, settings, new page file
def stream(messages):
 req=urllib.request.Request(BASE+'/api/chat-stream',data=json.dumps({'messages':messages}).encode(),headers={'Content-Type':'application/json'})
 return [json.loads(l) for l in get(req).decode().splitlines() if l.strip()]
events=stream([{'role':'user','content':'Set a timer for 2 minutes called verification test.'}])
report['stream_event_types']=sorted({e['type'] for e in events});assert events[-1]['type']=='done'
report['timer_tool_used']=any(e['type']=='tool' and e['name']=='set_timer' for e in events)
items=json.loads(get(BASE+'/api/objectives'))['items'];report['objectives']=[i['text'] for i in items]
for i in items:
 if 'verification' in i['text'].lower():post('/api/objectives',{'action':'delete','id':i['id']})
settings=json.loads(get(BASE+'/api/settings'));report['model']=settings['model'];report['voice']=settings['voice_status']
assert 'calendar_url' not in settings and 'brave_key' not in settings;report['secrets_hidden']=True
assert get(BASE+'/pages.js')[:2];report['pages_served']=True
speech=post('/api/speech',{'text':'Upgrade check complete.','rate':0});report['speech_voice']=speech.get('voice')
Path('live-check-report.json').write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps(report,indent=2))
