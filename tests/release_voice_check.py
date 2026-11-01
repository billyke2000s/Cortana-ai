"""Exercise the packaged reference voice before publishing a Windows build."""
import base64
import io
import json
import sys
import time
import urllib.request
import urllib.error
import wave
URL=sys.argv[1]
def call(path,body=None):
    req=urllib.request.Request(URL+path,json.dumps(body).encode() if body else None,{'Content-Type':'application/json'} if body else {})
    with urllib.request.urlopen(req,timeout=300) as r:return json.load(r)
for _ in range(180):
    status=call('/api/status')
    if 'ready' in status['lipSync'].lower() and 'ready' in status['wakeDetector'].lower():break
    time.sleep(1)
else:raise RuntimeError('Packaged alignment / keyword spotter did not prepare: '+str(status))
call('/api/settings',{'voice_engine':'zipvoice'});start=time.perf_counter()
speech=call('/api/speech',{'text':'I am ready when you are, Chief. What is our next move?','request_id':'release_smoke'})
assert 'ZipVoice' in speech['voice'],speech['voice']
with wave.open(io.BytesIO(base64.b64decode(speech['audio']))) as wav:
    duration=wav.getnframes()/wav.getframerate()
    assert wav.getnchannels()==1 and wav.getframerate()==24000 and duration>1
assert len(speech['visemes'])>=4,speech['visemes']
print('BUILT_EXE_REFERENCE_VOICE_OK',round(duration,2),'seconds,',len(speech['visemes']),'cues,',round(time.perf_counter()-start,2),'seconds render')
call('/api/cancel',{'request_id':'cancelled_smoke'})
try:call('/api/speech',{'text':'This must never generate.','request_id':'cancelled_smoke'})
except urllib.error.HTTPError as e:assert e.code==503
else:raise AssertionError('Cancelled speech generated')
call('/api/settings',{'voice_engine':'windows'})
speech=call('/api/speech',{'text':'Hey Cortana, what time is it?','request_id':'windows_smoke'})
assert speech['audio'] and len(speech['visemes'])>0
print('BUILT_EXE_WINDOWS_VOICE_OK')
