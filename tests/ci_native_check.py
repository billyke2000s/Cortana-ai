"""Windows native keyword detector and notification process; synthetic speech, no microphone."""
import base64
import os
import sys
import tempfile
sys.path.insert(0,'app');os.environ.setdefault('CORTANA_DATA_DIR',tempfile.mkdtemp())
from runtime import Runtime
from companion import notify
r=Runtime(print);r.neural.prepare_wake()
for phrase,expected in [('Hey Cortana, what time is it?',True),('The curtains are open today.',False),('Hey Montana, how are you?',False)]:
    speech=r.voice.windows(phrase);found=r.neural.detect(base64.b64decode(speech['audio']))
    print('KWS',repr(phrase),found,flush=True);assert found==expected,(phrase,found,expected)
assert notify('Cortana release check: reminder notification.')
print('WINDOWS_NOTIFICATION_PROCESS_OK (visual delivery needs a desktop)',flush=True)
r.close();r.store.close()
