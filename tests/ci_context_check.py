"""Real 4B/9B regression with relevant memories and older conversation excerpts."""
import json
import os
import sys
import tempfile
sys.path.insert(0,'app');os.environ.setdefault('CORTANA_DATA_DIR',tempfile.mkdtemp())
from runtime import Runtime
from store import Store
r=Runtime();r.store.close();r.store=Store(':memory:');r.model=sys.argv[1];r.ai_ready=True
r.store.add_fact('The user has a dog called Rex')
for i in range(50):r.store.add_fact(f'The user enjoys game number {i}')
for i in range(24):r.store.log_message('user' if i%2==0 else 'assistant','We discussed planning a study session.')
checks=[('Set a timer for 10 minutes for the pasta.','set_timer'),('Remember that my favourite colour is cyan.','remember'),
 ('How do I build a table in Python?','screen'),('Remind me to call mum at 6pm.','set_reminder'),('Tell me a joke.','reply'),('What is my dog called?','Rex')]
for ask,expect in checks:
    events=list(r.chat_stream([{'role':'user','content':ask}]))
    assert events and events[-1]['type']=='done',events
    if expect in ('set_timer','remember','set_reminder'):assert any(e.get('name')==expect for e in events),events
    elif expect=='screen':assert any(e['type']=='screen' for e in events),events
    elif expect=='Rex':assert 'rex' in events[-1]['reply'].lower(),events
    else:assert len(events[-1]['reply'])>10,events
    print(json.dumps({'model':r.model,'ask':ask,'expected':expect,'passed':True,'latency':r.jobs.snapshot()}),flush=True)
r.close();r.store.close()
