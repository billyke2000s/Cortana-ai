"""Cortana's "work" abilities (1.6): create files, analyse tables, tidy folders, check the PC's health, draft emails
and calculate.

Rules (AGENTS §4.7, D-034/D-035):
- Nothing runs model-provided commands. Folders are a fixed map (Downloads, Desktop, Documents); new files only go into
  Documents\\Cortana; file names are sanitised; nothing is ever deleted or overwritten.
- Anything that changes the PC (create_file, organise_files, draft_email) goes through the ask-before-doing gate:
  `preview()` describes it, and it runs only after the user approves (tools.run(..., approved=True)).
"""
import ast, csv, hashlib, html, io, json, math, os, re, shutil, subprocess, urllib.parse, webbrowser, zipfile
from pathlib import Path

HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
KINDS = {'document': '.docx', 'spreadsheet': '.csv', 'text': '.txt', 'markdown': '.md', 'webpage': '.html'}
MAX_CONTENT = 20000


def output_dir():
    """Where Cortana saves what she makes: Documents\\Cortana (CORTANA_OUTPUT_DIR overrides it for tests)."""
    return Path(os.environ.get('CORTANA_OUTPUT_DIR') or (known_folder('documents') / 'Cortana'))


def known_folder(name):
    """The user's Downloads/Desktop/Documents, following OneDrive redirection when the plain folder is missing."""
    home = Path.home()
    plain = home / {'downloads': 'Downloads', 'desktop': 'Desktop', 'documents': 'Documents'}[name]
    if plain.is_dir() or name == 'downloads':
        return plain
    onedrive = Path(os.environ.get('OneDrive', home / 'OneDrive')) / plain.name
    return onedrive if onedrive.is_dir() else plain


# ------------------------------------------------------------------ create_file
def clean_name(name, kind):
    ext = KINDS[kind]
    stem = re.sub(r'\.[A-Za-z0-9]{1,5}$', '', str(name or '').strip())
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', ' ', stem)
    stem = ' '.join(stem.split()).strip(' .')[:80] or 'Cortana notes'
    if stem.upper() in {'CON', 'PRN', 'AUX', 'NUL'} or re.fullmatch(r'(?i)(COM|LPT)\d', stem):
        stem = '_' + stem
    return stem + ext


def unique_path(folder, filename):
    """Never overwrite: 'Report.docx' -> 'Report (2).docx'."""
    path = Path(folder) / filename
    n = 2
    while path.exists():
        path = Path(folder) / f'{Path(filename).stem} ({n}){Path(filename).suffix}'
        n += 1
    return path


def _file_args(args):
    kind = str(args.get('kind') or 'document').lower()
    if kind not in KINDS:
        raise ValueError('Choose document, spreadsheet, text, markdown or webpage.')
    content = str(args.get('content') or '')
    if not content.strip():
        raise ValueError('There is nothing to put in the file yet.')
    if len(content) > MAX_CONTENT:
        raise ValueError(f'That is too long for one file ({len(content):,} characters; the limit is {MAX_CONTENT:,}).')
    if kind == 'spreadsheet':
        rows = csv_rows(content)
        if len(rows) < 1 or max(len(r) for r in rows) < 2:
            raise ValueError('A spreadsheet needs comma-separated columns, one row per line.')
    return kind, content, clean_name(args.get('name'), kind)


def preview_create_file(args):
    kind, content, filename = _file_args(args)
    target = unique_path(output_dir(), filename)
    return {'summary': f'Create {target.name} in Documents\\Cortana', 'detail': content[:600] + ('…' if len(content) > 600 else '')}


def create_file(args):
    kind, content, filename = _file_args(args)
    folder = output_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = unique_path(folder, filename)
    if kind == 'document':
        path.write_bytes(docx_bytes(content))
    elif kind == 'spreadsheet':
        out = io.StringIO()
        csv.writer(out, lineterminator='\r\n').writerows(csv_rows(content))
        path.write_text(out.getvalue(), encoding='utf-8-sig', newline='')   # BOM: Excel reads accents; newline='': no doubled \r on Windows
    elif kind == 'webpage':
        path.write_text(html_page(filename.rsplit('.', 1)[0], content), encoding='utf-8')
    else:
        path.write_text(content, encoding='utf-8')
    return {'done': 'file created', 'file': path.name, 'folder': 'Documents\\Cortana', 'path': str(path),
            'note': 'Say open_file number 1 opens it.'}


def csv_rows(text):
    sample = text.strip()
    try:
        dialect = csv.Sniffer().sniff(sample[:2000], delimiters=',;\t|')
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(sample), dialect) if any(c.strip() for c in r)]
    return [[c.strip() for c in r] for r in rows]


def _runs(text):
    """Markdown **bold** inside a paragraph -> WordprocessingML runs (text is XML-escaped)."""
    out = []
    for i, part in enumerate(re.split(r'\*\*(.+?)\*\*', text)):
        if part:
            props = '<w:rPr><w:b/></w:rPr>' if i % 2 else ''
            out.append(f'<w:r>{props}<w:t xml:space="preserve">{html.escape(part, quote=False)}</w:t></w:r>')
    return ''.join(out)


def docx_bytes(markdown):
    """A small, valid .docx from simple Markdown: # / ## / ### headings, - or * bullets, 1. lists, paragraphs, **bold**."""
    paras = []
    for line in markdown.splitlines():
        s = line.rstrip()
        if not s.strip():
            continue
        m = re.match(r'^(#{1,3})\s+(.*)', s)
        if m:
            paras.append(f'<w:p><w:pPr><w:pStyle w:val="Heading{len(m[1])}"/></w:pPr>{_runs(m[2])}</w:p>')
        elif re.match(r'^\s*[-*•]\s+', s):
            paras.append(f'<w:p><w:pPr><w:pStyle w:val="ListParagraph"/><w:ind w:left="360" w:hanging="240"/></w:pPr>{_runs("• " + re.sub(r"^\s*[-*•]\s+", "", s))}</w:p>')
        else:
            paras.append(f'<w:p>{_runs(s.strip())}</w:p>')
    W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {W}><w:body>{"".join(paras)}'
                '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>')
    heading = lambda n, size: (f'<w:style w:type="paragraph" w:styleId="Heading{n}"><w:name w:val="heading {n}"/><w:basedOn w:val="Normal"/>'
                               f'<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="80"/><w:outlineLvl w:val="{n - 1}"/></w:pPr>'
                               f'<w:rPr><w:b/><w:sz w:val="{size}"/></w:rPr></w:style>')
    styles = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles {W}>'
              '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/><w:sz w:val="22"/></w:rPr></w:rPrDefault>'
              '<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
              '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
              + heading(1, 32) + heading(2, 26) + heading(3, 23) +
              '<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/></w:style></w:styles>')
    files = {
        '[Content_Types].xml': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                               '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                               '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                               '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>',
        '_rels/.rels': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        'word/_rels/document.xml.rels': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        'word/document.xml': document, 'word/styles.xml': styles}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def html_page(title, markdown):
    """A self-contained page from simple Markdown. Everything is escaped: no model-written HTML or scripts get through."""
    body, in_list = [], False
    for line in markdown.splitlines():
        s = line.strip()
        bullet = re.match(r'^[-*•]\s+(.*)', s)
        if in_list and not bullet:
            body.append('</ul>'); in_list = False
        if not s:
            continue
        inline = lambda t: re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', html.escape(t))
        m = re.match(r'^(#{1,3})\s+(.*)', s)
        if m:
            body.append(f'<h{len(m[1])}>{inline(m[2])}</h{len(m[1])}>')
        elif bullet:
            if not in_list:
                body.append('<ul>'); in_list = True
            body.append(f'<li>{inline(bullet[1])}</li>')
        else:
            body.append(f'<p>{inline(s)}</p>')
    if in_list:
        body.append('</ul>')
    return ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title><style>body{{font:16px/1.55 system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;color:#1b2430}}'
            'h1,h2,h3{line-height:1.2}</style>' + '\n'.join(body))


# ------------------------------------------------------------------ analyse_table (read-only)
def number(cell):
    t = re.sub(r'[£$€,\s]', '', str(cell)).rstrip('%')
    if re.fullmatch(r'\(\d+(\.\d+)?\)', t):   # accounting negatives
        t = '-' + t[1:-1]
    try:
        v = float(t)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def analyse_table(store, args):
    doc = store.find_document(str(args.get('document') or ''))
    if not doc:
        return {'error': 'Add the CSV or spreadsheet export to Documents first (paperclip in Chat).'}
    rows = csv_rows(store.document_text(doc['id'], '\n'))   # pieces of a table split at row ends (files.chunks)
    if len(rows) < 2 or max(len(r) for r in rows) < 2:
        return {'error': f"{doc['name']} doesn't look like a table (comma-separated rows)."}
    header, data = rows[0], rows[1:]
    columns = []
    for i, name in enumerate(header[:15]):
        values = [number(r[i]) for r in data if i < len(r) and str(r[i]).strip()]
        nums = [v for v in values if v is not None]
        if values and len(nums) >= max(1, len(values) * .8):
            columns.append({'column': name or f'Column {i + 1}', 'count': len(nums), 'total': round(sum(nums), 4),
                            'average': round(sum(nums) / len(nums), 4), 'min': min(nums), 'max': max(nums)})
    want = str(args.get('column') or '').lower().strip()
    if want:
        columns = [c for c in columns if want in c['column'].lower()] or columns
    return {'document': doc['name'], 'rows': len(data), 'columns': header[:15], 'numeric_columns': columns,
            'note': 'These figures were calculated exactly. Use them; do not recalculate.'}


# ------------------------------------------------------------------ organise_files
GROUPS = {
    'Images': {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.heic', '.svg', '.tif', '.tiff'},
    'Documents': {'.pdf', '.doc', '.docx', '.odt', '.rtf', '.txt', '.md', '.ppt', '.pptx', '.xls', '.xlsx', '.csv', '.epub'},
    'Archives': {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz'},
    'Installers': {'.exe', '.msi', '.msix', '.appx', '.iso'},
    'Video': {'.mp4', '.mkv', '.mov', '.avi', '.webm', '.wmv'},
    'Audio': {'.mp3', '.wav', '.flac', '.m4a', '.ogg', '.aac'},
    'Code': {'.py', '.js', '.ts', '.html', '.css', '.json', '.xml', '.ps1', '.bat', '.sh', '.java', '.c', '.cpp', '.cs'},
}
SKIP = {'.lnk', '.url', '.ini', '.crdownload', '.part', '.tmp', '.download'}


def _group(path):
    ext = path.suffix.lower()
    return next((g for g, exts in GROUPS.items() if ext in exts), 'Other')


def _organise_plan(args):
    which = str(args.get('folder') or '').lower()
    if which not in ('downloads', 'desktop', 'documents'):
        raise ValueError('I can tidy Downloads, Desktop or Documents.')
    folder = known_folder(which)
    if not folder.is_dir():
        raise ValueError(f'Your {which.title()} folder was not found.')
    files = sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith(('.', '~$'))
                   and p.suffix.lower() not in SKIP and p.name.lower() != 'desktop.ini')[:500]
    moves = [(p, folder / _group(p)) for p in files]
    if which == 'documents':   # never shuffle documents into a "Documents" folder inside Documents
        moves = [(p, d if d.name != 'Documents' else folder / 'Files') for p, d in moves]
    return which, folder, moves


def duplicates(paths, limit_bytes=300 * 1024 * 1024):
    """Groups of identical files (same size, then same SHA-256). Reported only; never deleted."""
    by_size = {}
    for p in paths:
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if 0 < size <= limit_bytes:
            by_size.setdefault(size, []).append(p)
    groups = {}
    for same in by_size.values():
        if len(same) < 2:
            continue
        for p in same:
            h = hashlib.sha256()
            with open(p, 'rb') as f:
                for block in iter(lambda: f.read(1 << 20), b''):
                    h.update(block)
            groups.setdefault(h.hexdigest(), []).append(p.name)
    return [names for names in groups.values() if len(names) > 1][:10]


def preview_organise(args):
    which, folder, moves = _organise_plan(args)
    if not moves:
        raise ValueError(f'Your {which.title()} folder has no loose files to tidy.')
    counts = {}
    for _, dest in moves:
        counts[dest.name] = counts.get(dest.name, 0) + 1
    dupes = duplicates([p for p, _ in moves])
    detail = ', '.join(f'{n} → {g}' for g, n in sorted(counts.items(), key=lambda x: -x[1]))
    if dupes:
        detail += '\nIdentical copies (left alone): ' + '; '.join(' = '.join(d[:3]) for d in dupes[:5])
    return {'summary': f'Move {len(moves)} loose files in {which.title()} into folders by type', 'detail': detail}


def organise(args):
    which, folder, moves = _organise_plan(args)
    placed = []
    for src, dest in moves:
        if not src.exists():
            continue
        dest.mkdir(exist_ok=True)
        target = unique_path(dest, src.name)   # never overwrite a file already in that folder
        os.replace(src, target)
        placed.append(target)
    moved = len(placed)
    dupes = duplicates(placed)
    return {'done': f'moved {moved} files into folders by type', 'folder': which.title(),
            **({'identical_copies': dupes[:5], 'note': 'Duplicates were left in place; the user can delete them.'} if dupes else {})}


# ------------------------------------------------------------------ pc_health (read-only)
HEALTH_PS = r'''
$ErrorActionPreference = 'SilentlyContinue'
$cpu = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
$top = Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 6 | ForEach-Object { @{ name = $_.ProcessName; mb = [math]::Round($_.WorkingSet64 / 1MB) } }
$crashes = Get-WinEvent -FilterHashtable @{ LogName = 'Application'; Id = 1000; StartTime = (Get-Date).AddDays(-2) } -MaxEvents 8 | ForEach-Object {
  @{ app = ($_.Properties[0].Value); when = $_.TimeCreated.ToString('ddd HH:mm') } }
$boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
@{ cpu_pct = $cpu; top = @($top); crashes = @($crashes); uptime_hours = [math]::Round(((Get-Date) - $boot).TotalHours, 1) } | ConvertTo-Json -Depth 4 -Compress
'''


def pc_health():
    import hardware
    out = {}
    drives = []
    letters = [f'{c}:\\' for c in 'CDEFGHIJ'] if os.name == 'nt' else ['/']
    for root in letters:
        try:
            u = shutil.disk_usage(root)
        except OSError:
            continue
        drives.append({'drive': root.rstrip('\\'), 'free_gb': round(u.free / 1024 ** 3, 1), 'total_gb': round(u.total / 1024 ** 3),
                       'used_pct': round(100 * (u.total - u.free) / u.total)})
    out['drives'] = drives
    out['ram_gb'] = round(hardware._ram_gb(), 1)
    if os.name == 'nt':
        try:
            p = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', HEALTH_PS],
                               capture_output=True, timeout=25, creationflags=HIDDEN)
            info = json.loads(p.stdout.decode('utf-8', 'replace') or '{}')
            out.update({k: info.get(k) for k in ('cpu_pct', 'uptime_hours')})
            out['biggest_programs_mb'] = [t for t in (info.get('top') or []) if isinstance(t, dict)][:6]
            out['app_crashes_last_2_days'] = [c for c in (info.get('crashes') or []) if isinstance(c, dict)][:8]
        except (subprocess.TimeoutExpired, ValueError, OSError):
            out['note'] = 'Windows did not report processor and crash details this time.'
    tips = [f"Drive {d['drive']} is {d['used_pct']}% full" for d in drives if d['used_pct'] >= 90]
    if out.get('uptime_hours') and out['uptime_hours'] > 24 * 7:
        tips.append('the PC has not restarted for over a week')
    if tips:
        out['worth_mentioning'] = tips
    return out


# ------------------------------------------------------------------ draft_email
EMAIL = re.compile(r'^[^@\s,;<>]+@[^@\s,;<>]+\.[A-Za-z]{2,}$')


def _email_args(args):
    to = str(args.get('to') or '').strip()
    if to and not EMAIL.match(to):
        raise ValueError("That doesn't look like an email address.")
    subject = ' '.join(str(args.get('subject') or '').split())[:150]
    body = str(args.get('body') or '').strip()[:1500]
    if not (subject or body):
        raise ValueError('There is nothing to put in the email yet.')
    return to, subject, body


def preview_email(args):
    to, subject, body = _email_args(args)
    return {'summary': f"Open an email draft{' to ' + to if to else ''} in your mail app (you press Send)",
            'detail': f'Subject: {subject}\n\n{body}'}


def draft_email(args):
    to, subject, body = _email_args(args)
    url = 'mailto:' + urllib.parse.quote(to, safe='@') + '?' + urllib.parse.urlencode(
        {'subject': subject, 'body': body.replace('\n', '\r\n')}, quote_via=urllib.parse.quote)
    if not webbrowser.open(url):
        raise RuntimeError('No email app is set up on this PC.')
    return {'done': 'draft opened in the mail app; the user still presses Send'}


# ------------------------------------------------------------------ calculate (read-only, no code execution)
_FUNCS = {'round': round, 'abs': abs, 'min': min, 'max': max, 'sqrt': math.sqrt, 'floor': math.floor, 'ceil': math.ceil,
          'log': math.log10, 'ln': math.log}
_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.USub, ast.UAdd)


def calculate(expression):
    """Exact arithmetic for the model (small models get sums wrong). Numbers, + - * / // % ** ( ) and a few functions."""
    text = str(expression or '').strip()[:300]
    text = re.sub(r'(\d+(?:\.\d+)?)\s*%\s*of\s*', r'(\1/100)*', text, flags=re.I)
    text = text.replace('×', '*').replace('÷', '/').replace('^', '**').replace(',', '')
    if not text:
        raise ValueError('Give me something to calculate.')
    tree = ast.parse(text, mode='eval')

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, _OPS):
            a, b = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and (abs(b) > 100 or abs(a) > 1e6):
                raise ValueError('That power is too large.')
            return {ast.Add: lambda: a + b, ast.Sub: lambda: a - b, ast.Mult: lambda: a * b, ast.Div: lambda: a / b,
                    ast.FloorDiv: lambda: a // b, ast.Mod: lambda: a % b, ast.Pow: lambda: a ** b}[type(node.op)]()
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = ev(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise ValueError('I can only calculate with numbers and + - × ÷ ^ ( ).')
    try:
        value = ev(tree)
    except ZeroDivisionError:
        raise ValueError('That divides by zero.')
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('The answer is too large.')
        value = round(value, 10)
        value = int(value) if value.is_integer() and abs(value) < 1e15 else value
    return {'expression': text, 'result': value}
