"""Cortana's access to the user's own PC: documents she can read, file search, the screen and the clipboard.

Safety rules (see AGENTS.md §4 and SECURITY.md):
- Nothing here runs model-provided text as a command. The screenshot/clipboard PowerShell scripts are fixed strings.
- open_file() only opens files that find_files() just returned (by number), never executables or shortcuts.
- Screenshots and clipboard images go only to the local Ollama model and are deleted straight away.
"""
import base64, math, os, re, subprocess, tempfile, time, zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

HIDDEN = 0x08000000 if os.name == 'nt' else 0
DOC_TYPES = {'.pdf', '.docx', '.pptx', '.txt', '.md', '.csv', '.json', '.py', '.js', '.html', '.htm', '.xml', '.log', '.rtf'}
MAX_FILE_BYTES = 40_000_000
MAX_DOC_CHARS = 2_000_000
CHUNK = 900

# ------------------------------------------------------------------ text extraction
def _xml_text(data, para_tags, text_tag):
    root = ET.fromstring(data)
    out = []
    for p in root.iter():
        if p.tag.split('}')[-1] in para_tags:
            line = ''.join(t.text or '' for t in p.iter() if t.tag.split('}')[-1] == text_tag)
            if line.strip():
                out.append(line.strip())
    return out

def extract_text(name, data):
    """Return (text, pages) from file bytes. Pages are marked '[page N]' so answers can cite them."""
    ext = Path(name).suffix.lower()
    if ext not in DOC_TYPES:
        raise ValueError(f'Cortana can read PDF, Word (.docx), PowerPoint (.pptx) and text files, not {ext or "this type"}.')
    if len(data) > MAX_FILE_BYTES:
        raise ValueError('That file is too large (over 40 MB).')
    if ext == '.pdf':
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt('')
            except Exception:
                raise ValueError('That PDF is password-protected.')
        parts = []
        for i, page in enumerate(reader.pages[:600], 1):
            try:
                t = page.extract_text() or ''
            except Exception:
                t = ''
            if t.strip():
                parts.append(f'[page {i}]\n{t.strip()}')
        text = '\n\n'.join(parts)
        if not text.strip():
            raise ValueError('That PDF has no readable text (it may be scanned images).')
        return text[:MAX_DOC_CHARS], len(reader.pages)
    if ext in ('.docx', '.pptx'):
        try:
            z = zipfile.ZipFile(__import__('io').BytesIO(data))
        except zipfile.BadZipFile:
            raise ValueError('That file is damaged or not a real Word/PowerPoint file.')
        if ext == '.docx':
            lines = _xml_text(z.read('word/document.xml'), {'p'}, 't')
            return '\n'.join(lines)[:MAX_DOC_CHARS], None
        slides = sorted((n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', n)),
                        key=lambda n: int(re.search(r'\d+', n).group()))
        parts = [f'[slide {i}]\n' + '\n'.join(_xml_text(z.read(n), {'p'}, 't')) for i, n in enumerate(slides, 1)]
        return '\n\n'.join(parts)[:MAX_DOC_CHARS], len(slides)
    text = data.decode('utf-8-sig', 'replace')
    if ext in ('.html', '.htm', '.xml'):
        text = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', text)
        text = re.sub(r'<[^>]+>', ' ', text)
    if ext == '.rtf':
        text = re.sub(r'\\[a-z]+-?\d* ?|[{}]', '', text)
    return text[:MAX_DOC_CHARS], None

def chunks(text):
    """Split into ~900-character pieces on paragraph boundaries. Each piece is labelled with the page it starts on."""
    out, cur, page, cur_page = [], '', '', ''
    for para in re.split(r'\n\s*\n|\n(?=\[(?:page|slide) \d+\])', text):
        para = para.strip()
        if not para:
            continue
        m = re.match(r'\[(page|slide) (\d+)\]', para)
        if m:
            if cur:   # a new page starts a new piece, so every piece has one page
                out.append((cur_page, cur.strip())); cur = ''
            page = f'{m.group(1)} {m.group(2)}'
        if not cur:
            cur_page = page
        while len(para) > CHUNK * 1.5:   # very long paragraphs: split at a line (keeps table rows whole), else a sentence or space
            cut = para.rfind('\n', 0, CHUNK)
            if cut <= CHUNK // 2:
                cut = max(para.rfind('. ', 0, CHUNK), para.rfind(' ', 0, CHUNK))
            cut = cut if cut > CHUNK // 2 else CHUNK
            out.append((cur_page, (cur + ' ' + para[:cut + 1]).strip())); cur = ''; cur_page = page
            para = para[cut + 1:].strip()
        if len(cur) + len(para) > CHUNK and cur:
            out.append((cur_page, cur.strip())); cur = ''; cur_page = page
        cur += ('\n' if cur else '') + para
    if cur.strip():
        out.append((cur_page, cur.strip()))
    return out

# ------------------------------------------------------------------ search inside documents (BM25, no extra model needed)
STOP = set('the a an and or of to in on for is are was were be it this that with as at by from what which who how when '
           'where does do did about my me i you your can could would should tell say says give show find please into than'.split())

def words(text):
    return [w for w in re.findall(r'[a-z0-9]+', text.lower()) if w not in STOP and (len(w) > 1 or w.isdigit())]

def search(chunk_rows, query, k=4, budget=2600):
    """chunk_rows: [{'doc','page','text'}]. Returns the best pieces for the query, best first, within budget."""
    q = words(query)
    if not chunk_rows:
        return []
    if not q:
        return chunk_rows[:k]
    docs = [words(c['text']) for c in chunk_rows]
    n = len(docs); avg = sum(map(len, docs)) / n or 1
    df = {t: sum(1 for d in docs if t in d) for t in set(q)}
    phrase = ' '.join(q)
    scored = []
    for c, d in zip(chunk_rows, docs):
        tf = {}
        for w in d:
            if w in df:
                tf[w] = tf.get(w, 0) + 1
        s = sum(math.log(1 + (n - df[t] + .5) / (df[t] + .5)) * tf[t] * 2.2 / (tf[t] + 1.2 * (.25 + .75 * len(d) / avg)) for t in tf)
        if phrase and phrase in ' '.join(d):
            s += 3
        if s > 0:
            scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    out, used = [], 0
    for _, c in scored:
        if len(out) >= k or used + len(c['text']) > budget:
            continue
        out.append(c); used += len(c['text'])
    return out

def sections(text, size=3000, limit=8):
    """Evenly spaced parts of a document for summarising. Returns (parts, total_parts)."""
    parts = [text[i:i + size] for i in range(0, len(text), size)]
    if len(parts) <= limit:
        return parts, len(parts)
    step = (len(parts) - 1) / (limit - 1)
    return [parts[round(i * step)] for i in range(limit)], len(parts)

# ------------------------------------------------------------------ find files on this PC
EXECUTABLE = {'.exe', '.bat', '.cmd', '.com', '.msi', '.ps1', '.vbs', '.vbe', '.js', '.jse', '.wsf', '.wsh', '.scr', '.lnk',
              '.reg', '.hta', '.cpl', '.msc', '.jar', '.url', '.appref-ms', '.ps2', '.psm1', '.dll', '.sys', '.inf', '.application'}
KINDS = {'document': {'.pdf', '.doc', '.docx', '.odt', '.rtf', '.txt', '.md', '.pages'},
         'pdf': {'.pdf'}, 'word': {'.doc', '.docx'}, 'slides': {'.ppt', '.pptx', '.key', '.odp'},
         'spreadsheet': {'.xls', '.xlsx', '.csv', '.ods'}, 'image': {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.heic', '.bmp'},
         'video': {'.mp4', '.mov', '.mkv', '.avi', '.webm'}, 'audio': {'.mp3', '.wav', '.m4a', '.flac', '.ogg'},
         'code': {'.py', '.js', '.ts', '.java', '.c', '.cpp', '.cs', '.html', '.css', '.ipynb'}, 'archive': {'.zip', '.7z', '.rar'}}
SKIP_DIRS = {'appdata', 'node_modules', '.git', '__pycache__', '$recycle.bin', '.venv', 'venv', 'site-packages', '.cache',
             'windows', 'program files', 'program files (x86)', 'programdata', '.vscode', '.idea', 'cortanaai'}
FILLER = STOP | set('file files document doc folder last week yesterday today recent recently latest new old called named the my'.split())

def search_roots(extra=()):
    home = Path.home()
    roots = [home / n for n in ('Desktop', 'Documents', 'Downloads', 'Pictures', 'Videos', 'Music')]
    roots += [p for p in home.glob('OneDrive*') if p.is_dir()]
    roots += [Path(p) for p in extra]
    seen, out = set(), []
    for r in roots:
        try:
            key = str(r.resolve()).lower()
        except OSError:
            continue
        if r.is_dir() and key not in seen:
            seen.add(key); out.append(r)
    return out

def find(query, kind='', days=0, roots=None, limit=8, max_entries=80_000, max_seconds=5.0):
    """Search file names under the user's folders. Returns (results, scanned, timed_out)."""
    q = [w for w in re.findall(r'[a-z0-9]+', str(query).lower()) if w not in FILLER]
    k = str(kind or '').lower().strip()
    exts = KINDS.get(k if k in KINDS else k.rstrip('s'), set())
    newer = time.time() - float(days) * 86400 if days else 0
    start, scanned, hits = time.time(), 0, []
    stack = [(Path(r), 0) for r in (roots if roots is not None else search_roots())]
    while stack:
        folder, depth = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for e in entries:
            scanned += 1
            if scanned > max_entries or time.time() - start > max_seconds:
                return _rank(hits, q, limit), scanned, True
            name = e.name.lower()
            if name.startswith(('.', '~$')):
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    if depth < 7 and name not in SKIP_DIRS:
                        stack.append((Path(e.path), depth + 1))
                    continue
                ext = os.path.splitext(name)[1]
                if exts and ext not in exts:
                    continue
                st = e.stat()
            except OSError:
                continue
            if newer and st.st_mtime < newer:
                continue
            stem = re.findall(r'[a-z0-9]+', name)
            hit = sum(1 for w in q if any(w in s for s in stem))
            if q and hit < max(1, math.ceil(len(q) * .6)):
                continue
            hits.append((hit, st.st_mtime, e.path, st.st_size))
    return _rank(hits, q, limit), scanned, False

def _rank(hits, q, limit):
    hits.sort(key=lambda h: (-h[0], -h[1]))
    return [{'path': p, 'name': os.path.basename(p), 'modified': m, 'size': s} for _, m, p, s in hits[:limit]]

def openable(path):
    return Path(path).suffix.lower() not in EXECUTABLE and Path(path).is_file()

# ------------------------------------------------------------------ screen and clipboard (Windows)
_SHOT = r'''
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$full = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($full); $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size); $g.Dispose()
$scale = [Math]::Min(1.0, 1280 / $b.Width)
$out = New-Object System.Drawing.Bitmap ([int]($b.Width * $scale)), ([int]($b.Height * $scale))
$g = [System.Drawing.Graphics]::FromImage($out); $g.InterpolationMode = 'HighQualityBicubic'
$g.DrawImage($full, 0, 0, $out.Width, $out.Height); $g.Dispose()
$out.Save($env:CORTANA_IMAGE_OUT, [System.Drawing.Imaging.ImageFormat]::Png)
'''
_CLIP_IMAGE = r'''
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$img = [System.Windows.Forms.Clipboard]::GetImage()
if ($img -eq $null) { exit 3 }
$scale = [Math]::Min(1.0, 1280 / $img.Width)
$out = New-Object System.Drawing.Bitmap ([int]($img.Width * $scale)), ([int]($img.Height * $scale))
$g = [System.Drawing.Graphics]::FromImage($out); $g.InterpolationMode = 'HighQualityBicubic'
$g.DrawImage($img, 0, 0, $out.Width, $out.Height); $g.Dispose()
$out.Save($env:CORTANA_IMAGE_OUT, [System.Drawing.Imaging.ImageFormat]::Png)
'''

def _powershell_image(script):
    """Run a fixed PowerShell script that writes a PNG; return it as base64, or None (exit 3 = no image)."""
    if os.name != 'nt':
        raise RuntimeError('This only works on the Windows PC.')
    fd, path = tempfile.mkstemp(suffix='.png'); os.close(fd)
    try:
        env = {**os.environ, 'CORTANA_IMAGE_OUT': path}
        p = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-STA', '-ExecutionPolicy', 'Bypass', '-Command', script],
                           capture_output=True, timeout=20, creationflags=HIDDEN, env=env)
        if p.returncode == 3:
            return None
        data = Path(path).read_bytes() if p.returncode == 0 else b''
        if not data:
            raise RuntimeError('Could not capture the image.')
        return base64.b64encode(data).decode()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

def screenshot():
    return _powershell_image(_SHOT)

def clipboard_image():
    return _powershell_image(_CLIP_IMAGE)

def _win32():
    import ctypes
    from ctypes import wintypes as w
    u, k = ctypes.WinDLL('user32', use_last_error=True), ctypes.WinDLL('kernel32', use_last_error=True)
    u.OpenClipboard.argtypes = [w.HWND]; u.OpenClipboard.restype = w.BOOL
    u.GetClipboardData.argtypes = [w.UINT]; u.GetClipboardData.restype = w.HANDLE
    u.SetClipboardData.argtypes = [w.UINT, w.HANDLE]; u.SetClipboardData.restype = w.HANDLE
    u.IsClipboardFormatAvailable.argtypes = [w.UINT]; u.IsClipboardFormatAvailable.restype = w.BOOL
    k.GlobalLock.argtypes = [w.HGLOBAL]; k.GlobalLock.restype = w.LPVOID
    k.GlobalUnlock.argtypes = [w.HGLOBAL]; k.GlobalAlloc.argtypes = [w.UINT, ctypes.c_size_t]; k.GlobalAlloc.restype = w.HGLOBAL
    return ctypes, u, k

CF_UNICODETEXT = 13

def _open_clipboard(u):
    for _ in range(10):   # another app may hold it for a moment
        if u.OpenClipboard(None):
            return True
        time.sleep(.05)
    raise RuntimeError('The clipboard is busy. Try again.')

def clipboard_text():
    """Text on the clipboard, or None if it holds no text."""
    if os.name != 'nt':
        raise RuntimeError('This only works on the Windows PC.')
    ctypes, u, k = _win32()
    _open_clipboard(u)
    try:
        if not u.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        h = u.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        ptr = k.GlobalLock(h)
        try:
            return ctypes.wstring_at(ptr)
        finally:
            k.GlobalUnlock(h)
    finally:
        u.CloseClipboard()

def set_clipboard_text(text):
    if os.name != 'nt':
        raise RuntimeError('This only works on the Windows PC.')
    ctypes, u, k = _win32()
    data = (str(text) + '\0').encode('utf-16-le')
    h = k.GlobalAlloc(0x0002, len(data))   # GMEM_MOVEABLE
    ptr = k.GlobalLock(h); ctypes.memmove(ptr, data, len(data)); k.GlobalUnlock(h)
    _open_clipboard(u)
    try:
        u.EmptyClipboard()
        if not u.SetClipboardData(CF_UNICODETEXT, h):
            raise RuntimeError('Could not write to the clipboard.')
    finally:
        u.CloseClipboard()
