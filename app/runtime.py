"""Cortana's local service lifecycle, model selection and phone pairing."""
from pathlib import Path
import os, sys, json, shutil, subprocess, urllib.request, urllib.error, zipfile, threading, time, secrets, re, hashlib, socket

RESOURCES=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
DATA=Path(os.environ.get('CORTANA_DATA_DIR',str(Path(os.environ.get('LOCALAPPDATA',Path.home()))/'CortanaAI')))
HIDDEN=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
MODEL='qwen3.5:9b'          # smarter default; ~30 tokens/s on an 8 GB RTX 3070
FAST_MODEL='qwen3.5:4b'     # automatic fallback and 'Fast' option in Settings
CONTEXT=6144                # room for prompt, tools, memory, history and a long reply (9B: ~21 tokens/s on a 3070)
SYSTEM_PROMPT=("You are Cortana, a warm, capable personal AI companion with dry wit, running on the user's own PC. "
 "Answer the user's question directly in natural, concise sentences, usually under 60 words. Respect requested answer lengths. Occasionally call the user Chief, not every turn. "
 "Be curious and supportive; a little playful, never needlessly insulting. "
 "You have tools: timers, reminders, a to-do list called objectives, long-term memory, weather, web search, PC media, volume and app controls, and the user's calendar. "
 "Use a tool whenever it helps instead of guessing, and never claim you did something unless a tool result confirms it. If a tool reports an error, say so plainly. "
 "When the user tells you something lasting about themselves or asks you to remember something, use the remember tool. "
 "For facts that may have changed or that you are unsure of, use web_search and say where the answer came from. "
 "Do not pretend to have read private information. Never invent system glitches, reboots, diagnostics or personal experiences as a joke. Admit uncertainty. Do not add unrelated filler or unnecessary follow-up questions. "
 "Speak with confidence and just do what is asked: if asked for a joke, a story or an opinion, give one straight away. Never say you can't do something you can do in conversation, and never apologise for being an AI. "
 "For anything meant to be read rather than heard (code, tables, step-by-step instructions, commands, search results or long lists), speak only a short summary of one or two sentences, "
 "then write a new line containing exactly [[SCREEN]] followed by the full on-screen content in Markdown, starting with a '# ' title line. "
 "Use fenced code blocks with the language name for code. Never read code aloud, not even a single function name with brackets. "
 "Example of the format: Here's the simplest way, using the tabulate library. I've put it on screen.\n[[SCREEN]]\n# Python table\n```python\nfrom tabulate import tabulate\nprint(tabulate(rows, headers=['Name', 'Age']))\n```\n"
 "Only write [[SCREEN]] when there is something to show. "
 "The spoken part must contain no Markdown, code or symbols. Never include role labels, stage directions or hidden reasoning.")

SCREEN_MARK='[[SCREEN]]'
_TABLE_ROW=re.compile(r'^[ \t]*\|.*\|[ \t]*$',re.M)

def split_reply(text):
    """Split the model's answer into (spoken, screen): the voice reads `spoken`; `screen` is Markdown for the display panel."""
    spoken,_,screen=text.strip().partition(SCREEN_MARK)
    spoken,screen=spoken.strip(),screen.strip()
    # Small models sometimes forget the marker: move code or tables out of the spoken part anyway.
    starts=[i for i in (spoken.find('```'),) if i>=0]
    row=_TABLE_ROW.search(spoken)
    if row:starts.append(row.start())
    if starts:
        cut=min(starts);screen=(spoken[cut:]+('\n\n'+screen if screen else '')).strip();spoken=spoken[:cut].strip()
    spoken=re.sub(r'[*`#]+','',spoken)
    spoken=re.sub(r'\s+',' ',spoken).strip()
    if screen and not spoken:spoken="I've put it on screen for you."
    return spoken[:1500],screen[:12000]

def system_prompt(store=None):
    """SYSTEM_PROMPT plus the PC's current local date and time and what Cortana remembers about the user."""
    from datetime import datetime
    now=datetime.now().astimezone()
    text=SYSTEM_PROMPT+f" The current local date and time is {now.strftime('%A')} {now.day} {now.strftime('%B %Y')}, {now.strftime('%H:%M')} ({now.tzname()}). When asked the time, say the exact time."
    if store:
        home=store.get('home_location','')
        if home:text+=f" The user's home location is {home}."
        facts=store.facts()[-40:]
        if facts:text+=" Things you remember about the user: "+'; '.join(f['text'] for f in facts)+'.'
    return text

_SENTENCE_END=re.compile(r'(?<=[.!?\u2026])["\'\u201d\u2019)\]]*\s+|\n+')
_ABBREV=re.compile(r'(?:\b(?:mr|mrs|ms|dr|st|vs|etc|e\.g|i\.e|approx|no)\.)$',re.I)

def speakable(text):
    """Strip symbols the voice would otherwise read out."""
    text=re.sub(r'\[([^\]]+)\]\([^)]+\)',r'\1',text)      # markdown links -> text
    text=re.sub(r'[*`#_>|]+',' ',text)
    text=re.sub(r'\s+',' ',text)
    return re.sub(r'\s+([,.!?;:])',r'\1',text).strip()

class SpokenStream:
    """Turns streamed model text into whole spoken sentences and collects anything meant for the display panel."""
    def __init__(self):
        self.buf='';self.screen=None;self.spoken=[]
    def _emit(self,text,final=False):
        out=[];start=0;pending=''
        for m in _SENTENCE_END.finditer(text):
            piece=text[start:m.end()]
            if m.group().strip()=='' and _ABBREV.search(text[start:m.start()].strip()):continue
            pending+=piece;start=m.end()
            if len(pending.strip())>=18 or '\n' in m.group():
                clean=speakable(pending)
                if clean:out.append(clean)
                pending=''
        rest=pending+text[start:]
        if final:
            clean=speakable(rest)
            if clean:out.append(clean)
            rest=''
        self.spoken+=out
        return out,rest
    def feed(self,piece):
        if self.screen is not None:
            self.screen+=piece;return []
        self.buf+=piece
        cuts=[i for i in (self.buf.find(SCREEN_MARK),self.buf.find('```')) if i>=0]
        row=_TABLE_ROW.search(self.buf)
        if row:cuts.append(row.start())
        if cuts:
            cut=min(cuts);before,after=self.buf[:cut],self.buf[cut:]
            if after.startswith(SCREEN_MARK):after=after[len(SCREEN_MARK):]
            out,_=self._emit(before,final=True)
            self.screen=after;self.buf='';return out
        hold=max([k for k in range(1,len(SCREEN_MARK)) if self.buf.endswith(SCREEN_MARK[:k])]+[len(self.buf)-len(self.buf.rstrip('`|')),0])
        text,tail=(self.buf[:-hold],self.buf[-hold:]) if hold else (self.buf,'')
        out,rest=self._emit(text)
        self.buf=rest+tail
        return out
    def finish(self):
        if self.screen is not None:return []
        out,_=self._emit(self.buf,final=True);self.buf='';return out

def request_json(url,data=None,timeout=10):
    req=urllib.request.Request(url,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json','User-Agent':'CortanaLocal/1.0'})
    with urllib.request.urlopen(req,timeout=timeout) as response:return json.load(response)

def download(url,target,report,expected=None):
    target=Path(target)
    if target.exists() and (not expected or hashlib.sha256(target.read_bytes()).hexdigest()==expected):return
    target.parent.mkdir(parents=True,exist_ok=True)
    part=target.with_suffix(target.suffix+'.part')
    req=urllib.request.Request(url,headers={'User-Agent':'CortanaLocal/1.0'})
    with urllib.request.urlopen(req,timeout=45) as response,part.open('wb') as f:
        total=int(response.headers.get('Content-Length',0));received=0;last=0
        while chunk:=response.read(1024*1024):
            f.write(chunk);received+=len(chunk)
            if time.monotonic()-last>1:
                report(f'Downloading {target.name}: {received//1048576}'+(f' / {total//1048576}' if total else '')+' MB');last=time.monotonic()
    if total and received!=total:raise RuntimeError('Download was interrupted: '+target.name)
    if expected and hashlib.sha256(part.read_bytes()).hexdigest()!=expected:
        part.unlink(missing_ok=True);raise RuntimeError('Download verification failed: '+target.name)
    part.replace(target)

def extract(archive,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            dest=(directory/member.filename).resolve()
            if not dest.is_relative_to(directory.resolve()):raise RuntimeError('Invalid archive path.')
        z.extractall(directory)

class Runtime:
    def __init__(self,report=lambda text:None):
        DATA.mkdir(parents=True,exist_ok=True)
        from store import Store
        self.store=Store(DATA/'cortana.db')
        self.report=report;self.phone_url=None;self.tunnel_host=None
        # Tailscale gives a stable phone address, so keep the pairing token between launches in that mode only.
        if self.store.get('phone_access','cloudflare')=='tailscale':
            self.token=self.store.get('phone_token') or secrets.token_urlsafe(32);self.store.set('phone_token',self.token)
        else:self.token=secrets.token_urlsafe(32)
        self.local_url=None;self.model=os.getenv('CORTANA_MODEL') or self.store.get('model',MODEL)
        self.ollama_url=os.getenv('CORTANA_OLLAMA_URL','http://127.0.0.1:11434').rstrip('/')
        self.ai_ready=False;self.stt_ready=False;self.status='Starting Cortana';self.error=None
        self.children=[];self.logs=[];self.closing=threading.Event();self.stt_lock=threading.Lock();self.ai_lock=threading.Lock();self.lifecycle_lock=threading.Lock()
        self.whisper=next((DATA/'whisper').rglob('whisper-cli.exe'),None) if (DATA/'whisper').exists() else None
        self.whisper_model=DATA/'ggml-base.en.bin'
        from voice import Voice
        self.voice=Voice(self)

    def update(self,text):self.status=text;self.report(text)
    def spawn(self,args,env=None,stdout=None,stderr=None):
        with self.lifecycle_lock:
            if self.closing.is_set():raise RuntimeError('Cortana is closing.')
            p=subprocess.Popen(args,env=env,stdout=stdout if stdout is not None else subprocess.DEVNULL,stderr=stderr if stderr is not None else subprocess.DEVNULL,creationflags=HIDDEN)
            self.children.append(p);return p

    def ensure_ai(self):
        self.update('Starting local Qwen assistant...')
        try:tags=request_json(self.ollama_url+'/api/tags',timeout=2)
        except Exception:
            exe=shutil.which('ollama')
            installed=Path(os.environ.get('LOCALAPPDATA',''))/'Programs/Ollama/ollama.exe'
            if not exe and installed.exists():exe=str(installed)
            if not exe:
                exe=DATA/'ollama/ollama.exe'
                if not exe.exists():
                    release=request_json('https://api.github.com/repos/ollama/ollama/releases/latest')
                    asset=next(a for a in release['assets'] if a['name']=='ollama-windows-amd64.zip')
                    checksum=asset.get('digest','').removeprefix('sha256:') or None
                    download(asset['browser_download_url'],DATA/'ollama-runtime.zip',self.update,checksum)
                    extract(DATA/'ollama-runtime.zip',DATA/'ollama')
            log=(DATA/'ollama.log').open('ab');self.logs.append(log)
            env=os.environ.copy();env['OLLAMA_HOST']=self.ollama_url.removeprefix('http://');env['OLLAMA_NUM_PARALLEL']='1';env['OLLAMA_MAX_LOADED_MODELS']='1';env['OLLAMA_CONTEXT_LENGTH']=str(CONTEXT);env['OLLAMA_NO_CLOUD']='1'
            self.spawn([str(exe),'serve'],env=env,stdout=log,stderr=log)
            for _ in range(90):
                if self.closing.wait(.5):return
                try:tags=request_json(self.ollama_url+'/api/tags',timeout=2);break
                except Exception:pass
            else:raise RuntimeError('Ollama did not start. See ollama.log in the app data folder.')
        installed=[m['name'] for m in tags.get('models',[])]
        if self.model not in installed and FAST_MODEL in installed and self.model!=FAST_MODEL:
            self.report(self.model+' is not installed; using '+FAST_MODEL+'. Install it with: ollama pull '+self.model)
            self.model=FAST_MODEL
        if self.model not in installed:
            self.update('Downloading '+self.model+' on first launch...')
            req=urllib.request.Request(self.ollama_url+'/api/pull',data=json.dumps({'model':self.model,'stream':True}).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=180) as response:
                last=0
                for line in response:
                    if self.closing.is_set():return
                    msg=json.loads(line)
                    if msg.get('error'):raise RuntimeError(msg['error'])
                    if time.monotonic()-last>1:
                        total=msg.get('total',0);progress=f" {int(msg.get('completed',0)/total*100)}%" if total else ''
                        self.update('Qwen: '+msg.get('status','Downloading')+progress);last=time.monotonic()
        self.update('Loading '+self.model+' into memory...')
        try:request_json(self.ollama_url+'/api/generate',{'model':self.model,'prompt':'','stream':False,'keep_alive':'15m','options':{'num_ctx':CONTEXT}},timeout=180)
        except Exception:
            if self.model==FAST_MODEL:raise
            self.update(self.model+' could not load; switching to '+FAST_MODEL+'...');self.model=FAST_MODEL
            request_json(self.ollama_url+'/api/generate',{'model':self.model,'prompt':'','stream':False,'keep_alive':'15m','options':{'num_ctx':CONTEXT}},timeout=180)
        self.ai_ready=True;self.update('Qwen is ready.')

    def ensure_stt(self):
        if not self.whisper:
            self.update('Preparing local microphone recognition...')
            release=request_json('https://api.github.com/repos/ggml-org/whisper.cpp/releases/tags/v1.8.2')
            asset=next(a for a in release['assets'] if a['name']=='whisper-bin-x64.zip')
            checksum=asset.get('digest','').removeprefix('sha256:') or None
            download(asset['browser_download_url'],DATA/'whisper-runtime.zip',self.update,checksum)
            extract(DATA/'whisper-runtime.zip',DATA/'whisper')
            self.whisper=next((DATA/'whisper').rglob('whisper-cli.exe'))
        download('https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin',self.whisper_model,self.update)
        self.stt_ready=True;self.update('Local microphone recognition is ready.')

    def start_tailscale(self):
        """Stable private phone address via Tailscale (needs Tailscale installed and signed in on the PC and phone)."""
        exe=shutil.which('tailscale') or next((p for p in (Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Tailscale/tailscale.exe',) if p.exists()),None)
        if not exe:raise RuntimeError('Tailscale is not installed on this PC.')
        st=json.loads(subprocess.run([str(exe),'status','--json'],capture_output=True,timeout=20,creationflags=HIDDEN).stdout or b'{}')
        host=(st.get('Self') or {}).get('DNSName','').rstrip('.')
        if st.get('BackendState')!='Running' or not host:raise RuntimeError('Tailscale is not signed in on this PC.')
        port=self.local_url.rsplit(':',1)[1]
        p=subprocess.run([str(exe),'serve','--bg',port],capture_output=True,timeout=30,creationflags=HIDDEN)
        if p.returncode:raise RuntimeError('tailscale serve failed: '+(p.stderr or p.stdout).decode('utf-8','replace')[:160])
        self.tunnel_host=host;self.phone_url=f'https://{host}/?pair='+self.token
        self.update('Ready. Phone link (Tailscale): https://'+host)

    def start_tunnel(self):
        if self.store.get('phone_access','cloudflare')=='tailscale':
            try:return self.start_tailscale()
            except Exception as e:self.report('Tailscale unavailable ('+str(e)[:120]+'); using Cloudflare instead.')
        self.update('Creating secure phone connection...')
        exe=DATA/'cloudflared.exe'
        if not exe.exists():
            release=request_json('https://api.github.com/repos/cloudflare/cloudflared/releases/tags/2026.10.7')
            asset=next(a for a in release['assets'] if a['name']=='cloudflared-windows-amd64.exe')
            checksum=asset.get('digest','').removeprefix('sha256:') or None
            download(asset['browser_download_url'],exe,self.update,checksum)
        p=self.spawn([str(exe),'tunnel','--url',self.local_url,'--no-autoupdate','--protocol','http2'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        found=threading.Event()
        def read():
            for line in iter(p.stdout.readline,b''):
                match=re.search(rb'https://[a-z0-9-]+\.trycloudflare\.com',line)
                if match and not self.phone_url:
                    base=match.group().decode();self.tunnel_host=base.split('://')[1];self.phone_url=base+'/?pair='+self.token;found.set()
            if not self.closing.is_set():
                self.phone_url=None;self.tunnel_host=None;self.update('Phone connection stopped. Restart Cortana to reconnect.')
        threading.Thread(target=read,daemon=True).start()
        deadline=time.monotonic()+65
        while not found.wait(.5):
            if self.closing.is_set():return
            if p.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Phone connection could not start. Check your internet connection; desktop use is still available.')
        self.update('Ready. Scan the QR code on your phone.')

    def installed_models(self):
        try:return sorted(m['name'] for m in request_json(self.ollama_url+'/api/tags',timeout=3).get('models',[]) if m['name'].startswith(('qwen','llama','gemma','mistral','phi')))
        except Exception:return [self.model]

    def preload(self):
        try:request_json(self.ollama_url+'/api/generate',{'model':self.model,'prompt':'','stream':False,'keep_alive':'15m','options':{'num_ctx':CONTEXT}},timeout=180);self.report('Model switched to '+self.model)
        except Exception as e:self.report('Could not load '+self.model+': '+str(e)[:100])

    def clean_messages(self,messages,budget=6000):   # ~1,500 tokens of history inside the 6,144 context
        clean=[];remaining=budget
        for m in reversed(messages[-16:]):
            if m.get('role') not in ('user','assistant') or not isinstance(m.get('content'),str):continue
            content=m['content'][:min(remaining,3000)];remaining-=len(content)
            if content:clean.append({'role':m['role'],'content':content})
            if remaining<=0:break
        if not clean or clean[0]['role']!='user':raise ValueError('A user message is required.')
        return list(reversed(clean))

    def ollama_stream(self,payload):
        req=urllib.request.Request(self.ollama_url+'/api/chat',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        try:response=urllib.request.urlopen(req,timeout=180)
        except urllib.error.HTTPError as e:
            raise RuntimeError(json.loads(e.read() or b'{}').get('error') or f'Ollama error {e.code}')
        with response:
            for line in response:
                if line.strip():
                    chunk=json.loads(line)
                    if chunk.get('error'):raise RuntimeError(chunk['error'])
                    yield chunk

    def chat_stream(self,messages):
        """Yield events as the reply is generated: sentence, tool, refresh, screen, done."""
        import tools
        if not self.ai_ready:raise RuntimeError(self.status if not self.error else self.error)
        clean=self.clean_messages(messages)
        convo=[{'role':'system','content':system_prompt(self.store)}]+clean
        use_tools=self.store.get('tools_enabled',True)
        stream=SpokenStream();raw='';fell_back=False
        for round_ in range(4):
            payload={'model':self.model,'messages':convo,'stream':True,'think':False,'keep_alive':'15m',
                     'options':{'num_ctx':CONTEXT,'num_predict':1200,'temperature':.45}}
            if use_tools and round_<3:payload['tools']=tools.TOOLS
            content='';calls=[]
            try:
                for chunk in self.ollama_stream(payload):
                    msg=chunk.get('message') or {}
                    calls+=msg.get('tool_calls') or []
                    piece=re.sub(r'</?think>','',msg.get('content') or '')
                    if piece:
                        content+=piece
                        for sentence in stream.feed(piece):yield {'type':'sentence','text':sentence}
            except RuntimeError as e:
                # The bigger model may not fit next to other GPU work: retry once with the fast model.
                if fell_back or content or raw or self.model==FAST_MODEL:raise
                self.report(f'{self.model} failed ({str(e)[:80]}); using {FAST_MODEL}.')
                self.model=FAST_MODEL;fell_back=True;continue
            raw+=content
            if not calls:break
            convo.append({'role':'assistant','content':content,'tool_calls':calls})
            for call in calls[:4]:
                fn=call.get('function') or {};name=fn.get('name','');args=fn.get('arguments') or {}
                if isinstance(args,str):
                    try:args=json.loads(args)
                    except ValueError:args={}
                yield {'type':'tool','name':name,'label':tools.TOOL_LABELS.get(name,'WORKING')}
                result,change=tools.run(name,args,self.store)
                if change:yield {'type':'refresh','what':change}
                convo.append({'role':'tool','content':json.dumps(result,ensure_ascii=False,default=str)[:2500],'tool_name':name})
        for sentence in stream.finish():yield {'type':'sentence','text':sentence}
        screen=(stream.screen or '').strip()
        if screen:yield {'type':'screen','markdown':screen[:12000]}
        if not stream.spoken:
            if not screen:raise RuntimeError('The model returned no spoken answer. Try again.')
            stream.spoken.append("I've put it on screen for you.");yield {'type':'sentence','text':stream.spoken[-1]}
        self.store.log_message('user',clean[-1]['content']);self.store.log_message('assistant',raw)
        yield {'type':'done','reply':' '.join(stream.spoken)[:3000],'raw':raw[:6000]}

    def chat(self,messages):
        """Non-streaming version of chat_stream, kept for older pages and tests."""
        result={'reply':'','screen':'','raw':''}
        for event in self.chat_stream(messages):
            if event['type']=='screen':result['screen']=event['markdown']
            if event['type']=='done':result.update(reply=event['reply'],raw=event['raw'])
        return result

    def transcribe(self,wav):
        import tempfile,wave,io
        if not self.stt_ready:raise RuntimeError('Microphone recognition is still starting. You can type while it loads.')
        try:
            with wave.open(io.BytesIO(wav)) as f:
                if f.getnchannels()!=1 or f.getsampwidth()!=2 or f.getframerate()!=16000 or f.getnframes()>16000*31:raise ValueError('Use a mono 16 kHz recording under 30 seconds.')
        except wave.Error:raise ValueError('Invalid voice recording.')
        with self.stt_lock,tempfile.TemporaryDirectory(dir=DATA) as tmp:
            path=Path(tmp)/'speech.wav';path.write_bytes(wav);output=Path(tmp)/'words'
            p=subprocess.run([str(self.whisper),'-m',str(self.whisper_model),'-f',str(path),'-otxt','-of',str(output),'-t','4','-l','en','-nt','-ng'],capture_output=True,timeout=90,creationflags=HIDDEN)
            textfile=output.with_suffix('.txt')
            if p.returncode or not textfile.exists():raise RuntimeError('Could not transcribe that recording. Please try again.')
            text=textfile.read_text(encoding='utf-8-sig').strip()
            text=re.sub(r'\[[^\]]*\]|\([^)]*\)','',text).strip()
            if not text:raise RuntimeError('No speech detected. Try again when ready.')
            return text

    def close(self):
        with self.lifecycle_lock:self.closing.set();children=list(self.children)
        for p in reversed(children):
            if p.poll() is None:
                p.terminate()
                try:p.wait(timeout=5)
                except subprocess.TimeoutExpired:p.kill()
        for log in self.logs:log.close()

def qr_matrix(text):
    import qrcode
    qr=qrcode.QRCode(border=4,error_correction=qrcode.constants.ERROR_CORRECT_M);qr.add_data(text);qr.make(fit=True);return qr.get_matrix()

def qr_svg(text):
    matrix=qr_matrix(text);n=len(matrix)
    path=''.join(f'M{x} {y}h1v1h-1z' for y,row in enumerate(matrix) for x,on in enumerate(row) if on)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" shape-rendering="crispEdges"><rect width="{n}" height="{n}" fill="white"/><path d="{path}" fill="#041228"/></svg>'.encode()
