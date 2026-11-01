"""Things Cortana notices on her own: new documents in watched folders, finished downloads and the daily briefing.

Each tick returns quickly and only adds 'notice'/'briefing' items; the existing alert path (status poll in the page,
Windows balloon from the launcher) announces them. Nothing here reaches the network or opens files beyond reading
document text the user already chose to share by adding the folder (D-033).
"""
import time
from datetime import datetime
from pathlib import Path

PARTIAL = ('.crdownload', '.part', '.partial', '.tmp', '.download', '.opdownload')
MAX_NOTICES = 3          # per tick; more become one "and N more" notice
SETTLE_SECONDS = 15      # a download must be unchanged this long before it counts as finished
BRIEFING_WINDOW = 3 * 3600   # if the PC was off at briefing time, still brief within three hours, not later


def folder_candidates(folder):
    """Readable documents in a folder the user added (same rules as Memory → Add folder): depth ≤ 4, at most 80."""
    import files
    folder = Path(folder)
    if not folder.is_dir():
        return []
    try:
        found = [p for p in sorted(folder.rglob('*'))
                 if p.is_file() and p.suffix.lower() in files.DOC_TYPES and len(p.relative_to(folder).parts) <= 4]
    except OSError:
        return []
    return found[:80]


def _mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def mark_seen(store, paths):
    seen = store.get('watch_seen', None) or {}
    for p in paths:
        m = _mtime(Path(p))
        if m is not None:
            seen[str(p)] = m
    store.set('watch_seen', dict(list(seen.items())[-2000:]))


def index_document(store, path):
    """Read one file into Documents. Returns True when it had readable text."""
    import files
    if path.stat().st_size > files.MAX_FILE_BYTES:
        return False
    text, pages = files.extract_text(path.name, path.read_bytes())
    if not text.strip():
        return False
    store.add_document(path.name, text, files.chunks(text), pages, str(path))
    return True


def _announce(store, names, one, many, kind='notice'):
    for name in names[:MAX_NOTICES]:
        store.add_notice(one.format(name=name), kind)
    if len(names) > MAX_NOTICES:
        store.add_notice(many.format(count=len(names) - MAX_NOTICES), kind)


def watch_folders_tick(store):
    """New or changed documents in the Documents folders are read in, and she mentions them."""
    if not store.get('watch_folders', True):
        return 0
    current = {}
    for folder in store.get('doc_folders', []):
        for p in folder_candidates(folder):
            m = _mtime(p)
            if m is not None:
                current[str(p)] = (p, m)
    seen = store.get('watch_seen', None)
    if seen is None:   # first run after upgrading: everything already there counts as known
        store.set('watch_seen', {k: m for k, (_, m) in current.items()})
        return 0
    new, changed = [], []
    for key, (p, m) in current.items():
        if key in seen and seen[key] >= m - 1:
            continue
        try:
            if index_document(store, p):
                (changed if key in seen else new).append(p.name)
        except Exception:
            pass
        seen[key] = m
    store.set('watch_seen', dict(list(seen.items())[-2000:]))
    _announce(store, new, 'New document ready: {name}. Ask me to summarise it.', '{count} more new documents are ready in your folders.')
    _announce(store, changed, 'Updated document re-read: {name}.', '{count} more documents were updated.')
    return len(new) + len(changed)


def downloads_dir():
    return Path.home() / 'Downloads'


def watch_downloads_tick(store, now=None, folder=None):
    """Mention files that finished downloading (top level of Downloads only, opt-in)."""
    if not store.get('watch_downloads', False):
        return 0
    now = now or time.time()
    folder = Path(folder) if folder else downloads_dir()
    try:
        entries = [p for p in folder.iterdir() if p.is_file() and not p.name.startswith('.')]
    except OSError:
        return 0
    seen = store.get('downloads_seen', None)
    if seen is None:
        store.set('downloads_seen', [p.name for p in entries][-500:])
        return 0
    finished = []
    for p in entries:
        if p.name in seen or p.suffix.lower() in PARTIAL:
            continue
        m = _mtime(p)
        if m is None or now - m < SETTLE_SECONDS:
            continue
        finished.append(p.name)
        seen.append(p.name)
    store.set('downloads_seen', seen[-500:])
    _announce(store, finished, 'Download finished: {name}.', '{count} more downloads finished.')
    return len(finished)


def briefing_tick(store, now=None):
    """At the chosen time each day (HH:MM, local), queue the spoken briefing once."""
    at = store.get('briefing_time', '')
    if not at:
        return False
    now = now or time.time()
    local = datetime.fromtimestamp(now)
    hour, minute = (int(x) for x in at.split(':'))
    due = local.replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()
    today = local.date().isoformat()
    if now < due or now - due > BRIEFING_WINDOW or store.get('briefing_last', '') == today:
        return False
    store.set('briefing_last', today)
    store.add_notice('Your daily briefing is ready, Chief.', 'briefing')
    return True


def tick(store, now=None):
    """Run every watcher; one failing never stops the others."""
    for run in (lambda: watch_folders_tick(store), lambda: watch_downloads_tick(store, now), lambda: briefing_tick(store, now)):
        try:
            run()
        except Exception:
            pass
