/* Cortana pages: Mission Briefing, Objectives, Memory and Systems, shown in the holographic display panel.
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
  <button type="button" class="pg-btn" data-act="complete" data-id="${i.id}" aria-label="Done">✓</button>
  <button type="button" class="pg-btn pg-del" data-act="delete" data-id="${i.id}" aria-label="Delete">✕</button></li>`;
}
async function objectives(){
 try{
  const {items}=await get('/api/objectives');
  const groups=[['timer','Timers'],['reminder','Reminders'],['task','To-do']].map(([k,t])=>{const list=items.filter(i=>i.kind===k);return list.length?`<h3>${t}</h3><ul class="pg-list">${list.map(itemRow).join('')}</ul>`:'';}).join('');
  page('tasks','Objectives',`
   <form class="pg-add" id="pgAdd">
    <select id="pgKind" aria-label="Type"><option value="task">To-do</option><option value="timer">Timer</option><option value="reminder">Reminder</option></select>
    <input id="pgText" placeholder="What is it?" maxlength="200" required aria-label="Text">
    <input id="pgMinutes" type="number" min="0.1" max="1440" step="any" value="5" aria-label="Minutes" hidden>
    <input id="pgAt" type="datetime-local" aria-label="When" hidden>
    <button type="submit" class="pg-primary">Add</button>
   </form>
   ${groups||'<p class="pg-muted">Nothing open. Ask Cortana to set a timer, a reminder or add something to your list.</p>'}`,'CORTANA // OBJECTIVES');
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
  const {facts,messages}=await get('/api/memory');
  page('memory','Memory',`
   <h3>What I remember about you</h3>
   ${facts.length?`<ul class="pg-list">${facts.map(f=>`<li class="pg-item"><span class="pg-text">${esc(f.text)}</span><button type="button" class="pg-btn pg-del" data-act="forget" data-id="${f.id}" aria-label="Forget">✕</button></li>`).join('')}</ul>`:'<p class="pg-muted">Nothing yet. Tell me things like “remember my dog is called Max”.</p>'}
   <form class="pg-add" id="pgFact"><input id="pgFactText" placeholder="Add something to remember" maxlength="300" required aria-label="Fact"><button type="submit" class="pg-primary">Remember</button></form>
   <h3>Recent conversations</h3>
   ${messages.length?`<ul class="pg-convo">${messages.slice(-30).map(m=>`<li class="${m.role==='user'?'you':'her'}"><b>${m.role==='user'?'You':'Cortana'}</b> ${esc(m.content.replace(/\[\[SCREEN\]\][\s\S]*/,'').slice(0,300))}</li>`).join('')}</ul>
    <button type="button" class="pg-btn pg-wide" data-act="clear">Clear conversation history</button>`:'<p class="pg-muted">No conversations saved yet.</p>'}
   <p class="pg-muted">Saved only on your PC.</p>`,'CORTANA // MEMORY');
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
   ev.events.length?`<ul class="pg-list">${ev.events.map(e=>`<li class="pg-item"><span class="pg-ico">${esc(e.time)}</span><span class="pg-text">${esc(e.title)}${e.location?`<span class="pg-due">${esc(e.location)}</span>`:''}</span></li>`).join('')}</ul>`:'<p class="pg-muted">Nothing on your calendar today.</p>';
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

/* ---------------- Systems (settings) ---------------- */
const MODEL_NAMES={'qwen3.5:9b':'Smart — Qwen 3.5 9B','qwen3.5:4b':'Fast — Qwen 3.5 4B','qwen3.5:27b':'Maximum — Qwen 3.5 27B (slow on 8 GB)'};
async function systems(){
 try{
  const s=await get('/api/settings');
  const opt=(v,t,sel)=>`<option value="${esc(v)}"${sel?' selected':''}>${esc(t)}</option>`;
  page('settings','Systems',`
   <h3>Assistant</h3>
   <label>AI model<select id="sModel">${(s.models.length?s.models:[s.model]).map(m=>opt(m,MODEL_NAMES[m]||m,m===s.model)).join('')}</select></label>
   <label class="pg-check"><input type="checkbox" id="sTools"${s.tools_enabled?' checked':''}> Abilities (timers, memory, weather, search, calendar)</label>
   <label class="pg-check"><input type="checkbox" id="sPC"${s.pc_controls?' checked':''}> PC controls (media, volume, open allowed apps)</label>
   <h3>Voice</h3>
   <label>Engine<select id="sEngine">${opt('piper','Natural (Piper)',s.voice_engine==='piper')}${opt('windows','Windows voice',s.voice_engine==='windows')}</select></label>
   <label>Natural voice<select id="sVoice">${s.voices.map(v=>opt(v.name,v.name+(v.stock?'':' — your voice')+(v.installed?'':' (downloads)'),v.name===s.voice)).join('')}</select></label>
   <p class="pg-muted">${esc(s.voice_status)} Trained voices: put the .onnx and .onnx.json in %LOCALAPPDATA%\\CortanaAI\\voices, then restart.</p>
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
  systems.initial=s;
 }catch(e){failed('settings','Systems',e);}
}
async function saveSystems(){
 const s=systems.initial||{},v=id=>document.getElementById(id),data={};
 if(v('sModel').value!==s.model)data.model=v('sModel').value;
 data.tools_enabled=v('sTools').checked;data.pc_controls=v('sPC').checked;
 if(v('sEngine').value!==s.voice_engine)data.voice_engine=v('sEngine').value;
 if(v('sVoice').value!==s.voice)data.voice=v('sVoice').value;
 data.home_location=v('sHome').value.trim();
 if(v('sCal').value.trim())data.calendar_url=v('sCal').value.trim();
 if(v('sBrave').value.trim())data.brave_key=v('sBrave').value.trim();
 data.phone_access=v('sPhone').value;
 try{await post('/api/settings',data);v('sMsg').textContent='Saved.';setTimeout(systems,700);}catch(e){v('sMsg').textContent=e.message;}
}

/* ---------------- shared ---------------- */
function alertIn(message){const b=D.body();const p=document.createElement('p');p.className='pg-err';p.textContent=message;b.prepend(p);}
const confirmClear={armed:false};
D.body().addEventListener('click',async e=>{
 const btn=e.target.closest('[data-act]');if(!btn)return;
 const act=btn.dataset.act,id=btn.dataset.id;
 try{
  if(act==='complete'||act==='delete'){await post('/api/objectives',{action:act,id:Number(id)});objectives();}
  else if(act==='forget'){await post('/api/memory',{action:'forget',id:Number(id)});memory();}
  else if(act==='clear'){if(!confirmClear.armed){confirmClear.armed=true;btn.textContent='Tap again to clear everything';setTimeout(()=>{confirmClear.armed=false;},4000);return;}
   await post('/api/memory',{action:'clear_history'});memory();}
  else if(act==='read'&&lastBriefing)C.speak(briefingSpeech(lastBriefing));
  else if(act==='save')saveSystems();
  else if(act==='disconnect'){await post('/api/settings',{calendar_url:''});systems();}
  else if(act==='display'){D.hide();document.getElementById('settingsDialog').showModal();}
 }catch(err){alertIn(err.message);}
});
document.addEventListener('cortana:refresh',e=>{
 if(e.detail.what==='objectives'&&D.page==='tasks')objectives();
 if(e.detail.what==='memory'&&D.page==='memory')memory();
});
const PAGES={tasks:objectives,memory,briefing,settings:systems};
window.CortanaPages={open(target){const fn=PAGES[target];if(!fn)return false;fn();return true;}};
