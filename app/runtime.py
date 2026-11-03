"""Cortana's local service lifecycle, model selection and phone pairing."""
from pathlib import Path
import os, sys, json, shutil, subprocess, urllib.request, urllib.error, zipfile, threading, time, secrets, re, hashlib, socket, tarfile

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
 "You can work with the user's PC: read documents they added (search_documents, summarise_document), find files by name and open or read them, look at their screen only when they ask about it, read their clipboard when they mention something they copied, and add calendar events. Never say you cannot see their screen, files or clipboard: use the tool. Never make up weather, search results, file names or what a document says: always call the tool first. "
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

# Weather questions are answered from real data fetched before the model runs: qwen3.5:4b invented a forecast in 2 of 4
# runs even with a hint (DECISIONS D-027), and a wrong forecast is worse than none.
_WEATHER=re.compile(r"\b(weather|forecast|temperature|rain(ing|y)?|snow(ing)?|sunny|umbrella|degrees outside|how (hot|cold|warm) is it)\b",re.I)
_PLACE=re.compile(r"\b(?:in|for|at|near)\s+((?:[a-z][\w'.-]*)(?:\s+(?!today|tomorrow|tonight|this|next|on|at|right|now|later|morning|afternoon|evening|weekend|please)[a-z][\w'.-]*){0,3})",re.I)
_NOT_PLACE={'the','a','my','general','celsius','fahrenheit','degrees','it','there','here','case','time','an','hour','minutes','days','week'}
_TIMER_UNITS={'second':1/60,'sec':1/60,'minute':1,'min':1,'hour':60,'hr':60}
_TIMER_AMOUNT=re.compile(r"\b(\d+(?:\.\d+)?|an?|half an?)\s*-?\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b",re.I)
_TIMER_LABEL=re.compile(r"\bfor\s+(?:the\s+|my\s+)?(?!\d|an?\s|half\b)([a-z][a-z' -]{1,30}?)\s*[.!?]*$",re.I)
def timer_request(text):
    """{'minutes', 'label'} when the message plainly asks for a new timer with a length ("set a 10 minute timer for the
    pasta", "timer for 90 seconds"), else None. Questions about, or changes to, existing timers are left to the model."""
    text=(text or '').strip()
    if not re.search(r"\btimer\b",text,re.I) or re.search(r"\b(cancel|stop|delete|remove|how long|left|remaining|check|pause|snooze|extend|add)\b",text,re.I):return None
    total=0.0
    for amount,unit in _TIMER_AMOUNT.findall(text):
        a=amount.lower();n=.5 if a.startswith('half') else 1.0 if a in ('a','an') else float(a)
        total+=n*_TIMER_UNITS[re.sub(r's$','',unit.lower())]
    if not 0<total<=24*60:return None
    m=_TIMER_LABEL.search(text);label=(m.group(1).strip() if m else '')
    if re.search(r"\b(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b",label,re.I):label=''
    return {'minutes':round(total,4),'label':label}

_REMIND=re.compile(r"\bremind me\b",re.I)
_IN=re.compile(r"\bin\s+(\d+(?:\.\d+)?|an?|half an?)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b",re.I)
_AT=re.compile(r"\b(?:at\s+)?(?:(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)|([01]?\d|2[0-3])[:.](\d{2})(?!\s*(?:am|pm))|(noon|midday|midnight))\b",re.I)
def reminder_request(text):
    """{'text', 'in_minutes'|'at'} when the message plainly asks for a reminder with a clear time ("remind me to call mum at
    6pm", "remind me in 20 minutes to check the oven", "remind me at 18:30 tomorrow to ..."), else None. "at 6" (am or pm?),
    weekdays and dates are left to the model."""
    text=(text or '').strip()
    if not _REMIND.search(text) or re.search(r"\b(cancel|delete|remove|what|when|which|list|did|change|move)\b",text,re.I):return None
    rest=text[_REMIND.search(text).end():];found={}
    m=_IN.search(rest)
    if m:
        a=m.group(1).lower();n=.5 if a.startswith('half') else 1.0 if a in ('a','an') else float(a)
        found['in_minutes']=round(n*_TIMER_UNITS[re.sub(r's$','',m.group(2).lower())],4)
    else:
        m=_AT.search(rest)
        if not m:return None
        if m.group(6):hour,minute={'midnight':(0,0)}.get(m.group(6).lower(),(12,0))
        elif m.group(3):
            hour,minute=int(m.group(1)),int(m.group(2) or 0)
            if not 1<=hour<=12 or minute>59:return None
            hour=hour%12+(12 if m.group(3).lower().startswith('p') else 0)
        else:hour,minute=int(m.group(4)),int(m.group(5))
        if minute>59:return None
        if re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|next|on the|\d{1,2}(st|nd|rd|th))\b",rest,re.I):return None
        if re.search(r"\btomorrow\b",rest,re.I):
            from datetime import datetime,timedelta
            found['at']=(datetime.now()+timedelta(days=1)).strftime('%Y-%m-%d ')+f'{hour:02d}:{minute:02d}'
        else:found['at']=f'{hour:02d}:{minute:02d}'
    task=(rest[:m.start()]+' '+rest[m.end():])
    task=re.sub(r"\b(tomorrow|today|tonight|please|thanks?)\b",' ',task,flags=re.I)
    task=re.sub(r"^\W*(to|that|about)\s+",'',' '.join(task.split()),flags=re.I).strip(' ,.!?')
    task=re.sub(r"\s+(to|at|in|and)$",'',task,flags=re.I)
    if len(task)<2 or 'in_minutes' in found and not 0<found['in_minutes']<=7*24*60:return None
    return {'text':task,**found}

# The user asked her to *do* something that has a tool. If a turn ends without any tool call, she only said it (D-036).
_ACTION_ASK=re.compile(r"\b(remind me|remember (that|my|i|to|this)|add .{1,60} to (my |the )?(list|to-?do|objectives|calendar)|put .{1,60} on my (list|to-?do|calendar)|set (a |an )?(timer|reminder|alarm)|book .{1,40} (on|at|for))\b",re.I)
# With full access on, any instruction to act on the PC needs a tool too ("open Notepad", "play something on Spotify").
_PC_ASK=re.compile(r"\b(open|launch|start|close|quit|play|pause|install|uninstall|download|type|click|press|turn (on|off)|switch (on|off)|"
                   r"enable|disable|change|set up|move|rename|delete|copy|run|search for|go to|navigate|mute|unmute|restart|shut ?down)\b",re.I)
def wants_action(text,full=False):
    """A request to do something with a tool, not a question about it ("do you remember my dog's name?").
    full=True also counts instructions to act on the PC, which only full access can carry out."""
    text=text or ''
    if re.match(r"\s*(do|does|did|what|when|where|who|whom|how|why|is|are|was|were|have|has)\b",text,re.I):return False
    return bool(_ACTION_ASK.search(text)) or (full and bool(_PC_ASK.search(text)))

_NUDGE=("(App check, not from the user: your last reply said you did it, but you called no tool, so nothing happened. "
        "Call the right tool now. After it runs, reply only 'Done.')")

def weather_question(text):
    """None if not a weather question, else the place named in it ('' = home town)."""
    text=text or ''
    if not _WEATHER.search(text):return None
    if re.search(r'\b(rainbow|brainstorm|weather(ed|ing) the)\b',text,re.I):return None
    m=_PLACE.search(text)
    place=m.group(1).strip(" ?.!,'") if m else ''
    return '' if place.lower() in _NOT_PLACE or place.split(' ')[0].lower() in _NOT_PLACE else place

FULL_ON=(" Full access is ON (the user switched it on): you can control this PC. Use run_command for anything a PowerShell "
         "command can do (install, settings, files, apps) and computer_task to use the mouse and keyboard in any app or site "
         "(e.g. play a song in Spotify). The user approves each one on screen first, so call the tool; never claim it is done before it runs.")
FULL_OFF=(" Full access is OFF. If the user wants you to control the PC beyond your tools (click around, run commands, install "
          "things), tell them they can switch on Full access in Systems on the PC.")
FULL_PHONE=" Full access (running commands, using the mouse and keyboard) only works when the user talks to you on the PC itself, not on the phone."
def system_prompt(store=None,query=None,full=None):
    """SYSTEM_PROMPT plus the PC's current local date and time and what Cortana remembers about the user."""
    from datetime import datetime
    now=datetime.now().astimezone()
    text=SYSTEM_PROMPT+f" The current local date and time is {now.strftime('%A')} {now.day} {now.strftime('%B %Y')}, {now.strftime('%H:%M')} ({now.tzname()}). When asked the time, say the exact time."
    if store:
        home=store.get('home_location','')
        if home:text+=f" The user's home location is {home}."
        facts=store.relevant_facts(query) if query is not None else store.facts()[-40:]
        if facts:text+=" Things you remember about the user: "+'; '.join(f['text'] for f in facts)+'.'
        docs=store.documents()[:8]
        if docs:text+=" Documents the user added, newest first (\"this\" or \"it\" means the first): "+'; '.join(d['name'][:60] for d in docs)+'.'
    if full is not None:   # True: on and asked on the PC; False: off; 'phone': on, but asked from the phone (D-040)
        text+=FULL_ON if full is True else FULL_PHONE if full=='phone' else FULL_OFF
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
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                if not (directory/member.filename).resolve().is_relative_to(directory.resolve()):raise RuntimeError('Invalid archive path.')
            z.extractall(directory)
    else:
        with tarfile.open(archive) as t:
            for member in t.getmembers():
                if not (directory/member.name).resolve().is_relative_to(directory.resolve()) or not (member.isfile() or member.isdir()):raise RuntimeError('Invalid archive path.')
            t.extractall(directory,filter='data')

_DEEP=re.compile(r"\b(think (it )?(hard|harder|carefully|deeply|it through|this through|step by step)|take your time|deep think(ing)?|reason (it|this) (out|through))\b",re.I)
def wants_deep_thought(text):
    """The user asked her to reason first ("think carefully about...", "take your time")."""
    return bool(_DEEP.search(text or ''))

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
        from companion import Jobs
        from neural import Neural
        from lips import Lips
        self.jobs=Jobs();self.neural=Neural(self.update);self.lips=Lips()
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
            env=os.environ.copy();env['OLLAMA_HOST']=self.ollama_url.removeprefix('http://');env['OLLAMA_NUM_PARALLEL']='1';env['OLLAMA_MAX_LOADED_MODELS']='1';env['OLLAMA_CONTEXT_LENGTH']=str(self.context());env['OLLAMA_NO_CLOUD']='1'
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
        try:request_json(self.ollama_url+'/api/generate',{'model':self.model,'prompt':'','stream':False,'keep_alive':'15m','options':{'num_ctx':self.context()}},timeout=180)
        except Exception:
            if self.model==FAST_MODEL:raise
            self.update(self.model+' could not load; switching to '+FAST_MODEL+'...');self.model=FAST_MODEL
            request_json(self.ollama_url+'/api/generate',{'model':self.model,'prompt':'','stream':False,'keep_alive':'15m','options':{'num_ctx':self.context()}},timeout=180)
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
        try:request_json(self.ollama_url+'/api/generate',{'model':self.model,'prompt':'','stream':False,'keep_alive':'15m','options':{'num_ctx':self.context()}},timeout=180);self.report('Model switched to '+self.model)
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

    def context(self):
        """Context window for the current model: 6,144 (standard) or, in auto, the largest that fits on the graphics card."""
        import hardware
        if self.store.get('context_mode','auto')!='auto':return CONTEXT
        try:self.hw=self.hw or hardware.detect()
        except Exception:return CONTEXT
        return hardware.context_for(next((m for m in hardware.CATALOG if m['tag']==self.model),None),self.hw)

    def history_budget(self,ctx):
        """6,000 characters at 6,144 tokens; about half of any extra context goes to older messages (~3.5 characters/token)."""
        return 6000+max(0,ctx-CONTEXT)*7//4

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
                       'options':{'num_ctx':self.context(),'num_predict':int(max_tokens),'temperature':.2}},timeout=180)
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

    NOTIFY_TRIES=3   # after this many failed Windows balloons, stop trying (the in-app alert still fires)

    def notification_tick(self,now=None,wait=False):
        """Show due reminders as Windows balloons. Each balloon runs in its own thread (it stays up ~9 s), so the loop
        never blocks; a failed balloon is retried after 1, then 2 minutes, then given up instead of every 2 seconds."""
        if not self.store.get('native_notifications',True):return
        now=time.monotonic() if now is None else now
        if not hasattr(self,'notify_state'):self.notify_state={}   # (id, due) -> {'busy','tries','next'}
        threads=[]
        for item in self.store.pending_notifications():
            if self.closing.is_set():break
            key=(item['id'],item['due']);entry=self.notify_state.setdefault(key,{'busy':False,'tries':0,'next':0})
            if entry['busy'] or now<entry['next']:continue
            entry['busy']=True
            t=threading.Thread(target=self._notify_one,args=(item,key,entry,now),daemon=True);t.start();threads.append(t)
        if wait:
            for t in threads:t.join()

    def _notify_one(self,item,key,entry,now):
        from companion import notify
        try:shown=notify(item['text'],'Cortana reminder' if item['kind'] in ('timer','reminder') else 'Cortana')
        except Exception:shown=False
        entry['tries']+=1;entry['busy']=False
        if shown or entry['tries']>=self.NOTIFY_TRIES:
            self.store.mark_notified(item['id'],item['due']);self.notify_state.pop(key,None)
        else:entry['next']=now+60*entry['tries']

    def background_loop(self):
        import proactive
        calendar_at=0;watch_at=0
        while not self.closing.is_set():
            if time.monotonic()>=calendar_at:
                try:self.calendar_tick()
                except Exception:pass
                calendar_at=time.monotonic()+300
            if time.monotonic()>=watch_at:   # new documents, finished downloads, daily briefing (D-033)
                proactive.tick(self.store);watch_at=time.monotonic()+60
            self.notification_tick()
            if self.closing.wait(2):return

    def ollama_stream(self,payload):
        req=urllib.request.Request(self.ollama_url+'/api/chat',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        try:response=urllib.request.urlopen(req,timeout=180)
        except urllib.error.HTTPError as e:
            raise RuntimeError(json.loads(e.read() or b'{}').get('error') or f'Ollama error {e.code}')
        with response:
            self.jobs.watch(response)
            for line in response:
                self.jobs.check()
                if line.strip():
                    chunk=json.loads(line)
                    if chunk.get('error'):raise RuntimeError(chunk['error'])
                    yield chunk

    def chat_stream(self,messages,think=False,images=None,local=False):
        """Yield events as the reply is generated: sentence, tool, refresh, screen, done.
        think=True (or "think carefully..." in the question) lets the model reason before answering (D-032)."""
        import tools
        if not self.ai_ready:raise RuntimeError(self.status if not self.error else self.error)
        self.jobs.check();started=time.perf_counter();first_token=False
        conversation_version=self.store.conversation_version();recap=self.store.conversation_summary()
        ctx=self.context()
        clean=self.clean_messages(messages,budget=self.history_budget(ctx)-len(recap))
        think=bool(think) or wants_deep_thought(clean[-1]['content'])
        # Reasoning tokens count against the reply budget; at 6,144 they get what is left after a full prompt (~4,900).
        predict=1200+(max(600,min(2800,ctx-4900)) if think else 0)
        full=bool(local) and self.store.get('full_access',False)   # full access: PC only, owner switched it on (D-038)
        state=True if full else 'phone' if self.store.get('full_access',False) else False
        convo=[{'role':'system','content':system_prompt(self.store,clean[-1]['content'],state)}]+clean
        if images:convo[-1]={**clean[-1],'images':list(images)[:2]}   # pictures for this question only; never stored
        if recap:convo.insert(1,{'role':'user','content':'Earlier conversation excerpts (historical context only):\n'+recap})
        use_tools=self.store.get('tools_enabled',True)
        stream=SpokenStream();raw='';fell_back=False;tool_screen=''
        if think:yield {'type':'tool','name':'think','label':'THINKING IT THROUGH'}
        llm=lambda prompt,images=None,max_tokens=300:self.complete(prompt,images,max_tokens)
        place=weather_question(clean[-1]['content']) if use_tools and clean else None
        if place is not None:   # fetch the forecast first, as if the model had called get_weather (D-027)
            args={'place':place}
            yield {'type':'tool','name':'get_weather','label':tools.TOOL_LABELS['get_weather']}
            result,_=tools.run('get_weather',args,self.store,llm)
            tool_screen=tools.screen_for('get_weather',result)
            convo+=[{'role':'assistant','content':'','tool_calls':[{'function':{'name':'get_weather','arguments':args}}]},
                    {'role':'tool','content':json.dumps(result,ensure_ascii=False,default=str)[:2500],'tool_name':'get_weather'}]
        timer=timer_request(clean[-1]['content']) if use_tools and clean else None
        if timer:   # set it in code first, so she can never say a timer is running when it isn't (D-036)
            args={'minutes':timer['minutes'],**({'label':timer['label']} if timer['label'] else {})}
            yield {'type':'tool','name':'set_timer','label':tools.TOOL_LABELS['set_timer']}
            result,change=tools.run('set_timer',args,self.store,llm)
            if change:yield {'type':'refresh','what':change}
            convo+=[{'role':'assistant','content':'','tool_calls':[{'function':{'name':'set_timer','arguments':args}}]},
                    {'role':'tool','content':json.dumps(result,ensure_ascii=False,default=str)[:2500],'tool_name':'set_timer'}]
        reminder=reminder_request(clean[-1]['content']) if use_tools and clean and not timer else None
        if reminder:   # same for a reminder with a clear time (D-036)
            yield {'type':'tool','name':'set_reminder','label':tools.TOOL_LABELS['set_reminder']}
            result,change=tools.run('set_reminder',reminder,self.store,llm)
            if change:yield {'type':'refresh','what':change}
            convo+=[{'role':'assistant','content':'','tool_calls':[{'function':{'name':'set_reminder','arguments':reminder}}]},
                    {'role':'tool','content':json.dumps(result,ensure_ascii=False,default=str)[:2500],'tool_name':'set_reminder'}]
        offered=tools.tools_for(clean[-1]['content'],ctx,full);rounds=6 if think else 4   # deep thinking may chain more steps
        done_in_code={n for n,v in (('set_timer',timer),('set_reminder',reminder)) if v}
        offered=[t for t in offered if t['function']['name'] not in done_in_code]   # never a second, duplicate timer/reminder
        any_calls=bool(done_in_code) or place is not None;nudged=False
        for round_ in range(rounds+1):   # +1: room for one "you didn't actually do it" retry
            if round_==rounds and not nudged:break
            self.jobs.check()
            payload={'model':self.model,'messages':convo,'stream':True,'think':think,'keep_alive':'15m',
                     'options':{'num_ctx':ctx,'num_predict':predict,'temperature':.45}}
            if use_tools and (round_<rounds-1 or nudged):payload['tools']=offered
            content='';calls=[]
            try:
                for chunk in self.ollama_stream(payload):
                    self.jobs.check()
                    msg=chunk.get('message') or {}
                    calls+=msg.get('tool_calls') or []
                    piece=re.sub(r'</?think>','',msg.get('content') or '')
                    if piece:
                        if not first_token:self.jobs.measure('first_token_ms',started);first_token=True
                        content+=piece
                        for sentence in stream.feed(piece):yield {'type':'sentence','text':sentence}
            except RuntimeError as e:
                self.jobs.check()  # cancellation must never switch the active model
                # The bigger model may not fit next to other GPU work: retry once with the fast model.
                if fell_back or content or raw or self.model==FAST_MODEL:raise
                self.report(f'{self.model} failed ({str(e)[:80]}); using {FAST_MODEL}.')
                self.model=FAST_MODEL;fell_back=True;continue
            raw+=content
            if not calls:
                if use_tools and not any_calls and not nudged and wants_action(clean[-1]['content'],full):
                    nudged=True;convo+=[{'role':'assistant','content':content},{'role':'user','content':_NUDGE}];continue
                break
            any_calls=True
            convo.append({'role':'assistant','content':content,'tool_calls':calls})
            for call in calls[:4]:
                fn=call.get('function') or {};name=fn.get('name','');args=fn.get('arguments') or {}
                if isinstance(args,str):
                    try:args=json.loads(args)
                    except ValueError:args={}
                yield {'type':'tool','name':name,'label':tools.TOOL_LABELS.get(name,'WORKING')}
                self.jobs.check()
                if name in tools.CONFIRM:   # ask before doing (D-035): describe it, run only after the user approves
                    plan=tools.preview(name,args,self.store)
                    if 'error' in plan:result,change=plan,None
                    else:
                        pid=self.hold(name,args,local)
                        yield {'type':'confirm','id':pid,'name':name,'label':tools.TOOL_LABELS.get(name,'WORKING'),'summary':plan['summary'],'detail':plan.get('detail','')}
                        result,change={'status':'waiting for the user to approve','shown_on_screen':plan['summary'],
                                       'note':'Tell the user in one sentence what you prepared and to say yes or tap Approve. It has NOT been done yet.'},None
                else:result,change=tools.run(name,args,self.store,llm)
                if change:yield {'type':'refresh','what':change}
                tool_screen=tools.screen_for(name,result) or tool_screen   # weather, files found, new events: a card every time (D-021)
                convo.append({'role':'tool','content':json.dumps(result,ensure_ascii=False,default=str)[:tools.RESULT_LIMIT.get(name,2500)],'tool_name':name})
        for sentence in stream.finish():yield {'type':'sentence','text':sentence}
        screen=tool_screen or (stream.screen or '').strip()   # the tool's card wins, so weather looks the same every time
        if screen:yield {'type':'screen','markdown':screen[:12000]}
        if not stream.spoken:
            if not screen:raise RuntimeError('The model returned no spoken answer. Try again.')
            stream.spoken.append("I've put it on screen for you.");yield {'type':'sentence','text':stream.spoken[-1]}
        self.jobs.check();self.jobs.measure('reply_ms',started)
        self.store.log_exchange(clean[-1]['content'],raw,conversation_version)
        yield {'type':'done','reply':' '.join(stream.spoken)[:3000],'raw':raw[:6000]}

    control_visible=False   # the launcher draws the blue screen border while this is True

    def show_control(self,on):
        """Blue border round the screen (drawn by the launcher window) and a Cortana-blue cursor while she has control."""
        import control
        self.control_visible=bool(on)
        if os.name!='nt':return
        try:control.set_blue_cursor() if on else control.restore_cursor()
        except Exception:pass   # cosmetic: never let the cursor stop or break a task

    PENDING_SECONDS=600

    def hold(self,name,args,local=False):
        """Keep an action that needs approval; returns its one-time id."""
        if not hasattr(self,'pending'):self.pending={}
        now=time.monotonic()
        self.pending={k:v for k,v in self.pending.items() if now-v['at']<self.PENDING_SECONDS}
        while len(self.pending)>=20:self.pending.pop(next(iter(self.pending)))
        pid=secrets.token_urlsafe(12);self.pending[pid]={'name':name,'args':args,'at':now,'local':bool(local)};return pid

    def confirm(self,pid,approve,local=False):
        """Run (approve=True) or drop a held action, once. Returns {say, result?, refresh?}.
        Full-access actions are only approved on the PC itself, while full access is still switched on."""
        import tools
        entry=getattr(self,'pending',{}).get(str(pid))
        if entry and entry['name'] in tools.FULL and not (local and entry['local']):
            raise ValueError('Approve this on the PC itself.')
        entry=getattr(self,'pending',{}).pop(str(pid),None)
        if not entry or time.monotonic()-entry['at']>=self.PENDING_SECONDS:
            raise ValueError('That request has expired. Ask me again.')
        if not approve:return {'ok':True,'say':'Cancelled. Nothing was changed.'}
        if entry['name'] in tools.FULL and not self.store.get('full_access',False):
            raise ValueError('Full access was switched off.')
        llm=lambda prompt,images=None,max_tokens=300:self.complete(prompt,images,max_tokens)
        if entry['name']=='computer_task':   # runs here so Stop (POST /api/cancel {request_id:"task_<id>"}) can end it
            import control
            with self.jobs.scope('task_'+re.sub(r'[^A-Za-z0-9_-]','',str(pid))):
                try:result=control.computer_task(entry['args'].get('goal',''),llm,self.jobs.check,show=self.show_control)
                except (RuntimeError,ValueError) as e:result={'error':str(e)[:200]}
            return {'ok':'error' not in result and bool(result.get('done')),'say':tools.done_text('computer_task',result),'result':result,'refresh':None}
        result,change=tools.run(entry['name'],entry['args'],self.store,llm,approved=True)
        return {'ok':'error' not in result,'say':tools.done_text(entry['name'],result),'result':result,'refresh':change}

    def chat(self,messages):
        """Non-streaming version of chat_stream, kept for older pages and tests."""
        result={'reply':'','screen':'','raw':''}
        for event in self.chat_stream(messages):
            if event['type']=='screen':result['screen']=event['markdown']
            if event['type']=='done':result.update(reply=event['reply'],raw=event['raw'])
        return result

    def transcribe(self,wav,prompt=None):
        import tempfile,wave,io
        started=time.perf_counter()
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
            self.jobs.measure('transcription_ms',started)
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
