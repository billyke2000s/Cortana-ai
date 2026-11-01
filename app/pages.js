/* Cortana pages: Chat, Mission Briefing, Objectives, Memory and Systems, shown in the holographic display panel.
   All text from the server is escaped before it is put on the page. */
const D=window.CortanaDisplay,C=window.Cortana,esc=s=>D.esc(s??'');
const get=async path=>{const r=await fetch(path);const v=await r.json();if(!r.ok)throw Error(v.error||'Service unavailable.');return v;};
const post=(path,data)=>C.api(path,data);
const when=ts=>{const d=new Date(ts*1000),t=new Date(),tm=new Date(t);tm.setDate(t.getDate()+1);
 const day=d.toDateString()===t.toDateString()?'Today':d.toDateString()===tm.toDateString()?'Tomorrow':d.toLocaleDateString('en-GB',{weekday:'short',day:'numeric',month:'short'});
 return day+' '+d.toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'});};
const left=ts=>{const s=Math.max(0,Math.round(ts-Date.now()/1000));return s>=3600?`${Math.floor(s/3600)}h ${Math.floor(s%3600/60)}m`:`${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;};
const ICON={timer:'⏱',reminder:'⏰',task:'◇'};
let ticker=null;
function page(name,title,html,label){D.panel(title,html,label||'CORTANA // '+name.toUpperCase(),name);}
function failed(name,title,e){page(name,title,`<p class="pg-err">${esc(e.message)}</p>`);}

/* ---------------- Objectives ---------------- */
function itemRow(i){
 const due=i.due?(i.kind==='timer'&&!i.announced?`<span class="pg-due" data-timer="${i.due}">${left(i.due)}</span>`:`<span class="pg-due">${esc(when(i.due))}</span>`):'';
 const flag=i.announced&&!i.done?' pg-fired':'';
 return `<li class="pg-item${flag}"><span class="pg-ico">${ICON[i.kind]||''}</span><span class="pg-text">${esc(i.text)}${due}</span>
  ${i.due?`<button type="button" class="pg-btn" data-act="snooze" data-id="${i.id}" aria-label="Snooze ten minutes">+10m</button>`:''}
  <button type="button" class="pg-btn" data-act="complete" data-id="${i.id}" aria-label="Done">✓</button>
  <button type="button" class="pg-btn pg-del" data-act="delete" data-id="${i.id}" aria-label="Delete">✕</button></li>`;
}
async function objectives(){
 try{
  const {items,recent_alerts=[]}=await get('/api/objectives');
  const groups=[['timer','Timers'],['reminder','Reminders'],['task','To-do']].map(([k,t])=>{const list=items.filter(i=>i.kind===k);return list.length?`<h3>${t}</h3><ul class="pg-list">${list.map(itemRow).join('')}</ul>`:'';}).join('');
  page('tasks','Objectives',`
   <form class="pg-add" id="pgAdd">
    <select id="pgKind" aria-label="Type"><option value="task">To-do</option><option value="timer">Timer</option><option value="reminder">Reminder</option></select>
    <input id="pgText" placeholder="What is it?" maxlength="200" required aria-label="Text">
    <input id="pgMinutes" type="number" min="0.1" max="1440" step="any" value="5" aria-label="Minutes" hidden>
    <input id="pgAt" type="datetime-local" aria-label="When" hidden>
    <button type="submit" class="pg-primary">Add</button>
   </form>
   ${groups||'<p class="pg-muted">Nothing open. Ask Cortana to set a timer, a reminder or add something to your list.</p>'}${recent_alerts.length?'<h3>Recent timer alerts</h3><ul class="pg-list">'+recent_alerts.map(itemRow).join('')+'</ul>':''}`,'CORTANA // OBJECTIVES');
  const kind=document.getElementById('pgKind'),sync=()=>{document.getElementById('pgMinutes').hidden=kind.value!=='timer';document.getElementById('pgAt').hidden=kind.value!=='reminder';};
  kind.onchange=sync;sync();
  document.getElementById('pgAdd').onsubmit=async e=>{e.preventDefault();
   const data={action:'add',kind:kind.value,text:document.getElementById('pgText').value};
   if(kind.value==='timer')data.minutes=Number(document.getElementById('pgMinutes').value);
   if(kind.value==='reminder'){const v=document.getElementById('pgAt').value;if(!v)return;data.at=v.replace('T',' ');}
   try{await post('/api/objectives',data);objectives();}catch(err){alertIn(err.message);}};
  clearInterval(ticker);ticker=setInterval(()=>{if(D.page!=='tasks'){clearInterval(ticker);return;}
   document.querySelectorAll('.pg-due[data-timer]').forEach(el=>{el.textContent=left(Number(el.dataset.timer));});},1000);
 }catch(e){failed('tasks','Objectives',e);}
}

/* ---------------- Memory ---------------- */
async function memory(){
 try{
  const [{facts,messages,conflicts=[]},docs]=await Promise.all([get('/api/memory'),get('/api/documents')]);
  page('memory','Memory',`
   <h3>What I remember about you</h3>
   ${conflicts.length?'<p class="pg-muted">Some memories may conflict. Edit the matching facts to keep them current.</p>':''}
   ${facts.length?`<ul class="pg-list">${facts.map(f=>`<li class="pg-item"><input class="pg-text" data-fact="${f.id}" value="${esc(f.text)}" maxlength="300" aria-label="Memory"><button type="button" class="pg-btn" data-act="edit-fact" data-id="${f.id}">Save</button><button type="button" class="pg-btn pg-del" data-act="forget" data-id="${f.id}" aria-label="Forget">✕</button></li>`).join('')}</ul>`:'<p class="pg-muted">Nothing yet. Tell me things like “remember my dog is called Max”.</p>'}
   <form class="pg-add" id="pgFact"><input id="pgFactText" placeholder="Add something to remember" maxlength="300" required aria-label="Fact"><button type="submit" class="pg-primary">Remember</button></form>
   <h3>Documents I can read</h3>
   ${docs.documents.length?`<ul class="pg-list">${docs.documents.map(d=>`<li class="pg-item"><span class="pg-ico">📄</span><span class="pg-text">${esc(d.name)}<span class="pg-due">${d.pages?esc(d.pages)+(/\.pptx$/i.test(d.name)?' slides':' pages')+' · ':''}${d.chars<1000?esc(d.chars)+' characters':esc(Math.round(d.chars/1000))+'k characters'}</span></span><button type="button" class="pg-btn pg-del" data-act="doc-remove" data-id="${d.id}" aria-label="Remove">✕</button></li>`).join('')}</ul>`:'<p class="pg-muted">None yet. Add PDFs, Word, PowerPoint or text files, then ask “summarise this” or “quiz me on chapter 3”.</p>'}
   <button type="button" class="pg-btn pg-wide" data-act="attach">Add files…</button>
   ${docs.canAddFolder?`<form class="pg-add" id="pgFolder"><input id="pgFolderPath" placeholder="Folder, e.g. C:\\Users\\you\\Documents\\Coursework" maxlength="400" required aria-label="Folder path"><button type="submit" class="pg-primary">Add folder</button></form><p class="pg-muted" id="pgFolderMsg" role="status"></p>`:''}
   <h3>Recent conversations</h3>
   ${messages.length?`<ul class="pg-convo">${messages.slice(-30).map(m=>`<li class="${m.role==='user'?'you':'her'}"><b>${m.role==='user'?'You':'Cortana'}</b> ${esc(m.content.replace(/\[\[SCREEN\]\][\s\S]*/,'').slice(0,300))}</li>`).join('')}</ul>
    <button type="button" class="pg-btn pg-wide" data-act="clear">Clear conversation history</button>`:'<p class="pg-muted">No conversations saved yet.</p>'}
   <p class="pg-muted">Saved only on your PC.</p>`,'CORTANA // MEMORY');
  const folder=document.getElementById('pgFolder');
  if(folder)folder.onsubmit=async e=>{e.preventDefault();const msg=document.getElementById('pgFolderMsg');msg.textContent='Reading the folder… this can take a minute.';
   try{const v=await post('/api/documents',{action:'add_folder',path:document.getElementById('pgFolderPath').value});memory();
    setTimeout(()=>{const m=document.getElementById('pgFolderMsg');if(m)m.textContent=`Added ${v.added_count} file${v.added_count===1?'':'s'}${v.skipped.length?`; skipped ${v.skipped.length} (no readable text or too large)`:''}.`;},300);}
   catch(err){msg.textContent=err.message;}};
  document.getElementById('pgFact').onsubmit=async e=>{e.preventDefault();try{await post('/api/memory',{action:'add',text:document.getElementById('pgFactText').value});memory();}catch(err){alertIn(err.message);}};
 }catch(e){failed('memory','Memory',e);}
}

/* ---------------- Mission Briefing ---------------- */
let lastBriefing=null;
async function briefing(){
 page('briefing','Mission Briefing','<p class="pg-muted">Gathering your briefing…</p>');
 try{
  const b=lastBriefing=await get('/api/briefing');
  const w=b.weather,ev=b.events,items=b.items||[];
  const weather=!w?`<p class="pg-muted">Set your home town in Systems to see the weather.</p>`:w.error?`<p class="pg-err">${esc(w.error)}</p>`:
   `<div class="pg-card"><div class="pg-big">${esc(w.now.temp_c)}°</div><div><b>${esc(w.now.summary)}</b><br><span class="pg-muted">${esc(w.place)} · feels ${esc(w.now.feels_like_c)}° · wind ${esc(w.now.wind_kmh)} km/h</span></div></div>
    <ul class="pg-days">${w.days.map(d=>`<li><b>${esc(new Date(d.date+'T12:00').toLocaleDateString('en-GB',{weekday:'short'}))}</b>${esc(d.summary)}<span>${esc(d.high_c)}° / ${esc(d.low_c)}° · ${esc(d.rain_chance_pct??0)}% rain</span></li>`).join('')}</ul>`;
  const cal=!ev?`<p class="pg-muted">Connect your calendar in Systems to see today’s events.</p>`:ev.error?`<p class="pg-err">${esc(ev.error)}</p>`:
   ev.events.length?`<ul class="pg-list">${ev.events.map(e=>`<li class="pg-item"><span class="pg-ico">${esc(e.time)}</span><span class="pg-text">${esc(e.title)}${e.location?`<span class="pg-due">${esc(e.location)}</span>`:''}${e.source==='Cortana'?'<span class="pg-due">added by Cortana</span>':''}</span>${e.source==='Cortana'?`<button type="button" class="pg-btn pg-del" data-act="event-remove" data-id="${e.id}" aria-label="Remove event">✕</button>`:''}</li>`).join('')}</ul>`:'<p class="pg-muted">Nothing on your calendar today.</p>';
  page('briefing','Mission Briefing',`
   <p class="pg-muted">${esc(new Date().toLocaleDateString('en-GB',{weekday:'long',day:'numeric',month:'long'}))}</p>
   <button type="button" class="pg-primary pg-wide" data-act="read">▶ Read my briefing</button>
   <h3>Weather</h3>${weather}<h3>Today</h3>${cal}
   <h3>Objectives</h3>${items.length?`<ul class="pg-list">${items.slice(0,6).map(i=>`<li class="pg-item"><span class="pg-ico">${ICON[i.kind]}</span><span class="pg-text">${esc(i.text)}${i.due?`<span class="pg-due">${esc(when(i.due))}</span>`:''}</span></li>`).join('')}</ul>`:'<p class="pg-muted">No open objectives.</p>'}`,'CORTANA // MISSION BRIEFING');
 }catch(e){failed('briefing','Mission Briefing',e);}
}
function briefingSpeech(b){
 const h=new Date().getHours(),parts=[`Good ${h<12?'morning':h<18?'afternoon':'evening'}, Chief.`];
 const w=b.weather;
 if(w&&!w.error)parts.push(`It's ${w.now.temp_c} degrees and ${w.now.summary} in ${w.place.split(',')[0]}, with a high of ${w.days[0].high_c}${w.days[0].rain_chance_pct>=40?` and a ${w.days[0].rain_chance_pct} percent chance of rain`:''}.`);
 const ev=b.events;
 if(ev&&!ev.error)parts.push(ev.events.length?`You have ${ev.events.length} event${ev.events.length>1?'s':''} today: ${ev.events.slice(0,4).map(e=>(e.time==='all day'?'':e.time+', ')+e.title).join('; ')}.`:'Your calendar is clear today.');
 const items=b.items||[];
 if(items.length)parts.push(`You have ${items.length} open objective${items.length>1?'s':''}${items.length<=3?': '+items.map(i=>i.text).join(', '):''}.`);
 return parts.join(' ');
}

/* ---------------- Chat ---------------- */
/* Same holo panel as the other pages. Displays (code, tables, weather) appear as cards inside the conversation. */
function chatMsg(m,i){
 if(m.role==='system')return `<div class="chat-note${m.error?' chat-err':''}">${esc(m.text)}</div>`;
 if(m.role==='user')return `<div class="chat-msg chat-you"><small>YOU</small><p>${esc(m.text)}</p></div>`;
 const card=m.screen?(()=>{const r=D.render(m.screen);return `<div class="chat-card"><div class="chat-card-head">◆ ${esc(r.title)}<span><button type="button" class="pg-btn" data-act="card-copy" data-i="${i}">Copy</button> <button type="button" class="pg-btn" data-act="chat-display" data-i="${i}">Expand</button></span></div>${r.html}</div>`;})():'';
 const body=m.text?`<p>${esc(m.text)}</p>`:m.pending?`<p class="chat-typing">${esc(m.working?m.working+'…':'Thinking')}<i></i><i></i><i></i></p>`:'';
 return `<div class="chat-msg chat-her${m.error?' chat-err':''}"><small>CORTANA</small>${body}${card}${m.error?`<p class="pg-err">${esc(m.error)}</p>`:''}</div>`;
}
function renderChatLog(){
 const log=document.getElementById('chatLog');if(!log)return;
 const box=D.body(),atEnd=box.scrollHeight-box.scrollTop-box.clientHeight<80;
 const msgs=C.chat||[];
 log.innerHTML=msgs.length?msgs.map(chatMsg).join(''):`<p class="pg-muted chat-empty">Ask anything: “What's the weather tomorrow?”, “Set a 10 minute timer”, “How do I build a table in Python?”</p>`;
 if(atEnd)box.scrollTop=box.scrollHeight;
}
function chat(){
 page('chat','Chat',`<div id="chatLog" class="chat-log" aria-live="polite"></div>
  <form id="chatForm" class="chat-compose"><label class="sr-only" for="chatInput">Message</label>
   <button type="button" class="pg-btn chat-attach" data-act="attach" aria-label="Add a file for Cortana to read" title="Add a PDF, Word, PowerPoint or text file">📎</button>
   <button type="button" class="pg-btn chat-deep" data-act="deep" aria-pressed="${C.deep}" title="Deep thinking: she reasons before answering (slower). Or say “think carefully about…”">🧠</button>
   <textarea id="chatInput" rows="1" maxlength="3000" placeholder="Message Cortana…" enterkeyhint="send"></textarea>
   <button type="submit" class="pg-primary" aria-label="Send">Send</button></form>`,'CORTANA // COMMS');
 renderChatLog();const b=D.body();b.scrollTop=b.scrollHeight;
 const input=document.getElementById('chatInput'),form=document.getElementById('chatForm');
 const grow=()=>{input.style.height='auto';input.style.height=Math.min(input.scrollHeight,110)+'px';};
 input.addEventListener('input',grow);
 input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();form.requestSubmit();}});
 form.addEventListener('submit',e=>{e.preventDefault();const text=input.value.trim();if(!text)return;input.value='';grow();C.send(text);});
 if(matchMedia('(pointer:fine)').matches)input.focus();
}
document.addEventListener('cortana:chat',()=>{if(D.page==='chat')renderChatLog();});

/* Files for Cortana to read: the paperclip in Chat, dropping files on the panel, or Memory → Documents. */
const DOC_ACCEPT='.pdf,.docx,.pptx,.txt,.md,.csv,.json,.py,.js,.html,.htm,.xml,.log,.rtf';
const MAX_UPLOAD=12*1024*1024;
function pickFiles(){
 const input=document.createElement('input');input.type='file';input.multiple=true;input.accept=DOC_ACCEPT;
 input.onchange=()=>uploadFiles([...input.files]);input.click();
}
async function uploadFiles(list){
 for(const f of list){
  if(f.size>MAX_UPLOAD){C.note(`${f.name} is over 12 MB. Add its folder from Memory on the PC instead.`,true);continue;}
  C.note(`Reading ${f.name}…`);
  try{
   const data=await new Promise((ok,bad)=>{const r=new FileReader();r.onload=()=>ok(String(r.result).split(',')[1]||'');r.onerror=()=>bad(Error('Could not read the file.'));r.readAsDataURL(f);});
   const v=await post('/api/documents',{action:'add',name:f.name,data});
   const a=v.added;C.chat.pop();C.note(`📄 ${a.name} added${a.pages?` (${a.pages} ${/\.pptx$/i.test(a.name)?'slides':'pages'})`:''}. Ask me to summarise it, find something in it, or quiz you on it.`);
  }catch(e){C.chat.pop();C.note(`${f.name}: ${e.message}`,true);}
 }
 if(D.page==='memory')memory();
}
D.body().addEventListener('dragover',e=>{if(e.dataTransfer?.types?.includes('Files')){e.preventDefault();D.body().classList.add('drop-on');}});
D.body().addEventListener('dragleave',()=>D.body().classList.remove('drop-on'));
D.body().addEventListener('drop',e=>{if(!e.dataTransfer?.files?.length)return;e.preventDefault();D.body().classList.remove('drop-on');if(D.page!=='chat')chat();uploadFiles([...e.dataTransfer.files]);});

/* ---------------- Systems (settings) ---------------- */
/* AI model picker: rated for this PC's graphics card; models that are too big can't be chosen. */
const RATING={fast:['FAST','pg-r-fast'],good:['GOOD','pg-r-good'],slow:['SLOW','pg-r-slow'],too_big:['TOO BIG','pg-r-big']};
let modelPoll=null;
async function renderModels(){
 const box=document.getElementById('sModels');if(!box)return;
 let m;try{m=await get('/api/models');}catch(e){box.innerHTML=`<p class="pg-err">${esc(e.message)}</p>`;return;}
 const hw=m.hardware,gpu=hw.gpu?`${esc(hw.gpu)} · ${esc(hw.vram_gb)} GB graphics memory`:'No graphics card detected';
 const pull=m.pull;
 box.innerHTML=`<p class="pg-muted">${gpu} · ${esc(hw.ram_gb)} GB RAM${m.disk_free_gb!=null?` · ${esc(Math.round(m.disk_free_gb))} GB free disk`:''}</p>
  <ul class="pg-list pg-models">${m.models.map(r=>{
   const [badge,cls]=RATING[r.rating]||['?',''];const current=r.tag===m.current;const pulling=pull.active&&pull.tag===r.tag;
   const action=current?'<span class="pg-ok">IN USE</span>':!r.selectable||pulling?'':r.installed?`<button type="button" class="pg-btn" data-act="use-model" data-tag="${esc(r.tag)}">Use</button>`:
    `<button type="button" class="pg-btn" data-act="get-model" data-tag="${esc(r.tag)}"${pull.active?' disabled':''}>Download ${esc(r.size_gb)} GB</button>`;
   return `<li class="pg-item pg-model${r.selectable?'':' pg-disabled'}${current?' pg-current':''}">
    <span class="pg-text"><b>${esc(r.label)}</b> <span class="pg-badge ${cls}">${badge}</span>${r.recommended?' <span class="pg-badge pg-r-rec">★ RECOMMENDED</span>':''}${r.installed&&!current?' <span class="pg-ok">downloaded</span>':''}
     <span class="pg-due">${esc(r.blurb)} ${esc(r.note)}</span>
     ${pulling?`<span class="pg-bar"><i style="width:${Number(pull.pct)||0}%"></i></span><span class="pg-due">${esc(pull.status)} ${esc(pull.pct)}%</span>`:''}</span>${action}</li>`;}).join('')}</ul>
  ${pull.error?`<p class="pg-err">Download failed: ${esc(pull.error)}</p>`:''}
  ${m.other_installed.length?`<p class="pg-muted">Also installed: ${m.other_installed.map(esc).join(', ')}</p>`:''}`;
 clearTimeout(modelPoll);
 if(pull.active&&D.page==='settings')modelPoll=setTimeout(renderModels,1000);
}
/* First launch: the server waits for this choice before loading any model. */
function chooseModel(){
 page('settings','Choose your AI',`<p>Welcome, Chief. Pick the model Cortana thinks with. Each one is rated for <b>this PC's graphics card</b>:
  <span class="pg-badge pg-r-rec">★ RECOMMENDED</span> is the best fit, and models that are too big can't be chosen.
  Press <b>Use</b> for one that's already downloaded, or <b>Download</b> to fetch it (progress shows here). You can change it later in Systems.</p>
  <div id="sModels"><p class="pg-muted">Checking your hardware…</p></div>`,'CORTANA // FIRST SETUP');
 renderModels().then(()=>[...document.querySelectorAll('#sModels .pg-model')].find(li=>li.querySelector('.pg-r-rec'))?.scrollIntoView({block:'center'}));
}
async function systems(){
 try{
  const s=await get('/api/settings');
  const opt=(v,t,sel)=>`<option value="${esc(v)}"${sel?' selected':''}>${esc(t)}</option>`;
  page('settings','Systems',`
   <h3>Assistant</h3>
   <div id="sModels"><p class="pg-muted">Checking your hardware…</p></div>
   <label class="pg-check"><input type="checkbox" id="sTools"${s.tools_enabled?' checked':''}> Abilities (timers, memory, weather, search, calendar)</label>
   <label class="pg-check"><input type="checkbox" id="sPC"${s.pc_controls?' checked':''}> PC controls (media, volume, open allowed apps)</label>
   <label class="pg-check"><input type="checkbox" id="sAccess"${s.pc_access!==false?' checked':''}> Screen, clipboard and file access (only when you ask; nothing leaves this PC)</label>
   <h3>Brain</h3>
   <label>Memory size<select id="sContext">${opt('auto','Auto: largest that fits your graphics card',s.context_mode!=='standard')}${opt('standard','Standard (6,144 tokens)',s.context_mode==='standard')}</select></label>
   <p class="pg-muted">Current: ${esc(s.context)} tokens. Bigger remembers more of the conversation and long documents. Deep thinking: 🧠 in Chat, or say “think carefully about…”.</p>
   <h3>Character</h3>
   <label>Expression<select id="sExpression">${opt('normal','Normal',s.expression_mode!=='expressive')}${opt('expressive','Expressive',s.expression_mode==='expressive')}</select></label>
   <button type="button" class="pg-btn pg-wide" data-act="expression-preview">Preview expression</button>
   <h3>Voice</h3>
   <label>Engine<select id="sEngine">${opt('zipvoice','Reference voice (experimental, closer, slower)',s.voice_engine==='zipvoice')}${opt('piper','Natural (Piper)',s.voice_engine==='piper')}${opt('windows','Windows voice',s.voice_engine==='windows')}</select></label>
   <label>Natural voice<select id="sVoice">${s.voices.map(v=>opt(v.name,v.name+(v.stock?'':' — your voice')+(v.installed?'':' (downloads)'),v.name===s.voice)).join('')}</select></label>
   <p class="pg-muted">${esc(s.voice_status)} Trained voices: put the .onnx and .onnx.json in %LOCALAPPDATA%\\CortanaAI\\voices, then restart.</p>
   <button type="button" class="pg-btn pg-wide" data-act="voice-preview">Save and preview voice</button>
   <label class="pg-check"><input type="checkbox" id="sNotifications"${s.native_notifications!==false?' checked':''}> Windows reminders while the browser is closed (keep the launcher running)</label>
   <p class="pg-muted">${Object.entries((await get('/api/status')).latency||{}).map(([k,v])=>esc(({tts_ms:'Speech preparation',first_token_ms:'First model token',transcription_ms:'Transcription',playback_ms:'Send to playback',reply_ms:'Full reply'})[k]||k)+': '+esc(v)+' ms').join(' · ')||'Timings appear after your first conversation.'}</p>
   <label class="pg-check"><input type="checkbox" id="sWake"${C.wake?' checked':''}> “Hey Cortana” wake word (this device; listens locally)</label>
   <h3>Briefing</h3>
   <label>Home town (for weather)<input id="sHome" value="${esc(s.home_location||'')}" maxlength="80" placeholder="e.g. London"></label>
   <label>Calendar secret iCal address ${s.calendar_connected?'<span class="pg-ok">connected</span>':''}<input id="sCal" type="password" autocomplete="off" placeholder="${s.calendar_connected?'Leave blank to keep':'https://calendar.google.com/calendar/ical/…/basic.ics'}"></label>
   <p class="pg-muted">Google Calendar → Settings → your calendar → “Secret address in iCal format”. Treat it like a password.</p>
   ${s.calendar_connected?'<button type="button" class="pg-btn pg-wide" data-act="disconnect">Disconnect calendar</button>':''}
   <label>Brave Search key (optional, for full web results) ${s.brave_connected?'<span class="pg-ok">saved</span>':''}<input id="sBrave" type="password" autocomplete="off" placeholder="${s.brave_connected?'Leave blank to keep':'Without it, search uses encyclopedia-style answers'}"></label>
   <h3>Phone</h3>
   <label>Phone connection<select id="sPhone">${opt('cloudflare','Temporary link (Cloudflare) — new QR each launch',s.phone_access!=='tailscale')}${opt('tailscale','Stable link (Tailscale) — needs Tailscale on PC and phone',s.phone_access==='tailscale')}</select></label>
   <p class="pg-muted">Phone connection changes apply next time you start Cortana.</p>
   <button type="button" class="pg-btn pg-wide" data-act="display">Hologram, speech pace and phone QR…</button>
   <button type="button" class="pg-primary pg-wide" data-act="save">Save</button><p id="sMsg" class="pg-muted" role="status"></p>`,'CORTANA // SYSTEMS');
  document.getElementById('sWake').onchange=async e=>{if(!await C.setWake(e.target.checked))e.target.checked=false;};
  renderModels();
  systems.initial=s;
 }catch(e){failed('settings','Systems',e);}
}
async function saveSystems(){
 const s=systems.initial||{},v=id=>document.getElementById(id),data={};
 data.tools_enabled=v('sTools').checked;data.pc_controls=v('sPC').checked;data.pc_access=v('sAccess').checked;
 if(v('sEngine').value!==s.voice_engine)data.voice_engine=v('sEngine').value;
 if(v('sVoice').value!==s.voice)data.voice=v('sVoice').value;
 data.expression_mode=v('sExpression').value;data.context_mode=v('sContext').value;data.native_notifications=v('sNotifications').checked;
 data.home_location=v('sHome').value.trim();
 if(v('sCal').value.trim())data.calendar_url=v('sCal').value.trim();
 if(v('sBrave').value.trim())data.brave_key=v('sBrave').value.trim();
 data.phone_access=v('sPhone').value;
 try{await post('/api/settings',data);C.applyMode(data.expression_mode);if(v('sMsg'))v('sMsg').textContent='Saved.';setTimeout(()=>{if(D.page==='settings')systems();},700);}catch(e){if(v('sMsg'))v('sMsg').textContent=e.message;}
}

/* ---------------- shared ---------------- */
function alertIn(message){const b=D.body();const p=document.createElement('p');p.className='pg-err';p.textContent=message;b.prepend(p);}
const confirmClear={armed:false};
D.body().addEventListener('click',async e=>{
 const btn=e.target.closest('[data-act]');if(!btn)return;
 const act=btn.dataset.act,id=btn.dataset.id;
 try{
  if(act==='complete'||act==='delete'||act==='snooze'){await post('/api/objectives',{action:act,id:Number(id)});objectives();}
  else if(act==='deep'){C.deep=!C.deep;btn.setAttribute('aria-pressed',String(C.deep));C.note(C.deep?'Deep thinking on: slower, more careful answers.':'Deep thinking off.');}
  else if(act==='edit-fact'){await post('/api/memory',{action:'edit',id:Number(id),text:document.querySelector('[data-fact="'+Number(id)+'"]').value});memory();}
  else if(act==='forget'){await post('/api/memory',{action:'forget',id:Number(id)});memory();}
  else if(act==='clear'){if(!confirmClear.armed){confirmClear.armed=true;btn.textContent='Tap again to clear everything';setTimeout(()=>{confirmClear.armed=false;},4000);return;}
   await post('/api/memory',{action:'clear_history'});C.clearConversation();memory();}
  else if(act==='read'&&lastBriefing)C.speak(briefingSpeech(lastBriefing));
  else if(act==='save')saveSystems();
  else if(act==='expression-preview'){C.applyMode(document.getElementById('sExpression').value,true);C.speak('Still with me, Chief? Of course you are. What is our next move?');}
  else if(act==='voice-preview'){await post('/api/settings',{voice_engine:document.getElementById('sEngine').value,voice:document.getElementById('sVoice').value});C.speak('Systems online, Chief. I am ready when you are.');}
  else if(act==='setup-preview'){C.applyMode(document.getElementById('setupExpression').value,true);await post('/api/settings',{voice_engine:document.getElementById('setupVoice').value});C.speak('Still with me, Chief? Of course you are. What is our next move?');}
  else if(act==='setup-save'){const mode=document.getElementById('setupExpression').value;await post('/api/settings',{expression_mode:mode,voice_engine:document.getElementById('setupVoice').value,setup_complete:true});C.applyMode(mode);chat();}
  else if(act==='get-model'||act==='use-model'){btn.disabled=true;await post('/api/models',{action:act==='get-model'?'download':'use',tag:btn.dataset.tag});renderModels();}
  else if(act==='disconnect'){await post('/api/settings',{calendar_url:''});systems();}
  else if(act==='attach')pickFiles();
  else if(act==='doc-remove'){await post('/api/documents',{action:'remove',id:Number(id)});memory();}
  else if(act==='event-remove'){await post('/api/events',{action:'remove',id:Number(id)});briefing();}
  else if(act==='card-copy'){
   const md=(C.chat||[])[Number(btn.dataset.i)]?.screen||'';
   const text=md.replace(/^# .*\n?/,'').replace(/^```\w*$/gm,'').replace(/\*\*([^*]+)\*\*/g,'$1').replace(/`([^`]+)`/g,'$1')
    .replace(/\[([^\]]+)\]\((https:[^)]+)\)/g,'$1: $2').replace(/^\|?\s*-{3,}.*$/gm,'').replace(/\n{3,}/g,'\n\n').trim();
   try{await navigator.clipboard.writeText(text);btn.textContent='Copied';}catch{btn.textContent='Copy failed';}setTimeout(()=>{btn.textContent='Copy';},1500);}
  else if(act==='chat-display'){const m=(C.chat||[])[Number(btn.dataset.i)];if(m?.screen)C.showScreen(m.screen);}
  else if(act==='display'){D.hide();document.getElementById('settingsDialog').showModal();}
 }catch(err){alertIn(err.message);}
});
document.addEventListener('cortana:refresh',e=>{
 if(e.detail.what==='objectives'&&D.page==='tasks')objectives();
 if((e.detail.what==='memory'||e.detail.what==='documents')&&D.page==='memory')memory();
});
async function setup(){
 try{
 const s=await get('/api/settings');
 page('setup','Meet Cortana',`<p>Choose how she moves and speaks. You can change both later in Systems.</p>
 <label>Expression<select id="setupExpression"><option value="normal"${s.expression_mode==='normal'?' selected':''}>Normal — the previous Expressive</option><option value="expressive"${s.expression_mode==='expressive'?' selected':''}>Expressive — stronger reactions and gestures</option></select></label>
 <label>PC voice<select id="setupVoice"><option value="piper"${s.voice_engine==='piper'?' selected':''}>Piper — fast and light</option><option value="zipvoice"${s.voice_engine==='zipvoice'?' selected':''}>Reference voice — closer, experimental, slower CPU speech</option><option value="windows"${s.voice_engine==='windows'?' selected':''}>Windows fallback</option></select></label>
 <p class="pg-muted">The reference voice downloads roughly 185 MB. It is experimental and can skip words; there is no pitch shifting or promise of an exact match.</p>
 <button type="button" class="pg-btn pg-wide" data-act="setup-preview">Preview</button>
 <button type="button" class="pg-primary pg-wide" data-act="setup-save">Save and continue</button>`,'CORTANA // FIRST SETUP');
 }catch(e){failed('setup','Meet Cortana',e);}
}
const PAGES={setup,chat,tasks:objectives,memory,briefing,settings:systems,'choose-model':chooseModel};
window.CortanaPages={open(target){const fn=PAGES[target];if(!fn)return false;fn();return true;}};
