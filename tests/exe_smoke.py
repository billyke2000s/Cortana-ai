"""Smoke test for the built Cortana.exe (run by the release workflow on Windows before publishing).

Start the exe first:  Cortana.exe --headless --no-open --no-tunnel --port 8777
Then:                 python tests/exe_smoke.py http://127.0.0.1:8777
Checks that the bundle starts, serves the page, the 3D model and the scripts, detects hardware without crashing,
and reads a PDF (proves pypdf and files.py are bundled). It does not wait for the AI download.
"""
import base64, json, sys, time, urllib.request

URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8777'

def call(path, body=None):
    req = urllib.request.Request(URL + path, json.dumps(body).encode() if body is not None else None,
                                 {'Content-Type': 'application/json'} if body is not None else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.read()

def make_pdf(pages):
    objs = ['<< /Type /Catalog /Pages 2 0 R >>', None, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    kids = []
    for text in pages:
        stream = f'BT /F1 12 Tf 72 720 Td ({text}) Tj ET'
        objs.append(f'<< /Length {len(stream)} >>\nstream\n{stream}\nendstream')
        objs.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {len(objs)} 0 R >>')
        kids.append(f'{len(objs)} 0 R')
    objs[1] = f'<< /Type /Pages /Kids [{" ".join(kids)}] /Count {len(kids)} >>'
    out, offsets = b'%PDF-1.4\n', []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out)); out += f'{i} 0 obj\n{o}\nendobj\n'.encode()
    xref = len(out)
    out += f'xref\n0 {len(objs) + 1}\n0000000000 65535 f \n'.encode() + b''.join(f'{o:010d} 00000 n \n'.encode() for o in offsets)
    return out + f'trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()

for _ in range(90):
    try:
        status, raw = call('/api/status'); break
    except Exception:
        time.sleep(1)
else:
    sys.exit('Cortana.exe did not start its server within 90 s')
print('status:', json.loads(raw)['status'])
checks = []
status, page = call('/'); checks.append(('page', status == 200 and b'CORTANA' in page.upper()))
for path in ('/app.js', '/pages.js', '/avatar.js', '/vendor/three.module.js', '/vendor/GLTFLoader.js'):
    try:
        checks.append((path, call(path)[0] == 200))
    except Exception as e:
        checks.append((path + f' ({e})', False))
status, glb = call('/assets/cortana.glb'); checks.append((f'3D model {len(glb):,} bytes', status == 200 and len(glb) > 5_000_000))
models = json.loads(call('/api/models')[1]); print('hardware:', models['hardware'], '| recommended:', models['recommended'])
checks.append(('model list', len(models['models']) >= 6))
pdf = base64.b64encode(make_pdf(['Smoke test brief', 'Deadline 5 March'])).decode()
added = json.loads(call('/api/documents', {'action': 'add', 'name': 'smoke.pdf', 'data': pdf})[1])['added']
checks.append((f"PDF read: {added}", added['pages'] == 2))
for name, ok in checks:
    print('OK ' if ok else 'BAD', name)
sys.exit(0 if all(ok for _, ok in checks) else 1)
