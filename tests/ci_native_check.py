"""Windows notification process (the keyword detector check was dropped with the detector in 1.6.1, D-037)."""
import os
import sys
import tempfile
sys.path.insert(0,'app');os.environ.setdefault('CORTANA_DATA_DIR',tempfile.mkdtemp())
from runtime import Runtime
from companion import notify
r=Runtime(print)
assert notify('Cortana release check: reminder notification.')
print('WINDOWS_NOTIFICATION_PROCESS_OK (visual delivery needs a desktop)',flush=True)
r.close();r.store.close()
