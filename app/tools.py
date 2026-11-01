"""Abilities Cortana's AI can use: timers, reminders, tasks, memory, weather, web search, PC controls and calendar.

Every tool returns a small JSON-able dict that is handed back to the model. Nothing here runs arbitrary commands:
PC controls are a fixed allow-list, and network lookups only go to the services named below.
"""
import json, os, re, time, urllib.parse, urllib.request, webbrowser
from datetime import datetime, timedelta, date

UA = {'User-Agent': 'CortanaLocal/1.0 (personal assistant)'}

# ------------------------------------------------------------------ tool schemas for the model
def _fn(name, description, props=None, required=()):
    return {'type': 'function', 'function': {'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': props or {}, 'required': list(required)}}}

TOOLS = [
    _fn('set_timer', 'Start a countdown timer.', {
        'minutes': {'type': 'number', 'description': 'Length in minutes (use decimals for seconds).'},
        'label': {'type': 'string', 'description': 'What the timer is for.'}}, ['minutes']),
    _fn('set_reminder', 'Remind the user about something. Use in_minutes for relative times (in 20 minutes), or at for a clock time.', {
        'text': {'type': 'string'},
        'at': {'type': 'string', 'description': "For today or tomorrow give only the 24-hour time 'HH:MM' (the next time it occurs is used). Only for another named day give 'YYYY-MM-DD HH:MM'."},
        'in_minutes': {'type': 'number'}}, ['text']),
    _fn('add_task', 'Add an item to the to-do list (objectives).', {'text': {'type': 'string'}}, ['text']),
    _fn('list_objectives', "List the user's open timers, reminders and to-do items."),
    _fn('complete_objective', 'Mark a to-do item, reminder or timer as done or cancel it.', {
        'match': {'type': 'string', 'description': 'Words from the item text.'}}, ['match']),
    _fn('remember', 'Save a lasting fact about the user or their preferences when they tell you something worth remembering or ask you to remember it.', {
        'fact': {'type': 'string', 'description': "Short fact in the third person, e.g. 'The user's dog is called Max'."}}, ['fact']),
    _fn('forget', 'Delete remembered facts that match these words.', {'match': {'type': 'string'}}, ['match']),
    _fn('get_weather', 'Current weather and the next 3 days. Leave place empty for the home location.', {
        'place': {'type': 'string'}}),
    _fn('web_search', 'Look something up online: facts, people, places, definitions, recent info.', {
        'query': {'type': 'string'}}, ['query']),
    _fn('pc_control', 'Control the PC: media playback, volume, or open an allowed app or website.', {
        'action': {'type': 'string', 'enum': ['play_pause', 'next_track', 'previous_track', 'volume_up', 'volume_down', 'mute',
                                              'open_app', 'open_website']},
        'target': {'type': 'string', 'description': 'App name (notepad, calculator, file explorer, settings, browser, spotify, task manager) or website URL.'},
        'steps': {'type': 'integer', 'description': 'For volume: how many 2% steps (default 5).'}}, ['action']),
    _fn('get_calendar', "Events from the user's calendar for a day.", {
        'day': {'type': 'string', 'description': "'today', 'tomorrow' or 'YYYY-MM-DD'."}}),
]
TOOL_LABELS = {'set_timer': 'SETTING TIMER', 'set_reminder': 'SETTING REMINDER', 'add_task': 'UPDATING OBJECTIVES',
               'list_objectives': 'CHECKING OBJECTIVES', 'complete_objective': 'UPDATING OBJECTIVES', 'remember': 'SAVING TO MEMORY',
               'forget': 'UPDATING MEMORY', 'get_weather': 'CHECKING WEATHER', 'web_search': 'SEARCHING',
               'pc_control': 'CONTROLLING PC', 'get_calendar': 'CHECKING CALENDAR'}
CHANGES = {'set_timer': 'objectives', 'set_reminder': 'objectives', 'add_task': 'objectives', 'complete_objective': 'objectives',
           'remember': 'memory', 'forget': 'memory'}

# ------------------------------------------------------------------ helpers
def get_json(url, headers=None, timeout=12):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def get_text(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(r.headers.get_content_charset() or 'utf-8', 'replace')

def when_text(ts):
    d = datetime.fromtimestamp(ts)
    today = date.today()
    day = 'today' if d.date() == today else 'tomorrow' if d.date() == today + timedelta(days=1) else d.strftime('%a %d %b')
    return f"{day} at {d.strftime('%H:%M')}"

def parse_local_time(text):
    text = str(text).strip().replace('T', ' ')
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S', '%H:%M'):
        try:
            d = datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
        if fmt == '%H:%M':
            now = datetime.now()
            d = now.replace(hour=d.hour, minute=d.minute, second=0, microsecond=0)
            if d <= now:
                d += timedelta(days=1)
        return d.timestamp()
    raise ValueError("Time must look like 'YYYY-MM-DD HH:MM'.")

# ------------------------------------------------------------------ weather (Open-Meteo, no key)
WMO = {0: 'clear', 1: 'mainly clear', 2: 'partly cloudy', 3: 'overcast', 45: 'fog', 48: 'freezing fog', 51: 'light drizzle',
       53: 'drizzle', 55: 'heavy drizzle', 56: 'freezing drizzle', 57: 'freezing drizzle', 61: 'light rain', 63: 'rain',
       65: 'heavy rain', 66: 'freezing rain', 67: 'freezing rain', 71: 'light snow', 73: 'snow', 75: 'heavy snow',
       77: 'snow grains', 80: 'light showers', 81: 'showers', 82: 'violent showers', 85: 'snow showers', 86: 'heavy snow showers',
       95: 'thunderstorm', 96: 'thunderstorm with hail', 99: 'thunderstorm with hail'}

def weather(place, home):
    place = (place or '').strip() or home
    if not place:
        return {'error': 'No location given and no home location set. Ask the user for a town, or tell them to set it in Settings.'}
    geo = get_json('https://geocoding-api.open-meteo.com/v1/search?' + urllib.parse.urlencode({'name': place, 'count': 1, 'language': 'en'}))
    if not geo.get('results'):
        return {'error': f'Could not find a place called {place}.'}
    g = geo['results'][0]
    f = get_json('https://api.open-meteo.com/v1/forecast?' + urllib.parse.urlencode({
        'latitude': g['latitude'], 'longitude': g['longitude'], 'timezone': 'auto', 'forecast_days': 3,
        'current': 'temperature_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation',
        'daily': 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max'}))
    c, d = f['current'], f['daily']
    days = [{'date': d['time'][i], 'summary': WMO.get(d['weather_code'][i], 'mixed'), 'high_c': round(d['temperature_2m_max'][i]),
             'low_c': round(d['temperature_2m_min'][i]), 'rain_chance_pct': d['precipitation_probability_max'][i]} for i in range(len(d['time']))]
    return {'place': ', '.join(x for x in (g.get('name'), g.get('admin1'), g.get('country')) if x),
            'now': {'summary': WMO.get(c['weather_code'], 'mixed'), 'temp_c': round(c['temperature_2m']),
                    'feels_like_c': round(c['apparent_temperature']), 'wind_kmh': round(c['wind_speed_10m'])},
            'days': days, 'source': 'Open-Meteo'}

# ------------------------------------------------------------------ web search
def web_search(query, brave_key=None):
    query = str(query).strip()[:200]
    if not query:
        return {'error': 'Empty search.'}
    results = []
    if brave_key:
        try:
            data = get_json('https://api.search.brave.com/res/v1/web/search?' + urllib.parse.urlencode({'q': query, 'count': 5}),
                            headers={'X-Subscription-Token': brave_key, 'Accept': 'application/json'})
            for r in data.get('web', {}).get('results', [])[:5]:
                results.append({'title': r.get('title'), 'snippet': re.sub('<[^>]+>', '', r.get('description', '')), 'url': r.get('url')})
        except Exception as e:
            results.append({'title': 'Brave Search failed', 'snippet': str(e)[:120], 'url': ''})
    try:
        ddg = get_json('https://api.duckduckgo.com/?' + urllib.parse.urlencode({'q': query, 'format': 'json', 'no_html': 1, 'skip_disambig': 1}))
        if ddg.get('AbstractText'):
            results.append({'title': ddg.get('Heading') or query, 'snippet': ddg['AbstractText'], 'url': ddg.get('AbstractURL', '')})
        if ddg.get('Answer'):
            results.append({'title': 'Instant answer', 'snippet': str(ddg['Answer']), 'url': ''})
    except Exception:
        pass
    if len(results) < 2:
        try:
            s = get_json('https://en.wikipedia.org/w/api.php?' + urllib.parse.urlencode(
                {'action': 'query', 'list': 'search', 'srsearch': query, 'format': 'json', 'srlimit': 2}))
            for hit in s.get('query', {}).get('search', []):
                title = hit['title']
                summ = get_json('https://en.wikipedia.org/api/rest_v1/page/summary/' + urllib.parse.quote(title.replace(' ', '_')))
                results.append({'title': title, 'snippet': summ.get('extract', '')[:700],
                                'url': summ.get('content_urls', {}).get('desktop', {}).get('page', '')})
        except Exception:
            pass
    if not results:
        return {'error': 'No results found. Without a Brave Search key, only encyclopedia-style lookups work.'}
    return {'query': query, 'results': results[:6],
            'note': 'Answer from these results only and say where the information came from.'}

# ------------------------------------------------------------------ PC controls (fixed allow-list)
APPS = {'notepad': 'notepad.exe', 'calculator': 'calc.exe', 'file explorer': 'explorer.exe', 'explorer': 'explorer.exe',
        'settings': 'ms-settings:', 'browser': 'https://www.google.com', 'spotify': 'spotify:', 'task manager': 'taskmgr.exe',
        'paint': 'mspaint.exe', 'snipping tool': 'ms-screenclip:'}
VK = {'play_pause': 0xB3, 'next_track': 0xB0, 'previous_track': 0xB1, 'volume_up': 0xAF, 'volume_down': 0xAE, 'mute': 0xAD}

def press(vk, times=1):
    import ctypes
    for _ in range(times):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        time.sleep(.02)

def pc_control(action, target='', steps=5):
    if os.name != 'nt':
        return {'error': 'PC controls only work on Windows.'}
    if action in VK:
        n = max(1, min(25, int(steps or 5))) if action in ('volume_up', 'volume_down') else 1
        press(VK[action], n)
        return {'done': action.replace('_', ' '), 'steps': n}
    if action == 'open_app':
        key = str(target).strip().lower()
        key = next((k for k in APPS if k == key or k in key), None)
        if not key:
            return {'error': 'That app is not on the allowed list.', 'allowed': sorted(APPS)}
        os.startfile(APPS[key])
        return {'done': f'opened {key}'}
    if action == 'open_website':
        url = str(target).strip()
        if not re.match(r'^https?://', url):
            url = 'https://' + url
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.netloc or ' ' in parts.netloc:
            return {'error': 'Not a valid website address.'}
        webbrowser.open(url)
        return {'done': f'opened {parts.netloc}'}
    return {'error': 'Unknown action.'}

# ------------------------------------------------------------------ calendar (private iCal address, read-only)
def _unfold(text):
    return re.sub(r'\r?\n[ \t]', '', text).splitlines()

def _parse_dt(value, params):
    """Return (datetime, all_day). Times with Z or a TZID stay timezone-aware in their own zone, so repeats are
    expanded in that zone's wall-clock time (a weekly 09:30 stays 09:30 across a clock change). Floating times and
    dates stay naive. Convert to local time only after expanding (see _local)."""
    from datetime import timezone
    from zoneinfo import ZoneInfo
    if params.get('VALUE') == 'DATE' or re.fullmatch(r'\d{8}', value):
        return datetime.strptime(value[:8], '%Y%m%d'), True
    d = datetime.strptime(value.rstrip('Z')[:15], '%Y%m%dT%H%M%S')
    if value.endswith('Z'):
        return d.replace(tzinfo=timezone.utc), False
    tzid = params.get('TZID')
    if tzid:
        try:
            return d.replace(tzinfo=ZoneInfo(tzid)), False
        except Exception:
            pass  # unknown zone: treat as local time
    return d, False

def _local(d):
    """Aware datetime -> naive local time; naive values are already local."""
    return d.astimezone().replace(tzinfo=None) if d.tzinfo else d

def parse_ics(text):
    events, cur = [], None
    for line in _unfold(text):
        if line == 'BEGIN:VEVENT':
            cur = {'exdates': []}
        elif line == 'END:VEVENT' and cur is not None:
            if 'start' in cur:
                events.append(cur)
            cur = None
        elif cur is not None and ':' in line:
            head, value = line.split(':', 1)
            name, *ps = head.split(';')
            params = dict(p.split('=', 1) for p in ps if '=' in p)
            if name == 'SUMMARY':
                cur['title'] = value.replace('\\,', ',').replace('\\n', ' ').replace('\\;', ';')
            elif name == 'LOCATION':
                cur['location'] = value.replace('\\,', ',')
            elif name in ('DTSTART', 'DTEND'):
                d, all_day = _parse_dt(value, params)
                cur['start' if name == 'DTSTART' else 'end'] = d
                if name == 'DTSTART':
                    cur['all_day'] = all_day
            elif name == 'RRULE':
                cur['rrule'] = value
            elif name == 'EXDATE':
                for v in value.split(','):
                    cur['exdates'].append(_parse_dt(v, params)[0])
            elif name == 'STATUS':
                cur['status'] = value
    return events

def events_on(events, day):
    lo = datetime.combine(day, datetime.min.time())
    hi = lo + timedelta(days=1)
    out = []
    for e in events:
        if e.get('status') == 'CANCELLED':
            continue
        start = e['start']
        end = e.get('end')
        if end is not None and (end.tzinfo is None) != (start.tzinfo is None):
            end = None  # mixed aware/naive values can't be subtracted; fall back to the default length
        length = (end or start + (timedelta(days=1) if e.get('all_day') else timedelta(hours=1))) - start
        starts = [start]
        if e.get('rrule'):
            try:
                from dateutil.rrule import rrulestr
                rule = rrulestr(e['rrule'], dtstart=start)
                # Search a generous window in the event's own zone, then filter precisely in local time below.
                pad = length + timedelta(days=1)
                wlo, whi = lo - pad, hi + timedelta(days=1)
                if start.tzinfo:
                    wlo, whi = wlo.replace(tzinfo=start.tzinfo), whi.replace(tzinfo=start.tzinfo)
                starts = rule.between(wlo, whi, inc=True)
            except Exception:
                try:  # e.g. a UNTIL in UTC on a floating start: expand naively, as before
                    from dateutil.rrule import rrulestr
                    naive = start.replace(tzinfo=None)
                    starts = rrulestr(e['rrule'], dtstart=naive, ignoretz=True).between(lo - length, hi, inc=True)
                    starts = [x.replace(tzinfo=start.tzinfo) for x in starts]
                except Exception:
                    starts = [start]
        for s in starts:
            if s in e['exdates']:  # aware values compare by instant, across zones
                continue
            ls = _local(s)
            if ls < hi and ls + length > lo:
                out.append({'title': e.get('title', 'Busy'), 'start': ls, 'all_day': e.get('all_day', False),
                            'location': e.get('location', '')})
    out.sort(key=lambda x: (not x['all_day'], x['start']))
    return out

_ics_cache = {'url': None, 'at': 0, 'events': []}

def calendar(url, day='today'):
    if not url:
        return {'error': "No calendar connected. In Settings, paste your Google Calendar's secret address in iCal format."}
    if _ics_cache['url'] != url or time.time() - _ics_cache['at'] > 300:
        _ics_cache.update(url=url, at=time.time(), events=parse_ics(get_text(url)))
    day = str(day or 'today').strip().lower()
    d = date.today() + timedelta(days=1) if day == 'tomorrow' else date.today() if day in ('', 'today') else datetime.strptime(day[:10], '%Y-%m-%d').date()
    items = events_on(_ics_cache['events'], d)
    return {'day': d.strftime('%A %d %B'), 'events': [
        {'title': e['title'], 'time': 'all day' if e['all_day'] else e['start'].strftime('%H:%M'), 'location': e['location']} for e in items]}

# ------------------------------------------------------------------ dispatcher
def run(name, args, store):
    """Run one tool. Returns (result_dict, change) where change is 'objectives', 'memory' or None."""
    args = args if isinstance(args, dict) else {}
    try:
        if name == 'set_timer':
            minutes = float(args.get('minutes', 0))
            if not 0 < minutes <= 24 * 60:
                return {'error': 'Timers must be between a few seconds and 24 hours.'}, None
            due = time.time() + minutes * 60
            label = args.get('label') or f'{minutes:g} minute timer'
            iid = store.add_item('timer', label, due)
            return {'done': 'timer set', 'id': iid, 'label': label, 'rings': when_text(due)}, 'objectives'
        if name == 'set_reminder':
            if args.get('in_minutes') not in (None, ''):
                due = time.time() + float(args['in_minutes']) * 60
            elif args.get('at'):
                due = parse_local_time(args['at'])
            else:
                return {'error': 'Ask the user when to remind them.'}, None
            if due < time.time() - 60:
                return {'error': 'That time has already passed.'}, None
            iid = store.add_item('reminder', args.get('text', 'Reminder'), due)
            return {'done': 'reminder set', 'id': iid, 'when': when_text(due)}, 'objectives'
        if name == 'add_task':
            iid = store.add_item('task', args.get('text', ''))
            return {'done': 'added to objectives', 'id': iid}, 'objectives'
        if name == 'list_objectives':
            items = store.items()
            return {'open': [{'id': i['id'], 'type': i['kind'], 'text': i['text'],
                              **({'when': when_text(i['due'])} if i['due'] else {})} for i in items] or 'nothing open'}, None
        if name == 'complete_objective':
            found = store.find_items(args.get('match', ''))
            if not found:
                return {'error': 'No open item matches that.'}, None
            for i in found[:3]:
                store.complete_item(i['id'])
            return {'done': 'completed', 'items': [i['text'] for i in found[:3]]}, 'objectives'
        if name == 'remember':
            store.add_fact(args.get('fact', ''))
            return {'done': 'saved to memory'}, 'memory'
        if name == 'forget':
            gone = store.forget_fact(match=args.get('match', ''))
            return ({'done': 'forgotten', 'facts': [f['text'] for f in gone]} if gone else {'error': 'Nothing in memory matches that.'}), 'memory'
        if name == 'get_weather':
            return weather(args.get('place', ''), store.get('home_location', '')), None
        if name == 'web_search':
            return web_search(args.get('query', ''), store.get('brave_key', '')), None
        if name == 'pc_control':
            if not store.get('pc_controls', True):
                return {'error': 'PC controls are switched off in Settings.'}, None
            return pc_control(args.get('action'), args.get('target', ''), args.get('steps', 5)), None
        if name == 'get_calendar':
            return calendar(store.get('calendar_url', ''), args.get('day', 'today')), None
        return {'error': f'Unknown tool {name}.'}, None
    except Exception as e:
        return {'error': f'{name} failed: {str(e)[:160]}'}, None
