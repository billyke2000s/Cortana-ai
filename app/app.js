const $=id=>document.getElementById(id);
const app=$('app'),out=$('transcript'),label=$('listenLabel'),mic=$('mic');
const clientId=crypto.randomUUID?.().replaceAll('-','')||Math.random().toString(36).slice(2);
let pendingImages=[],pendingConfirm=null,deepThinking=false,activeJob=null,turnStarted=0,playingText='',restorePromise=null,restored=false,modePreviewUntil=0;
const wake={on:false,stream:null,input:null,node:null,busy:false,pending:null};
let queue=null,state='idle',audioContext=null,source=null,requestId=0,controller=null,recording=null,workletReady=false,capabilities={ai:false,timedSpeech:false},history=[];
const avatar=()=>window.CortanaAvatar;
function setState(s,text){state=s;app.classList.toggle('idle',s==='idle');app.classList.toggle('speaking',s==='speaking');mic.setAttribute('aria-pressed',String(s==='listening'));mic.setAttribute('aria-label',s==='listening'?'Finish listening':'Start listening');label.textContent=text;avatar()?.setState(s);document.dispatchEvent(new CustomEvent('cortana:state',{detail:{state:s}}));}
function idleLabel(){return wake.on?'SAY “HEY CORTANA”':'TAP THE MIC TO SPEAK';}
function error(message){out.textContent=message;out.classList.add('err');setState('idle','READY WHEN YOU ARE');}
function stop(){if(activeJob)api('/api/cancel',{request_id:activeJob}).catch(()=>{});activeJob=null;playingText='';requestId++;controller?.abort();controller=null;queue?.stop();queue=null;if(source){source.onended=null;try{source.stop();}catch{}source=null;}recording?.cancel();recording=null;avatar()?.stopSpeech();setState('idle',idleLabel());}
async function unlockAudio(){audioContext??=new AudioContext();await audioContext.resume();}
async function api(path,data,signal){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data),signal,keepalive:path==='/api/cancel'});const value=await r.json();if(!r.ok)throw Error(value.error||'Service unavailable.');return value;}
/* ---- Speech: each sentence is voiced as soon as it arrives and played back-to-back ---- */
// Mouth shapes from loudness for voices that don't report them (Piper). Ids follow the viseme set in avatar.js.
function envelopeCues(buffer){
 const data=buffer.getChannelData(0),rate=buffer.sampleRate,win=Math.max(1,Math.floor(rate*.045)),levels=[];
 for(let i=0;i<data.length;i+=win){
  const end=Math.min(data.length,i+win);let sum=0,cross=0;
  for(let k=i;k<end;k++){sum+=data[k]*data[k];if(k>i&&(data[k]>=0)!==(data[k-1]>=0))cross++;}
  levels.push({rms:Math.sqrt(sum/Math.max(1,end-i)),zcr:cross/Math.max(1,end-i)});
 }
 const sorted=levels.map(l=>l.rms).sort((a,b)=>a-b),peak=sorted[Math.floor(sorted.length*.95)]||1;
 const cues=[];let last=-1;
 levels.forEach((l,i)=>{
  const v=l.rms/peak;let id;
  if(v<.10)id=0;else if(l.zcr>.25&&v<.6)id=15;else if(v<.30)id=13;else if(v<.55)id=i%3?5:6;else if(v<.8)id=i%2?4:3;else id=2;
  if(id!==last){cues.push({time:i*win/rate,duration:win/rate,id});last=id;}else cues[cues.length-1].duration+=win/rate;
 });
 return cues;
}
class SpeechQueue{
 constructor(id){this.id=id;this.job=activeJob??=clientId+'_'+id;this.abort=new AbortController();this.chain=Promise.resolve();this.sources=[];this.cues=[];this.t0=null;this.end=0;this.count=0;this.finished=0;this.closed=false;this.failure=null;}
 add(text){
  const id=this.id;
  // Synthesis starts now so the next sentence is prepared while this one plays; Stop aborts the request and cancels it on the PC.
  const audio=api('/api/speech',{text,rate:Number($('rate').value),request_id:this.job},this.abort.signal).catch(e=>({error:e.message}));
  if(capabilities.voiceReady===false&&state==='thinking')label.textContent='LOADING CORTANA\u2019S VOICE…';
  this.count++;
  this.chain=this.chain.then(async()=>{
   if(id!==requestId)return;
   const result=await audio;if(id!==requestId)return;
   if(result.error){this.failure=result.error;this.finished++;return this.check();}
   const buffer=await audioContext.decodeAudioData(Uint8Array.from(atob(result.audio),c=>c.charCodeAt(0)).buffer);if(id!==requestId)return;
   const node=audioContext.createBufferSource();node.buffer=buffer;node.connect(audioContext.destination);
   const start=Math.max(audioContext.currentTime+.05,this.end);
   if(this.t0===null){this.t0=start;avatar()?.startSpeech(this.cues,()=>audioContext.currentTime-this.t0,0,performanceFor(text));setState('speaking','CORTANA IS SPEAKING…');}
   for(const c of (result.visemes?.length?result.visemes:envelopeCues(buffer)))this.cues.push({time:c.time+start-this.t0,duration:c.duration,id:c.id});
   this.end=start+buffer.duration;avatar()?.extendSpeech?.(this.end-this.t0);
   playingText+=' '+text;setTimeout(()=>{if(id===requestId)avatar()?.setPerformance?.(performanceFor(text));},Math.max(0,(start-audioContext.currentTime)*1000));
   if(!this.sources.length&&turnStarted)api('/api/metrics',{playback_ms:performance.now()-turnStarted+Math.max(0,(start-audioContext.currentTime)*1000)}).catch(()=>{});
   node.onended=()=>{this.finished++;this.check();};node.start(start);this.sources.push(node);
   $('voiceInfo').textContent=result.voice||'Local voice';
  }).catch(e=>{this.failure=e.message;this.finished++;this.check();});
 }
 close(){this.closed=true;this.chain.then(()=>this.check());}
 check(){
  if(!this.closed||this.finished<this.count||this.id!==requestId||this.done)return;
  this.done=true;avatar()?.stopSpeech();queue=null;
  if(this.failure&&!this.sources.length)error(this.failure);else setState('idle',idleLabel());
 }
 stop(){this.abort.abort();for(const s of this.sources){s.onended=null;try{s.stop();}catch{}}this.sources=[];}
}
function performanceFor(text){return /\b(sorry|difficult|worried|careful|danger|warning)\b/i.test(text)?'concerned':/\b(joke|funny|nice|clever|kidding|of course|chief)\b/i.test(text)?'playful':text.includes('?')?'curious':'focused';}
async function speak(text){
 stop();turnStarted=performance.now();const id=requestId;out.classList.remove('err');out.textContent=text;
 try{await unlockAudio();}catch{}
 if(id!==requestId)return;
 setState('thinking','PREPARING VOICE…');queue=new SpeechQueue(id);queue.add(text);queue.close();
}
/* Conversation shown on the Chat page: [{role:'user'|'assistant', text, screen?, error?}] (this tab only, newest last). */
const chatLog=[];
function chatChanged(){document.dispatchEvent(new CustomEvent('cortana:chat'));}
const YES=/^(yes|yeah|yep|yup|sure|ok(ay)?|do it|go ahead|go for it|approve(d)?|confirm(ed)?|please do)\b[\s\S]{0,30}$/i,NO=/^(no|nope|cancel|don'?t|stop|never ?mind|leave it)\b[\s\S]{0,30}$/i;
async function resolveConfirm(id,approve){
 const card=chatLog.flatMap(m=>m.confirms||[]).find(c=>c.id===id);if(!card||card.state!=='waiting')return;
 if(pendingConfirm===id)pendingConfirm=null;
 card.state='working';chatChanged();
 try{
  const r=await api('/api/confirm',{id,approve});card.state=approve?(r.ok?'done':'failed'):'cancelled';
  if(r.refresh)document.dispatchEvent(new CustomEvent('cortana:refresh',{detail:{what:r.refresh}}));
  if(r.result?.identical_copies)note('Identical copies (left in place): '+r.result.identical_copies.map(g=>g.join(' = ')).join('; '));
  chatChanged();speak(r.say);
 }catch(e){card.state='failed';chatChanged();error(e.message);}
}
async function send(text){
 await restoreConversation();
 if(pendingConfirm&&(YES.test(text.trim())||NO.test(text.trim()))){   // "yes" / "cancel" answers the waiting approval card
  chatLog.push({role:'user',text});chatChanged();return resolveConfirm(pendingConfirm,YES.test(text.trim()));
 }
 pendingConfirm=null;
 const inChat=holoPage==='chat';
 stop();turnStarted=performance.now();activeJob=clientId+'_'+requestId;if(!inChat)hideScreen();holoLast='';holoReopen.hidden=true;
 chatLog.push({role:'user',text});const turn={role:'assistant',text:'',pending:true};chatLog.push(turn);if(chatLog.length>60)chatLog.splice(0,chatLog.length-60);chatChanged();out.classList.remove('err');out.textContent='You: '+text;
 const id=requestId;
 try{await unlockAudio();}catch{}
 if(id!==requestId)return;
 if(!capabilities.ai){error(capabilities.status||'The assistant is still starting. Check the launcher.');return;}
 controller=new AbortController();setState('thinking','CORTANA IS THINKING…');
 const messages=[...history,{role:'user',content:text}].slice(-18),q=queue=new SpeechQueue(id);let spoken='';
 const handle=ev=>{
  if(ev.type==='sentence'){spoken+=(spoken?' ':'')+ev.text;out.textContent=spoken;out.scrollTop=out.scrollHeight;q.add(ev.text);turn.text=spoken;chatChanged();}
  else if(ev.type==='tool'){if(state==='thinking')label.textContent=ev.label+'…';turn.working=ev.label;chatChanged();}
  else if(ev.type==='screen'){turn.screen=ev.markdown;holoLast=ev.markdown;if(holoPage==='chat')chatChanged();else showScreen(ev.markdown);}   // in Chat, the card goes inline
  else if(ev.type==='confirm'){(turn.confirms??=[]).push({id:ev.id,name:ev.name,label:ev.label,summary:ev.summary,detail:ev.detail,state:'waiting'});pendingConfirm=ev.id;chatChanged();if(holoPage!=='chat')window.CortanaPages?.open('chat');}
  else if(ev.type==='refresh')document.dispatchEvent(new CustomEvent('cortana:refresh',{detail:{what:ev.what}}));
  else if(ev.type==='done')history=[...messages,{role:'assistant',content:ev.raw||ev.reply}].slice(-18);
  else if(ev.type==='error')throw Error(ev.error);
 };
 try{
  const r=await fetch('/api/chat-stream',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({messages,request_id:activeJob,think:deepThinking,images:pendingImages.splice(0)}),signal:controller.signal});
  if(!r.ok){const v=await r.json().catch(()=>({}));throw Error(v.error||'Service unavailable.');}
  const reader=r.body.getReader(),decoder=new TextDecoder();let buf='';
  for(;;){
   const {value,done}=await reader.read();if(id!==requestId){turn.pending=false;chatChanged();return;}if(done)break;
   buf+=decoder.decode(value,{stream:true});let i;
   while((i=buf.indexOf('\n'))>=0){const line=buf.slice(0,i).trim();buf=buf.slice(i+1);if(line)handle(JSON.parse(line));}
  }
  if(buf.trim())handle(JSON.parse(buf));
  q.close();turn.pending=false;turn.working=null;chatChanged();
 }catch(e){
  turn.pending=false;turn.working=null;
  if(e.name==='AbortError'||id!==requestId){if(!turn.text)turn.text='(stopped)';chatChanged();return;}
  turn.error=e.message;chatChanged();
  q.close();if(!spoken)error(e.message);else out.textContent=spoken+' (Interrupted: '+e.message+')';
 }
}
function encodeWav(chunks,rate){
 const length=chunks.reduce((n,c)=>n+c.length,0),all=new Float32Array(length);let offset=0;
 for(const c of chunks){all.set(c,offset);offset+=c.length;}
 const frames=Math.floor(length*16000/rate),buffer=new ArrayBuffer(44+frames*2),view=new DataView(buffer);
 const str=(at,text)=>{for(let i=0;i<text.length;i++)view.setUint8(at+i,text.charCodeAt(i));};
 str(0,'RIFF');view.setUint32(4,36+frames*2,true);str(8,'WAVE');str(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,16000,true);view.setUint32(28,32000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);str(36,'data');view.setUint32(40,frames*2,true);
 for(let i=0;i<frames;i++){const a=Math.floor(i*rate/16000),b=Math.min(length,Math.floor((i+1)*rate/16000));let sum=0;for(let k=a;k<Math.max(a+1,b);k++)sum+=all[k]||0;const sample=Math.max(-1,Math.min(1,sum/Math.max(1,b-a)));view.setInt16(44+i*2,sample<0?sample*32768:sample*32767,true);}
 const bytes=new Uint8Array(buffer);let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));return btoa(binary);
}
async function listen(){
 if(recording){recording.finish();return;}
 stop();const id=requestId;
 if(!capabilities.transcription){error('Microphone recognition is still starting. You can type while it loads.');return;}
 if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia){error('Open the secure phone link from the QR code to use the microphone.');return;}
 let stream=null;
 try{
  await unlockAudio();setState('thinking','OPENING MICROPHONE...');
  stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
  if(id!==requestId){stream.getTracks().forEach(t=>t.stop());return;}
  if(!workletReady){await audioContext.audioWorklet.addModule('./mic-worklet.js');workletReady=true;}
  if(id!==requestId){stream.getTracks().forEach(t=>t.stop());return;}
  const input=audioContext.createMediaStreamSource(stream),node=new AudioWorkletNode(audioContext,'cortana-capture');
  const chunks=[];let done=false,heard=false,lastVoice=performance.now(),started=lastVoice;
  const cleanup=()=>{done=true;node.port.onmessage=null;input.disconnect();node.disconnect();stream.getTracks().forEach(t=>t.stop());recording=null;};
  const finish=async()=>{
   if(done)return;cleanup();if(id!==requestId)return;
   if(!heard||!chunks.length){error('Did not catch that. Tap the microphone and try again.');return;}
   setState('thinking','LISTENING BACK...');controller=new AbortController();
   try{const result=await api('/api/transcribe',{audio:encodeWav(chunks,audioContext.sampleRate)},controller.signal);if(id!==requestId)return;out.textContent='You: '+result.text;await send(result.text);}catch(e){if(id===requestId&&e.name!=='AbortError')error(e.message);}
  };
  recording={finish,cancel:cleanup};
  node.port.onmessage=e=>{if(done)return;const c=e.data;chunks.push(c);let rms=0;for(const v of c)rms+=v*v;rms=Math.sqrt(rms/c.length);const now=performance.now();if(rms>.014){heard=true;lastVoice=now;}
   $('wave').style.opacity=String(Math.min(1,.35+rms*8));
   if((heard&&now-lastVoice>1200&&now-started>1500)||(!heard&&now-started>8000)||now-started>29000)finish();
  };
  input.connect(node);node.connect(audioContext.destination);out.textContent='Speak naturally. Tap the mic again when finished.';setState('listening','CORTANA IS LISTENING...');
 }catch(e){stream?.getTracks().forEach(t=>t.stop());if(id===requestId){recording?.cancel();error(e.name==='NotAllowedError'?'Microphone access was blocked. Allow it in browser settings, or type a message.':'Could not open the microphone. You can still type.');}}
}
function openDialog(id){$(id).showModal();}
for(const d of document.querySelectorAll('dialog')){d.querySelector('.close-dialog').addEventListener('click',()=>d.close());}
function preference(key,fallback){try{return localStorage.getItem('cortana.'+key)??fallback;}catch{return fallback;}}
function savePreference(key,value){try{localStorage.setItem('cortana.'+key,value);}catch{}}
$('character').value=preference('character','1.3')==='1.8'?'1.8':'1.3';$('rate').value=preference('rate','0');$('hologramView').value=preference('view','portrait');
function applySettings(){avatar()?.setCharacter($('character').value);avatar()?.setFull($('hologramView').value==='full');}
$('character').addEventListener('change',()=>{savePreference('character',$('character').value);applySettings();api('/api/settings',{expression_mode:$('character').value==='1.8'?'expressive':'normal'}).catch(()=>{});});
$('rate').addEventListener('change',()=>savePreference('rate',$('rate').value));
deepThinking=preference('deep','0')==='1';
$('hologramView').addEventListener('change',()=>{savePreference('view',$('hologramView').value);applySettings();});
applySettings();document.addEventListener('cortana:avatar-ready',applySettings);
mic.addEventListener('click',listen);
document.querySelector('[aria-label="Type a message"]').addEventListener('click',()=>navigate('chat'));

document.querySelector('.menu-btn').addEventListener('click',()=>navigate('settings'));
const sideButtons=document.querySelectorAll('.side-btn');if(sideButtons[1]){sideButtons[1].setAttribute('aria-label','Stop speech');sideButtons[1].addEventListener('click',stop);}
function info(title,text){$('infoTitle').textContent=title;$('infoText').textContent=text;openDialog('infoDialog');}
function navigate(target){
 if(target==='voice')target='chat';
 if(window.CortanaPages?.open(target))return;
 if(target==='settings'){openDialog('settingsDialog');return;}
 if(['home','cortana'].includes(target)){hideScreen();return;}
 const entries={briefing:['Mission briefing','Calendar and agenda services have not been connected yet.'],tasks:['Objectives','Task and reminder services have not been connected yet.'],memory:['Conversation memory',history.length?history.map(m=>(m.role==='user'?'You: ':'Cortana: ')+m.content).join('\n\n'):'No AI conversation in this session yet. Conversations are kept in memory only.']};
 const entry=entries[target]||['Not connected','This section needs its corresponding assistant service.'];info(...entry);
}
document.querySelectorAll('[data-target]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.target)));
const nav=$('nav'),accent=$('navAccent');
function moveAccent(b){if(!b)return;const nr=nav.getBoundingClientRect(),br=b.getBoundingClientRect();accent.style.width=Math.max(60,br.width+30)+'px';accent.style.transform=`translateX(${br.left-nr.left-15}px)`;}
nav.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{nav.querySelector('.active')?.classList.remove('active');b.classList.add('active');moveAccent(b);navigate(b.dataset.tab);document.dispatchEvent(new CustomEvent('cortana:navigate',{detail:{tab:b.dataset.tab}}));}));
addEventListener('resize',()=>moveAccent(nav.querySelector('.active')));requestAnimationFrame(()=>moveAccent(nav.querySelector('.active')));
function clock(){const now=new Date();$('date').textContent=now.toLocaleDateString('en-GB',{weekday:'long',day:'numeric',month:'long'}).toUpperCase();const h=now.getHours();$('greet').textContent=`Good ${h<12?'morning':h<18?'afternoon':'evening'}, Chief.`;}
clock();setInterval(clock,60000);
const heights=[3,3,10,14,6,22,12,28,8,34,40,34,8,28,12,22,6,14,10,3,3];
heights.forEach((h,i)=>{const s=document.createElement('span');if(h<=3)s.className='dot';s.style.setProperty('--h',h+'px');s.style.setProperty('--dl',(-i*.09)+'s');$('wave').appendChild(s);});
for(let i=0;i<24;i++){const p=document.createElement('i');p.style.left=(12+Math.random()*76)+'%';p.style.top=(15+Math.random()*65)+'%';p.style.setProperty('--d',(5+Math.random()*5)+'s');p.style.setProperty('--dl',(-Math.random()*8)+'s');$('particles').appendChild(p);}
let statusBusy=false,shownQR=false;
async function refreshStatus(){
 if(statusBusy)return;statusBusy=true;
 try{const r=await fetch('/api/status');if(!r.ok)throw Error('Connection lost');capabilities=await r.json();
  if(performance.now()>modePreviewUntil)applyMode(capabilities.expressionMode);
  $('connectionNote').textContent=capabilities.ai?'Connected to your PC':capabilities.status||'Starting assistant...';
  $('aiInfo').textContent=capabilities.ai?'Local assistant: '+capabilities.model:capabilities.status;
  $('statusText').textContent=capabilities.ai?'ONLINE':'STARTING';
  announceAlerts(capabilities.alerts||[]);
  // First launch: keep the model chooser up (Systems also contains it) until a model is picked.
  if(capabilities.chooseModel&&capabilities.canPair&&window.CortanaDisplay?.page!=='settings')window.CortanaPages?.open('choose-model');
  if(!capabilities.chooseModel&&capabilities.choosePersonality&&capabilities.canPair&&window.CortanaDisplay?.page!=='setup')window.CortanaPages?.open('setup');
  $('phoneSection').hidden=!capabilities.canPair;
  if(capabilities.canPair&&capabilities.phoneReady&&!shownQR){$('phoneQR').src='/api/phone-qr';$('phoneQR').hidden=false;shownQR=true;$('phoneHelp').textContent='Scan with your phone camera. Keep the PC launcher open.';}
  if(capabilities.canPair&&!capabilities.phoneReady){$('phoneQR').hidden=true;shownQR=false;$('phoneHelp').textContent=capabilities.error||'Preparing your secure phone connection...';}
 }catch{$('connectionNote').textContent='Connection lost. Keep the Cortana app open on your PC.';$('statusText').textContent='OFFLINE';capabilities.ai=false;capabilities.transcription=false;}
 finally{statusBusy=false;}
}
refreshStatus();setInterval(refreshStatus,4000);
addEventListener('keydown',e=>{if(e.key==='Escape')stop();});
addEventListener('pagehide',stop);
// An existing assistant can provide replies using this API without replacing the UI.
function note(text,error=false){chatLog.push({role:'system',text,error});chatChanged();}
function stopTask(id){api('/api/cancel',{request_id:'task_'+id}).catch(()=>{});}   // ends a mouse/keyboard task between steps
window.Cortana={stopTask,attachImage(b64){if(pendingImages.length>=2)throw Error('Two pictures at most per question.');pendingImages.push(b64);return pendingImages.length;},confirm:resolveConfirm,get deep(){return deepThinking;},set deep(v){deepThinking=!!v;savePreference('deep',deepThinking?'1':'0');},applyMode,restoreConversation,clearConversation(){stop();history=[];chatLog.length=0;chatChanged();},speak,stop,send,api,get state(){return state;},get wake(){return wake.on;},setWake,get chat(){return chatLog;},showScreen:md=>showScreen(md),
 note};

/* ---- Timer and reminder alerts (checked with every status poll) ---- */
const announced=new Set();
function chime(){
 try{const t=audioContext.currentTime;for(const [f,at] of [[880,0],[1320,.18],[1760,.36]]){const o=audioContext.createOscillator(),g=audioContext.createGain();o.frequency.value=f;o.type='sine';
  g.gain.setValueAtTime(0,t+at);g.gain.linearRampToValueAtTime(.18,t+at+.02);g.gain.exponentialRampToValueAtTime(.001,t+at+.5);o.connect(g).connect(audioContext.destination);o.start(t+at);o.stop(t+at+.55);}}catch{}
}
async function announceAlerts(alerts){
 const next=alerts.find(a=>!announced.has(a.id+':'+a.due));
 if(!next||state!=='idle')return;
 const key=next.id+':'+next.due,alertRequest=requestId;announced.add(key);
 try{await unlockAudio();}catch{announced.delete(key);return;}
 if(state!=='idle'||requestId!==alertRequest){announced.delete(key);return;}
 chime();
 setTimeout(()=>{
  if(state!=='idle'||requestId!==alertRequest){announced.delete(key);return;}
  api('/api/objectives',{action:'ack',id:next.id}).then(()=>document.dispatchEvent(new CustomEvent('cortana:refresh',{detail:{what:'objectives'}}))).catch(()=>{});
  if(next.kind==='briefing'&&window.CortanaPages?.readBriefing){window.CortanaPages.readBriefing();return;}   // daily briefing: open it and read it out
  speak(next.kind==='timer'?`Chief, your ${next.text.replace(/\s*timer$/i,'')} timer is done.`:next.kind==='notice'?next.text:`Reminder, Chief: ${next.text}.`);
 },700);
}

/* ---- "Hey Cortana" wake word: listens locally for speech, transcribes short bursts on this PC, reacts to the name ---- */
async function setWake(on){
 if(on===wake.on)return true;
 if(!on){wake.on=false;wake.node&&(wake.node.port.onmessage=null);wake.input?.disconnect();wake.node?.disconnect();wake.stream?.getTracks().forEach(t=>t.stop());Object.assign(wake,{stream:null,input:null,node:null,pending:null});savePreference('wake','0');if(state==='idle')setState('idle',idleLabel());return true;}
 if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia){error('The wake word needs the secure phone link or this PC.');return false;}
 try{
  await unlockAudio();
  wake.stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
  if(!workletReady){await audioContext.audioWorklet.addModule('./mic-worklet.js');workletReady=true;}
  wake.input=audioContext.createMediaStreamSource(wake.stream);wake.node=new AudioWorkletNode(audioContext,'cortana-capture');
  // Speech detection adapts to the room: thresholds follow the background noise level (quiet mics and noisy rooms both work).
  let chunks=[],pre=[],talking=false,lastVoice=0,startedAt=0,floor=.006;
  const check=audio=>{   // the PC transcribes the burst (with a hint for the name) and decides if it was "Hey Cortana"
   wake.busy=true;
   api('/api/transcribe',{audio:encodeWav(audio,audioContext.sampleRate),wake:true,interrupt:state==='speaking'||state==='thinking'}).then(r=>{
    if(!wake.on||!r.wake||recording||state==='listening')return;
    const norm=t=>t.toLowerCase().replace(/[^a-z0-9 ]/g,'').trim();
    if(state==='speaking'&&norm(playingText).includes(norm(r.text)))return;
    stop();
    if(/^(stop|quiet|cancel|enough|never mind)[.! ]*$/i.test(r.rest.trim()))return;
    wake.pending=null;
    if(r.rest.split(/\s+/).filter(Boolean).length>=2)send(r.rest);else{chime();listen();}
   }).catch(()=>{}).finally(()=>{wake.busy=false;const next=wake.pending;wake.pending=null;if(next&&wake.on&&state!=='listening'&&!recording)check(next);});
  };
  wake.node.port.onmessage=e=>{
   const c=e.data,now=performance.now();let rms=0;for(const v of c)rms+=v*v;rms=Math.sqrt(rms/c.length);
   if(state==='listening'||recording){chunks=[];talking=false;pre=[];wake.pending=null;return;}   // echo-cancelled wake audio stays active during playback
   const start=Math.max(.012,floor*3),keep=Math.max(.009,floor*2);
   if(!talking){
    if(rms<start)floor=floor*.97+rms*.03;
    pre.push(c);if(pre.length>8)pre.shift();if(rms>start){talking=true;startedAt=now;lastVoice=now;chunks=[...pre];}return;}
   chunks.push(c);if(rms>keep)lastVoice=now;
   if(now-lastVoice>700||now-startedAt>7000){
    const audio=chunks;chunks=[];pre=[];talking=false;
    if(now-startedAt<400)return;
    if(wake.busy)wake.pending=audio;else check(audio);   // keep the latest burst instead of dropping it while busy
   }
  };
  wake.input.connect(wake.node);wake.node.connect(audioContext.destination);
  wake.on=true;savePreference('wake','1');if(state==='idle')setState('idle',idleLabel());return true;
 }catch(e){error(e.name==='NotAllowedError'?'Microphone access was blocked, so the wake word is off.':'Could not start the wake word.');return false;}
}
if(preference('wake','0')==='1')addEventListener('pointerdown',()=>setWake(true),{once:true});   // browsers need a tap before using the mic

/* ---- Cortana display: a holographic panel for code, tables and steps (instead of squashing them into the transcript) ---- */
const holoEsc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function holoInline(t){
 return t.split(/(`[^`]+`)/g).map(p=>p.length>1&&p.startsWith('`')&&p.endsWith('`')?'<code>'+holoEsc(p.slice(1,-1))+'</code>'
  :holoEsc(p).replace(/\[([^\]]+)\]\((https:\/\/[^\s)"'<>]+)\)/g,'<a class="holo-link" href="$2" target="_blank" rel="noopener noreferrer">$1</a>')   // https only; text already escaped
   .replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/(^|[^*])\*([^*\s][^*]*)\*/g,'$1<em>$2</em>')).join('');
}
const HOLO_KEYWORDS=new Set('def class return if elif else for while in import from as with try except finally raise pass break continue lambda yield and or not is None True False async await const let var function new this null true false switch case default public private static void int string bool'.split(' '));
function holoHighlight(code){
 const re=/(#[^\n]*|\/\/[^\n]*)|("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_]\w*)/g;
 let html='',last=0,m;
 while((m=re.exec(code))){
  html+=holoEsc(code.slice(last,m.index));
  if(m[1])html+='<span class="tk-c">'+holoEsc(m[1])+'</span>';
  else if(m[2])html+='<span class="tk-s">'+holoEsc(m[2])+'</span>';
  else if(m[3])html+='<span class="tk-n">'+holoEsc(m[3])+'</span>';
  else if(HOLO_KEYWORDS.has(m[4]))html+='<span class="tk-k">'+holoEsc(m[4])+'</span>';
  else if(code[re.lastIndex]==='(')html+='<span class="tk-f">'+holoEsc(m[4])+'</span>';
  else html+=holoEsc(m[4]);
  last=re.lastIndex;
 }
 return html+holoEsc(code.slice(last));
}
function holoMarkdown(md){
 const lines=md.replace(/\r/g,'').split('\n'),isRow=l=>/^\s*\|.*\|\s*$/.test(l),cells=r=>r.trim().replace(/^\||\|$/g,'').split('|').map(c=>c.trim());
 const listItem=/^\s*([-*+]|\d+[.)])\s+/,blockStart=/^\s*(```|#{1,4}\s|[-*+]\s|\d+[.)]\s)/;
 let html='',title='',i=0,m;
 while(i<lines.length){
  const l=lines[i];
  if((m=l.match(/^\s*```\s*([\w+#.-]*)/))){
   const lang=m[1],buf=[];i++;
   while(i<lines.length&&!/^\s*```/.test(lines[i]))buf.push(lines[i++]);
   i++;
   html+='<div class="holo-code"><div class="holo-code-bar"><span>'+holoEsc(lang||'code')+'</span><button type="button" class="holo-copy">Copy</button></div><pre><code>'+holoHighlight(buf.join('\n'))+'</code></pre></div>';
   continue;
  }
  if((m=l.match(/^(#{1,4})\s+(.*)/))){
   if(!title&&m[1].length===1){title=m[2].trim();i++;continue;}
   const level=Math.min(4,m[1].length+1);html+='<h'+level+'>'+holoInline(m[2])+'</h'+level+'>';i++;continue;
  }
  if(isRow(l)&&i+1<lines.length&&/^\s*\|?\s*:?-{2,}/.test(lines[i+1])){
   const head=cells(l),rows=[];i+=2;
   while(i<lines.length&&isRow(lines[i]))rows.push(cells(lines[i++]));
   html+='<div class="holo-table"><table><thead><tr>'+head.map(c=>'<th>'+holoInline(c)+'</th>').join('')+'</tr></thead><tbody>'
    +rows.map(r=>'<tr>'+r.map(c=>'<td>'+holoInline(c)+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
   continue;
  }
  if(listItem.test(l)){
   const tag=/^\s*\d/.test(l)?'ol':'ul',items=[];
   while(i<lines.length&&listItem.test(lines[i]))items.push(lines[i++].replace(listItem,''));
   html+='<'+tag+'>'+items.map(t=>'<li>'+holoInline(t)+'</li>').join('')+'</'+tag+'>';continue;
  }
  if(!l.trim()){i++;continue;}
  const para=[];
  while(i<lines.length&&lines[i].trim()&&!blockStart.test(lines[i])&&!isRow(lines[i]))para.push(lines[i++]);
  if(para.length)html+='<p>'+holoInline(para.join(' '))+'</p>';else{html+='<p>'+holoInline(l)+'</p>';i++;}
 }
 return {title:title||'Display',html};
}
const holo=document.createElement('section');
holo.id='holoPanel';holo.className='holo-panel';holo.hidden=true;
holo.setAttribute('role','dialog');holo.setAttribute('aria-modal','false');holo.setAttribute('aria-labelledby','holoTitle');
holo.innerHTML='<div class="holo-head"><div><small id="holoLabel">CORTANA // DISPLAY</small><h2 id="holoTitle"></h2></div><button type="button" class="holo-close" aria-label="Close display">&times;</button></div><div class="holo-body" id="holoBody"></div>';
document.body.appendChild(holo);
const holoReopen=document.createElement('button');
holoReopen.type='button';holoReopen.className='holo-reopen';holoReopen.hidden=true;holoReopen.textContent='◆ SHOW DISPLAY';
out.insertAdjacentElement('afterend',holoReopen);
let holoLast='';
let holoPage=null;
function showPanel(title,html,label='CORTANA // DISPLAY',page=null){
 const reopening=!holo.hidden&&holoPage===page&&page;
 $('holoLabel').textContent=label;$('holoTitle').textContent=title;$('holoBody').innerHTML=html;if(!reopening)$('holoBody').scrollTop=0;
 holoPage=page;holo.hidden=false;holoReopen.hidden=true;placeHolo();
 if(!reopening){holo.classList.remove('holo-open');void holo.offsetWidth;holo.classList.add('holo-open');}
}
// Keep the panel above the bottom navigation so pages can be switched while it is open.
function placeHolo(){
 const nav=document.querySelector('.nav-wrap');if(!nav)return;
 const top=nav.getBoundingClientRect().top,gap=8;
 holo.style.bottom=Math.max(8,innerHeight-top+gap)+'px';
 holo.style.maxHeight=Math.max(220,Math.min(innerHeight*.56,top-gap-innerHeight*.40))+'px';   // keep her face visible above it
}
addEventListener('resize',()=>{if(!holo.hidden)placeHolo();});
function showScreen(md){holoLast=md;const r=holoMarkdown(md);showPanel(r.title,r.html);}
function hideScreen(){if(holo.hidden)return;holo.hidden=true;holoPage=null;holoReopen.hidden=!holoLast;}
holo.querySelector('.holo-close').addEventListener('click',hideScreen);
holoReopen.addEventListener('click',()=>holoLast&&showScreen(holoLast));
document.addEventListener('keydown',e=>{if(e.key==='Escape')hideScreen();});
holo.addEventListener('click',async e=>{
 const b=e.target.closest('.holo-copy');if(!b)return;
 const code=b.closest('.holo-code').querySelector('code').textContent;
 try{await navigator.clipboard.writeText(code);b.textContent='Copied';}
 catch{const r=document.createRange();r.selectNodeContents(b.closest('.holo-code').querySelector('code'));const s=getSelection();s.removeAllRanges();s.addRange(r);b.textContent='Selected';}
 setTimeout(()=>{b.textContent='Copy';},1600);
});
window.CortanaDisplay={show:showScreen,hide:hideScreen,render:holoMarkdown,panel:showPanel,esc:holoEsc,get page(){return holo.hidden?null:holoPage;},body:()=>$('holoBody')};

function applyMode(mode,preview=false){
 if(preview)modePreviewUntil=performance.now()+20000;
 if(!['normal','expressive'].includes(mode))return;
 $('character').value=mode==='expressive'?'1.8':'1.3';applySettings();
}
async function restoreConversation(){
 if(restored)return;
 if(restorePromise)return restorePromise;
 restorePromise=(async()=>{
  try{
   const r=await fetch('/api/conversation');if(!r.ok)throw Error('History unavailable');
   const data=await r.json();history=data.messages.slice(-18).map(({role,content})=>({role,content}));
   chatLog.splice(0,chatLog.length,...data.messages.map(m=>{const [text,screen]=m.content.split('[[SCREEN]]');return {role:m.role,text:text.trim(),screen:screen?.trim()};}));
   restored=true;chatChanged();
  }catch{}finally{restorePromise=null;}
 })();return restorePromise;
}
restoreConversation();
