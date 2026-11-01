"""Actual Linux Docker boundary and output test, invoked on the Linux CI runner."""
import os,sys,tempfile
sys.path[:0]=['app'];os.environ.setdefault('CORTANA_DATA_DIR',tempfile.mkdtemp())
from runtime import Runtime
r=Runtime()
try:
    result=r.agent.workspace.code({'code':"""import pathlib,socket
assert not pathlib.Path('/host').exists()
try:
 pathlib.Path('/input/tamper').write_text('no')
 raise AssertionError('input was writable')
except OSError: pass
try:
 socket.create_connection(('1.1.1.1',443),timeout=1)
 raise AssertionError('network escaped')
except OSError: pass
pathlib.Path('/output/result.txt').write_text(str(6*7))
print('verified 42')
"""})
    assert result['verified'],result
    assert 'verified 42' in result['stdout'],result
    assert result['artifacts'],result
    output=r.store.agent_get(result['artifacts'][0]['id'],'artifact')
    from pathlib import Path
    assert Path(output['path']).read_text()=='42',result
    print('DOCKER: read-only input, no network, verified output collection PASS',flush=True)
finally:r.close();r.store.close()
