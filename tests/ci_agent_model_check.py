"""Real Qwen semantic routing through the actual runtime; no user-phrase router.
External side effects are fixtures. File creation is real. Separate checks exercise browser/Docker themselves.
"""
import json,os,sys,tempfile,urllib.request
from unittest.mock import patch
sys.path.insert(0,'app');os.environ.setdefault('CORTANA_DATA_DIR',tempfile.mkdtemp())
from runtime import Runtime
import tools
r=Runtime();r.model=sys.argv[1];r.ai_ready=True
original=urllib.request.urlopen
def cpu(request,*args,**kwargs):
    if getattr(request,'full_url','').startswith(r.ollama_url+'/api/'):kwargs['timeout']=900
    return original(request,*args,**kwargs)
cases=[
 ('Jot down blue team ready in a text file called readiness.txt.','manage_files',lambda a:a.get('action')=='write'),
 ('Put Status: systems online into an actual Word file I can download.','create_document',lambda a:a.get('format')=='docx'),
 ('Take me to https://example.com and tell me its heading.','browser',lambda a:a.get('action')=='navigate'),
 ('Is my machine running low on disk space? Check it.','diagnostics',lambda a:a.get('action')=='summary'),
 ('Look through the mail account I connected and tell me what came in.','connected_service',lambda a:a.get('action') in ('list','email_list','tools')),
 ('Do I need a brolly in London today? Check the forecast.','get_weather',lambda a:'london' in a.get('place','').lower()),
]
for ask,want,check in cases:
    seen=[];actual=r.agent.run
    def routed(name,args,groups,approved=False):
        if name==want:
            seen.append(args)
            if name in ('browser','connected_service'):return {'fixture':True,'result':'Requested action observed; external service not contacted.'},None
        return actual(name,args,groups,approved)
    old=tools.weather
    def weather(place,home):seen.append({'place':place});return {'error':'Forecast fixture unavailable; do not invent data.'}
    with patch.object(r.agent,'run',routed),patch.object(tools,'weather',weather),patch('urllib.request.urlopen',cpu):
        events=list(r.chat_stream([{'role':'user','content':ask}]))
    assert r.model==sys.argv[1],r.model
    assert seen and any(check(a) for a in seen),(ask,seen,events)
    assert events[-1]['type']=='done',events
    print(json.dumps({'model':r.model,'ask':ask,'tool':want,'arguments':seen,'passed':True}),flush=True)
r.close();r.store.close()
