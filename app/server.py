"""Cortana gateway. Phone access requires this launch's pairing cookie."""
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from urllib.parse import urlsplit,parse_qs,unquote
from http.cookies import SimpleCookie
import json,os,subprocess,threading,base64,secrets,re,time
from runtime import RESOURCES,HIDDEN,qr_svg
UNPAIRED_PAGE=('<!doctype html><meta name=viewport content="width=device-width,initial-scale=1"><title>Cortana: pair your phone</title>'
 '<body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#020814;color:#e8f4ff;font:16px system-ui;text-align:center;padding:24px">'
 '<div><h1 style="color:#9fe2ff;letter-spacing:.12em">CORTANA</h1><p>This phone isn\'t paired with this session.</p>'
 '<p style="color:#a9c6e6">Scan the QR code shown in the Cortana window on your PC.<br>Each time Cortana restarts it shows a new QR code, so old links stop working.</p></div>').encode()
SETTINGS_PUBLIC=('model','voice_engine','voice','home_location','pc_controls','tools_enabled','phone_access')
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
            alerts=[{'id':i['id'],'kind':i['kind'],'text':i['text']} for i in runtime.store.due_alerts()]
            return self.send_json({'timedSpeech':os.name=='nt','ai':runtime.ai_ready,'transcription':runtime.stt_ready,'model':runtime.model,'status':runtime.status,'canPair':self.local,'phoneReady':bool(runtime.phone_url),'error':runtime.error,'voice':runtime.voice.status,'alerts':alerts,'chooseModel':runtime.awaiting_choice})
        if parsed.path=='/api/objectives':return self.send_json({'items':runtime.store.items()})
        if parsed.path=='/api/memory':return self.send_json({'facts':runtime.store.facts(),'messages':runtime.store.recent_messages(60)})
        if parsed.path=='/api/settings':
            store=runtime.store
            return self.send_json({**{k:store.get(k) for k in SETTINGS_PUBLIC},'model':runtime.model,'voice':store.get('voice','en_US-hfc_female-medium'),
                'voice_engine':store.get('voice_engine','piper'),'pc_controls':store.get('pc_controls',True),'tools_enabled':store.get('tools_enabled',True),
                'phone_access':store.get('phone_access','cloudflare'),'calendar_connected':bool(store.get('calendar_url')),'brave_connected':bool(store.get('brave_key')),
                'voices':runtime.voice.catalog(),'models':runtime.installed_models(),'voice_status':runtime.voice.status})
        if parsed.path=='/api/briefing':return self.send_json(briefing(runtime))
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
            size=int(self.headers.get('Content-Length','0'));limit=1500000 if self.path=='/api/transcribe' else 64000
            if not 0<size<=limit:return self.send_json({'error':'Request is too large or empty.'},400)
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict):raise ValueError('Invalid request.')
            runtime=self.server.runtime
            if self.path=='/api/transcribe':return self.send_json({'text':runtime.transcribe(base64.b64decode(data.get('audio',''),validate=True))})
            if self.path=='/api/chat':
                messages=data.get('messages',[])
                if not isinstance(messages,list) or len(messages)>20 or not all(isinstance(m,dict) for m in messages):raise ValueError('Invalid conversation.')
                return self.send_json(runtime.chat(messages))
            if self.path=='/api/speech':
                text=data.get('text','')
                if not isinstance(text,str) or not text.strip() or len(text)>3000:raise ValueError('Enter between 1 and 3000 characters.')
                return self.send_json(runtime.voice.speak(text,max(-1,min(1,int(data.get('rate',0))))))
            if self.path=='/api/chat-stream':
                messages=data.get('messages',[])
                if not isinstance(messages,list) or len(messages)>20 or not all(isinstance(m,dict) for m in messages):raise ValueError('Invalid conversation.')
                return self.stream_events(runtime.chat_stream(messages))
            if self.path=='/api/objectives':return self.send_json(objectives_action(runtime.store,data))
            if self.path=='/api/memory':return self.send_json(memory_action(runtime.store,data))
            if self.path=='/api/settings':return self.send_json(settings_action(runtime,data))
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
    elif action in ('complete','delete','ack'):
        getattr(store,{'complete':'complete_item','delete':'delete_item','ack':'acknowledge'}[action])(int(data['id']))
    else:raise ValueError('Unknown action.')
    return {'items':store.items()}
def memory_action(store,data):
    action=data.get('action')
    if action=='forget':store.forget_fact(fact_id=int(data['id']))
    elif action=='add':store.add_fact(data.get('text',''))
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
    for key in ('pc_controls','tools_enabled'):
        if key in data:store.set(key,bool(data[key]))
    if data.get('phone_access') in ('cloudflare','tailscale'):store.set('phone_access',data['phone_access'])
    if data.get('voice_engine') in ('piper','windows') or data.get('voice'):
        voice=data.get('voice')
        if voice and voice not in [v['name'] for v in runtime.voice.catalog()]:raise ValueError('Unknown voice.')
        runtime.voice.switch(data.get('voice_engine'),voice)
    return {'ok':True}
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
    if store.get('calendar_url'):
        try:out['events']=tools.calendar(store.get('calendar_url'),'today')
        except Exception:out['events']={'error':'Could not read your calendar. Check the address in Systems and the internet connection.'}
    return out
if __name__=='__main__':
    from launcher import main
    main()
