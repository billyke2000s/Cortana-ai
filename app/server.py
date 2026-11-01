"""Cortana gateway. Phone access requires this launch's pairing cookie."""
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from urllib.parse import urlsplit,parse_qs,unquote
from http.cookies import SimpleCookie
import json,os,subprocess,threading,base64,secrets,re,time
from pathlib import Path
from runtime import RESOURCES,HIDDEN,qr_svg
UNPAIRED_PAGE=('<!doctype html><meta name=viewport content="width=device-width,initial-scale=1"><title>Cortana: pair your phone</title>'
 '<body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#020814;color:#e8f4ff;font:16px system-ui;text-align:center;padding:24px">'
 '<div><h1 style="color:#9fe2ff;letter-spacing:.12em">CORTANA</h1><p>This phone isn\'t paired with this session.</p>'
 '<p style="color:#a9c6e6">Scan the QR code shown in the Cortana window on your PC.<br>Each time Cortana restarts it shows a new QR code, so old links stop working.</p></div>').encode()
SETTINGS_PUBLIC=('model','voice_engine','voice','home_location','pc_controls','tools_enabled','phone_access','pc_access','expression_mode','setup_complete','native_notifications','context_mode','briefing_time','watch_folders','watch_downloads')
_weather_cache={'at':0,'key':None,'value':None}
class AppServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,runtime):
        self.runtime=runtime
        super().__init__(address,Handler)
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(RESOURCES),**kwargs)
    def log_message(self,*args):pass
    @property
    def local(self):
        host=self.headers.get('Host','').split(':')[0].lower()
        return host in ('localhost','127.0.0.1') and not self.headers.get('CF-Connecting-IP') and not self.headers.get('X-Forwarded-Host')
    def authorised(self):
        if self.local:return True
        runtime=self.server.runtime
        if self.headers.get('Host','').lower()!=runtime.tunnel_host:return False
        try:
            cookies=SimpleCookie(self.headers.get('Cookie',''));token=cookies.get('cortana_session')
            return bool(token and secrets.compare_digest(token.value,runtime.token))
        except Exception:return False
    def end_headers(self):
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer');self.send_header('Permissions-Policy','microphone=(self), camera=()');self.send_header('X-Frame-Options','DENY');super().end_headers()
    def send_data(self,data,mime,status=200):
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
    def send_json(self,value,status=200):self.send_data(json.dumps(value,default=str).encode(),'application/json; charset=utf-8',status)
    def stream_events(self,events):
        """Newline-delimited JSON, flushed per event so the page can speak the first sentence while the rest is written."""
        self.send_response(200);self.send_header('Content-Type','application/x-ndjson; charset=utf-8');self.send_header('Cache-Control','no-store')
        self.send_header('X-Accel-Buffering','no');self.close_connection=True;self.end_headers()
        try:
            for event in events:
                self.wfile.write((json.dumps(event,ensure_ascii=False,default=str)+'\n').encode('utf-8'));self.wfile.flush()
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
        except Exception as e:
            try:self.wfile.write((json.dumps({'type':'error','error':str(e) if isinstance(e,(RuntimeError,ValueError)) else 'The local service could not finish.'})+'\n').encode());self.wfile.flush()
            except OSError:pass
        finally:events.close()
    def do_GET(self):
        runtime=self.server.runtime;parsed=urlsplit(self.path);pairing=parse_qs(parsed.query).get('pair',[''])[0]
        if pairing and self.headers.get('Host','').lower()==runtime.tunnel_host and secrets.compare_digest(pairing,runtime.token):
            self.send_response(303);self.send_header('Location','/');# Lax, not Strict: the QR link is opened from the camera/scanner app (another site), and browsers drop Strict cookies on
            # navigations that start elsewhere, so the app never saw the pairing. POSTs stay protected by the Origin check below.
            self.send_header('Set-Cookie',f'cortana_session={runtime.token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000');self.send_header('Cache-Control','no-store');self.send_header('Content-Length','0');self.end_headers();return
        if not self.authorised():return self.send_data(UNPAIRED_PAGE,'text/html; charset=utf-8',403)
        if parsed.path=='/api/status':
            alerts=[{'id':i['id'],'kind':i['kind'],'text':i['text'],'due':i['due']} for i in runtime.store.due_alerts()]
            return self.send_json({'timedSpeech':os.name=='nt','ai':runtime.ai_ready,'transcription':runtime.stt_ready,'model':runtime.model,'status':runtime.status,'canPair':self.local,'phoneReady':bool(runtime.phone_url),'error':runtime.error,'voice':runtime.voice.status,'voiceReady':runtime.voice.ready,'alerts':alerts,'chooseModel':runtime.awaiting_choice,'choosePersonality':not runtime.store.get('setup_complete',False) and (runtime.model_chosen or not runtime.ask_model),'expressionMode':runtime.store.get('expression_mode','normal'),'latency':runtime.jobs.snapshot(),'wakeDetector':runtime.neural.wake_status,'lipSync':runtime.lips.status})
        if parsed.path=='/api/conversation':return self.send_json({'messages':runtime.store.recent_messages(60),'summary':runtime.store.conversation_summary()})
        if parsed.path=='/api/objectives':return self.send_json({'items':runtime.store.items(),'recent_alerts':runtime.store.recent_alerts()})
        if parsed.path=='/api/memory':return self.send_json({'facts':runtime.store.facts(),'conflicts':runtime.store.fact_conflicts(),'messages':runtime.store.recent_messages(60)})
        if parsed.path=='/api/settings':
            store=runtime.store
            return self.send_json({**{k:store.get(k) for k in SETTINGS_PUBLIC},'model':runtime.model,'voice':store.get('voice','en_US-hfc_female-medium'),
                'expression_mode':store.get('expression_mode','normal'),'context_mode':store.get('context_mode','auto'),'briefing_time':store.get('briefing_time',''),'watch_folders':store.get('watch_folders',True),'watch_downloads':store.get('watch_downloads',False),'context':runtime.context(),'setup_complete':store.get('setup_complete',False),'native_notifications':store.get('native_notifications',True),
                'voice_engine':store.get('voice_engine','piper'),'pc_controls':store.get('pc_controls',True),'tools_enabled':store.get('tools_enabled',True),'pc_access':store.get('pc_access',True),
                'phone_access':store.get('phone_access','cloudflare'),'calendar_connected':bool(store.get('calendar_url')),'brave_connected':bool(store.get('brave_key')),
                'voices':runtime.voice.catalog(),'models':runtime.installed_models(),'voice_status':runtime.voice.status})
        if parsed.path=='/api/briefing':return self.send_json(briefing(runtime))
        if parsed.path=='/api/documents':return self.send_json({'documents':runtime.store.documents(),'folders':runtime.store.get('doc_folders',[]),'canAddFolder':self.local})
        if parsed.path=='/api/events':return self.send_json({'events':runtime.store.upcoming_events()})
        if parsed.path=='/api/models':return self.send_json(runtime.models_info())
        if parsed.path=='/api/phone-qr':
            if not self.local:return self.send_json({'error':'Pairing is available on the PC only.'},403)
            if not runtime.phone_url:return self.send_json({'error':'Phone connection is starting.'},503)
            return self.send_data(qr_svg(runtime.phone_url),'image/svg+xml')
        if parsed.path=='/api/phone':
            if not self.local:return self.send_json({'error':'Pairing is available on the PC only.'},403)
            return self.send_json({'ready':bool(runtime.phone_url),'url':runtime.phone_url})
        public_path=unquote(parsed.path).replace('\\','/')
        allowed=public_path in ('/','/index.html','/app.js','/avatar.js','/pages.js','/mic-worklet.js','/responsive.css','/manifest.webmanifest','/app-icon.svg') or public_path.startswith(('/assets/','/vendor/'))
        if not allowed or '..' in public_path.split('/'):return self.send_error(404)
        super().do_GET()
    def do_POST(self):
        if not self.authorised():return self.send_json({'error':'Pair again using the QR code on your PC.'},403)
        host=self.headers.get('Host','');origin=self.headers.get('Origin');expected=('http://' if self.local else 'https://')+host
        if origin and origin!=expected:return self.send_json({'error':'Request must come from Cortana.'},403)
        if not self.headers.get('Content-Type','').startswith('application/json'):return self.send_json({'error':'JSON required.'},415)
        try:
            size=int(self.headers.get('Content-Length','0'));limit={'/api/transcribe':1500000,'/api/documents':16000000}.get(self.path,64000)
            if not 0<size<=limit:return self.send_json({'error':'Request is too large or empty.'},400)
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict):raise ValueError('Invalid request.')
            runtime=self.server.runtime
            if self.path=='/api/cancel':
                key=runtime.jobs.key(data.get('request_id'))
                if not key:raise ValueError('Request ID required.')
                runtime.jobs.cancel(key);return self.send_json({'ok':True})
            if self.path=='/api/metrics':
                value=data.get('playback_ms')
                if not isinstance(value,(int,float)) or not 0<=value<=600000:raise ValueError('Invalid playback timing.')
                with runtime.jobs.lock:runtime.jobs.metrics['playback_ms']=round(value)
                return self.send_json({'ok':True})
            if self.path=='/api/transcribe':
                audio=base64.b64decode(data.get('audio',''),validate=True)
                if data.get('wake') is True:   # wake-word burst: hint the name, decide here (testable) instead of in the page
                    from runtime import wake_match,WAKE_PROMPT
                    detected=runtime.neural.detect(audio)
                    if detected is False or (data.get('interrupt') is True and detected is None):return self.send_json({'text':'','wake':False,'rest':''})
                    try:text=runtime.transcribe(audio,WAKE_PROMPT)
                    except RuntimeError:return self.send_json({'text':'','wake':False,'rest':''})
                    rest=wake_match(text);return self.send_json({'text':text,'wake':rest is not None,'rest':rest or ''})
                return self.send_json({'text':runtime.transcribe(audio)})
            if self.path=='/api/chat':
                messages=data.get('messages',[])
                if not isinstance(messages,list) or len(messages)>20 or not all(isinstance(m,dict) for m in messages):raise ValueError('Invalid conversation.')
                return self.send_json(runtime.chat(messages))
            if self.path=='/api/speech':
                text=data.get('text','')
                if not isinstance(text,str) or not text.strip() or len(text)>3000:raise ValueError('Enter between 1 and 3000 characters.')
                with runtime.jobs.scope(data.get('request_id')):
                    return self.send_json(runtime.voice.speak(text,max(-1,min(1,int(data.get('rate',0))))))
            if self.path=='/api/chat-stream':
                messages=data.get('messages',[])
                if not isinstance(messages,list) or len(messages)>20 or not all(isinstance(m,dict) for m in messages):raise ValueError('Invalid conversation.')
                think=data.get('think',False)
                if not isinstance(think,bool):raise ValueError('Use true or false for think.')
                def events():
                    with runtime.jobs.scope(data.get('request_id')):yield from runtime.chat_stream(messages,think)
                return self.stream_events(events())
            if self.path=='/api/objectives':return self.send_json(objectives_action(runtime.store,data))
            if self.path=='/api/memory':return self.send_json(memory_action(runtime.store,data))
            if self.path=='/api/settings':return self.send_json(settings_action(runtime,data))
            if self.path=='/api/documents':return self.send_json(documents_action(runtime.store,data,self.local))
            if self.path=='/api/events':
                if data.get('action')!='remove':raise ValueError('Unknown action.')
                runtime.store.remove_event(int(data['id']));return self.send_json({'events':runtime.store.upcoming_events()})
            if self.path=='/api/models':
                tag=str(data.get('tag',''))
                if data.get('action')=='download':runtime.start_pull(tag)
                elif data.get('action')=='use':runtime.use_model(tag)
                else:raise ValueError('Unknown action.')
                return self.send_json(runtime.models_info())
            self.send_json({'error':'Unknown endpoint.'},404)
        except ValueError as e:self.send_json({'error':str(e) if str(e) and not str(e).startswith(('invalid literal','could not convert','Expecting')) else 'Invalid request or audio format.'},400)
        except (TypeError,KeyError):self.send_json({'error':'Invalid request or audio format.'},400)
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception as e:self.send_json({'error':str(e) if isinstance(e,RuntimeError) else 'The local service could not finish. Check the Cortana launcher.'},503)
def objectives_action(store,data):
    import tools
    action=data.get('action')
    if action=='add':
        kind=data.get('kind','task');text=str(data.get('text','')).strip()
        if not text:raise ValueError('Text required.')
        due=None
        if kind=='timer':due=time.time()+max(.05,min(1440,float(data.get('minutes',5))))*60
        elif kind=='reminder':due=tools.parse_local_time(data.get('at',''))
        elif kind!='task':raise ValueError('Unknown type.')
        store.add_item(kind,text,due)
    elif action=='snooze':store.snooze(int(data['id']),data.get('minutes',10))
    elif action in ('complete','delete','ack'):
        getattr(store,{'complete':'complete_item','delete':'delete_item','ack':'acknowledge'}[action])(int(data['id']))
    else:raise ValueError('Unknown action.')
    return {'items':store.items()}
def memory_action(store,data):
    action=data.get('action')
    if action=='forget':store.forget_fact(fact_id=int(data['id']))
    elif action=='add':store.add_fact(data.get('text',''))
    elif action=='edit':store.edit_fact(int(data['id']),data.get('text',''))
    elif action=='clear_history':store.clear_messages()
    else:raise ValueError('Unknown action.')
    return {'facts':store.facts(),'messages':store.recent_messages(60)}
def settings_action(runtime,data):
    store=runtime.store
    if 'model' in data:
        model=str(data['model'])
        if not re.fullmatch(r'[\w.:/-]{1,80}',model):raise ValueError('Invalid model.')
        runtime.use_model(model)   # refuses models that are too big for this PC or not downloaded
    if 'home_location' in data:store.set('home_location',str(data['home_location']).strip()[:80])
    if 'calendar_url' in data:
        url=str(data['calendar_url']).strip()
        if url and not re.fullmatch(r'https://\S{10,800}',url):raise ValueError('The calendar address must start with https://')
        store.set('calendar_url',url)
    if 'brave_key' in data:store.set('brave_key',str(data['brave_key']).strip()[:120])
    if 'context_mode' in data:
        if data['context_mode'] not in ('auto','standard'):raise ValueError('Choose Auto or Standard memory size.')
        store.set('context_mode',data['context_mode'])
    if 'expression_mode' in data:
        if data['expression_mode'] not in ('normal','expressive'):raise ValueError('Choose Normal or Expressive.')
        store.set('expression_mode',data['expression_mode'])
    if 'briefing_time' in data:
        at=data['briefing_time']
        if not isinstance(at,str) or (at and not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d',at)):raise ValueError('Use a time like 07:30, or leave it empty.')
        store.set('briefing_time',at)
    for key in ('setup_complete','native_notifications','watch_folders','watch_downloads'):
        if key in data:
            if not isinstance(data[key],bool):raise ValueError('Use true or false for '+key+'.')
            store.set(key,data[key])
    if 'voice_engine' in data and data['voice_engine'] not in ('piper','windows','zipvoice'):raise ValueError('Unknown voice engine.')
    for key in ('pc_controls','tools_enabled','pc_access'):
        if key in data:store.set(key,bool(data[key]))
    if data.get('phone_access') in ('cloudflare','tailscale'):store.set('phone_access',data['phone_access'])
    if data.get('voice_engine') in ('piper','windows','zipvoice') or data.get('voice'):
        voice=data.get('voice')
        if voice and voice not in [v['name'] for v in runtime.voice.catalog()]:raise ValueError('Unknown voice.')
        runtime.voice.switch(data.get('voice_engine'),voice)
    return {'ok':True}
def documents_action(store,data,local):
    """Add a dropped file (base64), add a whole folder (PC only), or remove a document."""
    import files
    action=data.get('action')
    if action=='remove':store.remove_document(int(data['id']))
    elif action=='add':
        name=os.path.basename(str(data.get('name','')).replace('\\','/'))[:160]
        if not name:raise ValueError('File name missing.')
        raw=base64.b64decode(str(data.get('data','')),validate=True)
        if not raw:raise ValueError('That file is empty.')
        text,pages=files.extract_text(name,raw)
        if not text.strip():raise ValueError('No readable text in that file.')
        did=store.add_document(name,text,files.chunks(text),pages)
        return {'added':{'id':did,'name':name,'pages':pages,'chars':len(text)},'documents':store.documents()}
    elif action=='add_folder':
        if not local:raise ValueError('Folders can only be added on the PC itself.')
        folder=Path(str(data.get('path','')).strip().strip('"')).expanduser()
        if not str(folder).strip() or not folder.is_dir():raise ValueError('That folder does not exist.')
        added,skipped=[],[]
        import proactive
        candidates=proactive.folder_candidates(folder)
        for p in candidates:
            try:
                if p.stat().st_size>files.MAX_FILE_BYTES:raise ValueError('too large')
                text,pages=files.extract_text(p.name,p.read_bytes())
                if text.strip():store.add_document(p.name,text,files.chunks(text),pages,str(p));added.append(p.name)
                else:skipped.append(p.name)
            except Exception:skipped.append(p.name)
        if not candidates:raise ValueError('No PDF, Word, PowerPoint or text files in that folder.')
        store.set('doc_folders',(store.get('doc_folders',[])+[str(folder)])[-20:])
        if store.get('watch_seen',None) is not None:proactive.mark_seen(store,candidates)   # already read: no "new document" notices
        return {'added_count':len(added),'skipped':skipped[:20],'documents':store.documents()}
    else:raise ValueError('Unknown action.')
    return {'documents':store.documents()}
def briefing(runtime):
    import tools
    store=runtime.store;out={'items':store.items(),'weather':None,'events':None}
    home=store.get('home_location','')
    if home:
        try:
            if _weather_cache['key']!=home or time.time()-_weather_cache['at']>600:
                _weather_cache.update(key=home,at=time.time(),value=tools.weather('',home))
            out['weather']=_weather_cache['value']
        except Exception:out['weather']={'error':'Weather is unavailable right now. Check the internet connection.'}
    if store.get('calendar_url') or store.events_between(time.time()-86400,time.time()+86400):
        try:out['events']=tools.day_events(store,'today')
        except Exception:out['events']={'error':'Could not read your calendar. Check the address in Systems and the internet connection.'}
    return out
if __name__=='__main__':
    from launcher import main
    main()
