/* AI abilities and concrete review. All model/service text is escaped. */
const C=window.Cortana,D=window.CortanaDisplay,esc=D.esc;
let current=null,refreshTimer=null;
const get=async()=>{const r=await fetch('/api/agent');if(!r.ok)throw Error('Could not load abilities.');return r.json();};
const post=data=>C.api('/api/agent',data);
const button=(action,label,id='')=>`<button type="button" class="pg-btn" data-agent="${action}" data-id="${esc(id)}">${esc(label)}</button>`;
const downloads=items=>items.map(a=>`<div class="pg-card"><a href="/api/artifacts/${esc(a.id)}" download>${esc(a.name)}</a> · ${Math.ceil(a.bytes/1024)} KB ${button('target','Use this',a.id)}</div>`).join('');
async function open(page='abilities'){
 current=page;
 try{
  const s=await get();if(current!==page)return;
  let html=`<div class="pg-actions">${button('abilities','Abilities')}${button('activity','Activity')}</div>`;
  if(page==='activity'){
   html+='<h3>Awaiting your review</h3>'+(s.approvals.map(a=>`<section class="pg-card"><strong>${esc(a.reason)}</strong><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(JSON.stringify(a.context,null,2))}</pre>${button('approve','Approve',a.id)} ${button('deny','Deny',a.id)}</section>`).join('')||'<p class="pg-muted">No actions waiting.</p>');
   html+='<h3>Missions</h3>'+s.missions.map(m=>`<div class="pg-card"><strong>${esc(m.title)}</strong> · ${esc(m.state)}<ol>${m.steps.map(t=>`<li>${esc(t)}</li>`).join('')}</ol>${m.evidence.map(t=>`<p>${esc(t)}</p>`).join('')}</div>`).join('');
   html+='<h3>Files</h3>'+downloads(s.artifacts)+'<h3>Recent actions</h3>'+s.activity.map(a=>`<p>${esc(a.name)} · ${esc(a.status)} ${a.undo?button('undo','Undo',a.undo):''}</p>`).join('');
   html+='<h3>Scheduled goals</h3>'+s.jobs.map(j=>`<div class="pg-card"><strong>${esc(j.goal)}</strong><p>${esc(j.state)} · ${j.enabled?'enabled':'paused'}</p>${j.last_reply?`<p>${esc(j.last_reply)}</p>`:''}${button(j.enabled?'pause':'resume',j.enabled?'Pause':'Resume',j.id)} ${button('remove-job','Remove',j.id)}</div>`).join('');
  }else{
   html+='<p>Speak naturally. Qwen chooses and combines tools from the conversation. No command phrases to memorise.</p><p class="pg-muted">Files and undo · Word/PDF · CSV/XLSX and charts · isolated Python · browser · Windows apps · diagnostics · images/scanned PDFs/video · email, calendar, music and smart home · scheduled goals · MCP plugins.</p>';
   html+=`<label>Reasoning<select id="agentReasoning"><option value="fast"${s.settings.reasoning==='fast'?' selected':''}>Fast</option><option value="deep"${s.settings.reasoning==='deep'?' selected':''}>Deep — slower, more thinking</option></select></label><label>Context rated for this PC<select id="agentContext">${s.settings.context_choices.map(n=>`<option value="${n}"${n===s.settings.context_tokens?' selected':''}>${n.toLocaleString()} tokens</option>`).join('')}</select></label>${button('preferences','Save reasoning settings')}`;
   html+='<h3>Approved folders</h3><p>'+s.roots.map(n=>esc(n)+(s.canConfigure&&n!=='Workspace'?' '+button('remove-root','Remove',n):'')).join(' · ')+'</p><p class="pg-muted">New deliverables go in the Cortana workspace. Add other work folders on the PC. File changes have undo; undo refuses to overwrite newer edits.</p>';
   if(s.canConfigure)html+=`<label>Folder label<input id="agentRootName" placeholder="Coursework" maxlength="31"></label><label>Folder path<input id="agentRootPath" placeholder="C:\\Users\\…\\Documents\\Coursework"></label>${button('root','Add folder')}`;
   html+='<h3>Connections</h3>'+s.connections.map(c=>`<p>${esc(c.name)} · ${esc(c.type)} ${s.canConfigure?button('remove-connection','Disconnect',c.name):''}</p>`).join('');
   if(s.canConfigure)html+=`<details><summary>Connect a service or MCP plugin</summary><p class="pg-muted">Enter settings here on the PC. Secrets are never returned to the page. MCP tools can provide calendars, music or other services. This client supports Streamable HTTP 2025-11-25. Email accepts provider app passwords or an existing OAuth access token; automatic OAuth refresh is not included.</p><label>Name<input id="agentConnectionName" maxlength="40" placeholder="calendar"></label><label>Connection settings (JSON)<textarea id="agentConnectionConfig" rows="7" spellcheck="false" autocomplete="off" placeholder='{"type":"mcp","url":"http://localhost:8000/mcp","token":"…"}'></textarea></label><p class="pg-muted">CalDAV: type caldav, url (calendar collection), username, password or token. Home Assistant: type home_assistant, url, token. Email: type email, imap, smtp, username, password (or oauth_token), smtp_port 465/587. MCP read_tools may list explicitly trusted read-only tools; other calls need review.</p>${button('connection','Save connection')}</details>`;
   html+='<h3>Execution setup</h3><p class="pg-muted">Browser: installed Microsoft Edge on Windows. Python: Docker Desktop in Linux container mode, with python:3.12-slim pulled. Video frames: FFmpeg on PATH. Email, calendar, music and home services require your own configured account or server. Scheduled jobs run while the launcher is open.</p><label>Add images, scans or other input files<input id="agentUpload" type="file" multiple></label>'+button('upload','Upload selected files');
  }
  html+='<p id="agentMessage" class="pg-muted" role="status"></p>';
  D.panel(page==='activity'?'Activity':'Abilities',html,'CORTANA // OPERATIONS',page);
 }catch(e){if(current===page)D.panel('Abilities',`<p>${esc(e.message)}</p>`,'CORTANA // OPERATIONS',page);}
}
D.body().addEventListener('click',async event=>{
 const el=event.target.closest('[data-agent]');if(!el)return;
 const action=el.dataset.agent,id=el.dataset.id,v=id=>document.getElementById(id)?.value;
 if(action==='abilities'||action==='activity')return open(action);
 el.disabled=true;const message=document.getElementById('agentMessage');if(message)message.textContent='Working…';
 try{
  if(action==='preferences')await post({action,reasoning:v('agentReasoning'),context_tokens:Number(v('agentContext'))});
  else if(action==='root')await post({action,name:v('agentRootName'),path:v('agentRootPath')});
  else if(action==='connection'){await post({action,name:v('agentConnectionName'),config:JSON.parse(v('agentConnectionConfig'))});document.getElementById('agentConnectionConfig').value='';}
  else if(action==='remove-root')await post({action:'root',name:id,remove:true});
  else if(action==='remove-connection')await post({action:'connection',name:id,remove:true});
  else if(action==='approve'||action==='deny'){const result=await post({action:'review',id,allow:action==='approve'});if(result.error)throw Error(result.error);}
  else if(action==='undo')await post({action,id});
  else if(action==='target'){await post({action,id});if(message)message.textContent='Current file selected. Refer to it as “this file” in chat.';return;}
  else if(['pause','resume','remove-job'].includes(action))await post({action:'job',job_action:action==='remove-job'?'remove':action,id});
  else if(action==='upload'){
   for(const file of document.getElementById('agentUpload').files){
    if(file.size>32*1024*1024)throw Error('Choose files under 32 MB.');
    const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});
    await C.api('/api/agent-upload',{name:file.name,data});
   }
   return open('activity');
  }
  await open(current);
 }catch(e){if(message)message.textContent=e.message;}finally{el.disabled=false;}
});
const original=window.CortanaPages.open;
window.CortanaPages.navigation=0;
window.CortanaPages.open=target=>{window.CortanaPages.navigation++;if(target==='abilities'||target==='activity'){open(target);return true;}current=null;return original(target);};
document.addEventListener('cortana:activity',event=>{
 if(event.detail.type==='approval'&&D.page!=='chat')open('activity');
 else if(D.page==='activity'){clearTimeout(refreshTimer);refreshTimer=setTimeout(()=>open('activity'),500);}
});
