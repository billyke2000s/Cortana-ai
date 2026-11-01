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
 "You can work with the user's PC: read documents they added (search_documents, summarise_document), find files by name and open or read them, look at their screen only when they ask about it, read their clipboard when they mention something they copied, and add calendar events. Never say you cannot see their screen, files or clipboard: use the tool. "
 "File search results and new calendar events are put on screen automatically, like weather. "
 "Weather results are put on screen automatically: answer weather questions in one or two spoken sentences and never write [[SCREEN]] for them. "
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
        docs=store.documents()[:8]
        if docs:text+=" Documents the user added, newest first (\"this\" or \"it\" means the first): "+'; '.join(d['name'][:60] for d in docs)+'.'
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

# ---- "Hey Cortana": Whisper spells the name many ways ("Katana", "Courtana", "Cortona"...), so match it fuzzily.
WAKE_PROMPT='Cortana is my assistant.'   # biases Whisper towards the name; a transcript equal to it is ignored (hallucination)
WAKE_GREETINGS={'hey','hi','ok','okay','yo','a','hay','hei','hej','eh'}
WAKE_WEAK={'katana','quartana','kortina','cortina','catana','gotana','cortna','cotanna'}   # only count after a greeting
def wake_match(text):
    """Return the words after the wake name, or None if the name isn't near the start."""
    from difflib import SequenceMatcher
    norm=lambda t:re.sub(r'[^a-z ]','',t.lower()).strip()
    if not text or norm(text)==norm(WAKE_PROMPT):return None
    words=[(m.group().lower(),m.end()) for m in re.finditer(r"[A-Za-z']+",text)][:6]
    sim=lambda w:SequenceMatcher(None,w,'cortana').ratio()
    for i,(w,end) in enumerate(words[:4]):
        after_greeting=i>0 and words[i-1][0] in WAKE_GREETINGS
        joined=(w+words[i+1][0],words[i+1][1]) if i+1<len(words) else None
        hit=None
        if 5<=len(w)<=9 and (sim(w)>=0.78 or (after_greeting and (w in WAKE_WEAK or sim(w)>=0.75))):hit=end
        elif joined and 6<=len(joined[0])<=9 and sim(joined[0])>=0.85:hit=joined[1]   # "cor tana", "court ana"
        if hit is not None:
            if any(x[0] not in WAKE_GREETINGS|{'um','uh','er','erm','so','oh','well'} for x in words[:i]):return None   # name must open the phrase
            return text[hit:].lstrip(' ,.!?;:-').strip()
    return None

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
        self.local_url=None;self.model=os.getenv('CORTANA_MODEL') or self.store.get('model') or MODEL
        self.model_chosen=bool(os.getenv('CORTANA_MODEL') or self.store.get('model'))   # False: pick the recommended model for this PC
        # First launch with the window open: wait for the user to pick a model on the page (launcher sets ask_model).
        self.ask_model=False;self.awaiting_choice=False;self.model_picked=threading.Event()
        self.hw=None;self.tag_exists={};self.pull={'active':False,'tag':None,'status':'','pct':0,'error':None}
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
        if not self.model_chosen and self.ask_model:
            import hardware
            self.hw=self.hw or hardware.detect()
            rows=hardware.recommend(self.hw,installed,self.available_tags(installed))
            best=next((r['label'] for r in rows if r['tag']==hardware.recommended_tag(rows,MODEL)),'')
            self.awaiting_choice=True
            self.update('Choose your AI model on the Cortana page.'+(f' Recommended for this PC: {best}.' if best else ''))
            try:
                while not self.model_picked.wait(.5):
                    if self.closing.is_set():return
            finally:self.awaiting_choice=False
            installed=[m['name'] for m in request_json(self.ollama_url+'/api/tags',timeout=5).get('models',[])]
        if not self.model_chosen:
            import hardware
            self.hw=self.hw or hardware.detect()
            rows=hardware.recommend(self.hw,installed,self.available_tags(installed))
            best=hardware.recommended_tag(rows,MODEL)
            usable=[r for r in rows if r['installed'] and r['selectable']]
            if best in installed or not usable:self.model=best        # nothing usable installed yet: download the recommended one
            else:
                self.model=max(usable,key=lambda r:r['quality'])['tag']  # don't force a big download: use the best one already here
                self.report(f'{best} is recommended for this PC; download it in Systems. Using {self.model} for now.')
        if self.model not in installed and FAST_MODEL in installed and self.model!=FAST_MODEL:
            self.report(self.model+' is not installed; using '+FAST_MODEL+'. Install it with: ollama pull '+self.model)
            self.model=FAST_MODEL
        if self.model not in installed:
            self.update('Downloading '+self.model+' on first launch...')
            self.pull_model(self.model,lambda status,pct:self.update(f'AI model: {status}'+(f' {pct}%' if pct else '')))
            if self.closing.is_set():return
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

    def pull_model(self,tag,progress):
        """Download a model through Ollama, reporting (status, percent)."""
        req=urllib.request.Request(self.ollama_url+'/api/pull',data=json.dumps({'model':tag,'stream':True}).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=180) as response:
            last=0
            for line in response:
                if self.closing.is_set():return
                msg=json.loads(line)
                if msg.get('error'):raise RuntimeError(msg['error'])
                if time.monotonic()-last>.5 or msg.get('status')=='success':
                    total=msg.get('total',0);progress(msg.get('status','downloading'),int(msg.get('completed',0)/total*100) if total else 0);last=time.monotonic()

    def available_tags(self,installed=()):
        """Catalog tags that exist in the Ollama library (checked once; installed ones always count)."""
        import hardware
        for m in hardware.CATALOG:
            tag=m['tag']
            if tag in installed:self.tag_exists[tag]=True
            if tag in self.tag_exists:continue
            name,_,version=tag.partition(':')
            try:
                req=urllib.request.Request(f'https://registry.ollama.ai/v2/library/{name}/manifests/{version}',method='HEAD',
                    headers={'Accept':'application/vnd.docker.distribution.manifest.v2+json','User-Agent':'CortanaLocal/1.0'})
                urllib.request.urlopen(req,timeout=6).close();self.tag_exists[tag]=True
            except urllib.error.HTTPError as e:
                if e.code==404:self.tag_exists[tag]=False
            except Exception:
                pass   # offline: decide again later; standard sizes are assumed to exist
        return {m['tag'] for m in hardware.CATALOG if self.tag_exists.get(m['tag'],not m['moe'])}

    def models_info(self):
        import hardware
        self.hw=self.hw or hardware.detect()
        try:installed=[m['name'] for m in request_json(self.ollama_url+'/api/tags',timeout=3).get('models',[])]
        except Exception:installed=[]
        rows=hardware.recommend(self.hw,installed,self.available_tags(installed))
        return {'hardware':self.hw,'models':rows,'current':None if self.awaiting_choice else self.model,   # nothing is in use until the first choice
               'recommended':hardware.recommended_tag(rows),
                'pull':dict(self.pull),'disk_free_gb':hardware.free_disk_gb(),'other_installed':[t for t in installed if t not in {r['tag'] for r in rows}]}

    def check_model(self,tag,need_installed=True):
        info=self.models_info();row=next((r for r in info['models'] if r['tag']==tag),None)
        if row is None:
            if tag in info['other_installed']:return info,None    # a model the user installed themselves: allowed
            raise ValueError('Unknown model.')
        if not row['selectable']:raise ValueError(row['label']+' is too big for this PC: '+row['note'])
        if need_installed and not row['installed']:raise ValueError(row['label']+' is not downloaded yet.')
        return info,row

    def use_model(self,tag):
        self.check_model(tag)
        self.store.set('model',tag);self.model=tag;self.model_chosen=True;self.model_picked.set()
        threading.Thread(target=self.preload,daemon=True).start()

    def start_pull(self,tag,use_after=True):
        if self.pull['active']:raise ValueError('A download is already running.')
        info,row=self.check_model(tag,need_installed=False)
        if row and row['installed']:raise ValueError(row['label']+' is already downloaded.')
        free=info['disk_free_gb']
        if row and free is not None and free<row['size_gb']*1.1+1:raise ValueError(f"Not enough disk space: {row['size_gb']:.0f} GB needed, {free:.0f} GB free.")
        self.pull={'active':True,'tag':tag,'status':'starting','pct':0,'error':None}
        def run():
            try:
                def progress(status,pct):
                    self.pull.update(status=status,pct=pct)
                    if self.awaiting_choice:self.update(f'Downloading {tag}: {status}'+(f' {pct}%' if pct else ''))
                self.pull_model(tag,progress)
                if use_after:self.use_model(tag)          # switch first, so nobody sees 'done' with the old model still active
                self.pull.update(active=False,status='done',pct=100)
            except Exception as e:
                self.pull.update(active=False,status='failed',error=str(e)[:200])
        threading.Thread(target=run,daemon=True).start()

    def clean_messages(self,messages,budget=6000):   # ~1,500 tokens of history inside the 6,144 context
        clean=[];remaining=budget
        for m in reversed(messages[-16:]):
            if m.get('role') not in ('user','assistant') or not isinstance(m.get('content'),str):continue
            content=m['content'][:min(remaining,3000)];remaining-=len(content)
            if content:clean.append({'role':m['role'],'content':content})
            if remaining<=0:break
        if not clean or clean[0]['role']!='user':raise ValueError('A user message is required.')
        return list(reversed(clean))

    def complete(self,prompt,images=None,max_tokens=300):
        """One short, non-streaming answer from the current model (document notes, screenshots). Images: base64 PNGs."""
        msg={'role':'user','content':prompt}
        if images:msg['images']=images
        r=request_json(self.ollama_url+'/api/chat',{'model':self.model,'messages':[msg],'stream':False,'think':False,'keep_alive':'15m',
                       'options':{'num_ctx':CONTEXT,'num_predict':int(max_tokens),'temperature':.2}},timeout=180)
        text=re.sub(r'<think>.*?</think>','',(r.get('message') or {}).get('content') or '',flags=re.S).strip()
        if not text:raise RuntimeError('The model gave no answer.')
        return text

    def calendar_tick(self,now=None):
        """Create a 10-minute-before reminder for each timed Google Calendar event coming up (once per event)."""
        import tools
        url=self.store.get('calendar_url','')
        if not url:return 0
        now=now or time.time();done=self.store.get('cal_reminded',[]);added=0
        for title,start in tools.ical_upcoming(url,12,now):
            key=f'{title}|{int(start)}'
            if key in done or start-now<60:continue
            self.store.add_item('reminder',f'{title} starts in 10 minutes',max(now,start-600));done.append(key);added+=1
        self.store.set('cal_reminded',done[-300:])
        return added

    def background_loop(self):
        while True:
            try:self.calendar_tick()
            except Exception:pass
            if self.closing.wait(300):return

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
        stream=SpokenStream();raw='';fell_back=False;tool_screen=''
        llm=lambda prompt,images=None,max_tokens=300:self.complete(prompt,images,max_tokens)
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
                result,change=tools.run(name,args,self.store,llm)
                if change:yield {'type':'refresh','what':change}
                tool_screen=tools.screen_for(name,result) or tool_screen   # weather, files found, new events: a card every time (D-021)
                convo.append({'role':'tool','content':json.dumps(result,ensure_ascii=False,default=str)[:tools.RESULT_LIMIT.get(name,2500)],'tool_name':name})
        for sentence in stream.finish():yield {'type':'sentence','text':sentence}
        screen=tool_screen or (stream.screen or '').strip()   # the tool's card wins, so weather looks the same every time
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

    def transcribe(self,wav,prompt=None):
        import tempfile,wave,io
        if not self.stt_ready:raise RuntimeError('Microphone recognition is still starting. You can type while it loads.')
        try:
            with wave.open(io.BytesIO(wav)) as f:
                if f.getnchannels()!=1 or f.getsampwidth()!=2 or f.getframerate()!=16000 or f.getnframes()>16000*31:raise ValueError('Use a mono 16 kHz recording under 30 seconds.')
        except wave.Error:raise ValueError('Invalid voice recording.')
        with self.stt_lock,tempfile.TemporaryDirectory(dir=DATA) as tmp:
            path=Path(tmp)/'speech.wav';path.write_bytes(wav);output=Path(tmp)/'words'
            p=subprocess.run([str(self.whisper),'-m',str(self.whisper_model),'-f',str(path),'-otxt','-of',str(output),'-t','4','-l','en','-nt','-ng']+(['--prompt',prompt] if prompt else []),capture_output=True,timeout=90,creationflags=HIDDEN)
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
