"""Data-only extension manifests. No extension code is imported into Cortana."""
import copy
import hashlib
import json
import re
import threading
import urllib.request
from urllib.parse import urlsplit

KEY = 'installed_extensions'
MAX_EXTENSIONS = 4
MAX_TOOLS = 4


def checked(value):
    """Validate the entire package before saving anything, including its private connection."""
    value = copy.deepcopy(value)
    if not isinstance(value, dict) or len(json.dumps(value)) > 30000:
        raise ValueError('Choose an extension JSON file smaller than 30 KB.')
    if value.get('manifest_version') != 1:
        raise ValueError('Unsupported extension manifest version.')
    for key, pattern in [('id', r'[a-z][a-z0-9.-]{2,49}'), ('version', r'\d+\.\d+\.\d+')]:
        if not isinstance(value.get(key), str) or not re.fullmatch(pattern, value[key]):
            raise ValueError('Invalid extension ' + key + '.')
    for key, limit in [('name', 80), ('description', 400)]:
        if not isinstance(value.get(key), str) or not 1 <= len(value[key]) <= limit:
            raise ValueError('Invalid extension ' + key + '.')
    conn = value.get('connection', {})
    if not isinstance(conn, dict) or not isinstance(conn.get('url'), str):
        raise ValueError('Invalid extension connection.')
    url = conn.get('url', '')
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == 'http' and parsed.hostname == '127.0.0.1' and
                 1024 <= parsed.port <= 65535 and parsed.path in ('', '/') and
                 not parsed.username and not parsed.password and not parsed.query and not parsed.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('Extension services must use http://127.0.0.1 and an explicit port above 1023.')
    token = conn.get('token')
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', token):
        raise ValueError('The extension needs a private service token.')
    tools = value.get('tools')
    if not isinstance(tools, list) or not 1 <= len(tools) <= MAX_TOOLS:
        raise ValueError('An extension needs between one and four tools.')
    names = set()
    for tool in tools:
        name = tool.get('name') if isinstance(tool, dict) else None
        if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,23}', name) or name in names:
            raise ValueError('Tool names must be unique lowercase identifiers.')
        names.add(name)
        if not isinstance(tool.get('description'), str) or not 1 <= len(tool['description']) <= 400:
            raise ValueError('Each tool needs a short description.')
        if not isinstance(tool.get('approval'), bool):
            raise ValueError('Each tool must explicitly declare approval true or false.')
        if not re.fullmatch(r'/v1/[a-z0-9/_-]{1,100}', str(tool.get('path', ''))):
            raise ValueError('Tool paths must be fixed /v1/ paths.')
        schema = tool.get('parameters')
        if not isinstance(schema, dict) or schema.get('type') != 'object':
            raise ValueError('Tool parameters must be an object schema.')
        props = schema.get('properties', {})
        if not isinstance(props, dict) or len(props) > 10:
            raise ValueError('Too many tool parameters.')
        for key, prop in props.items():
            if not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', key) or not isinstance(prop, dict) or prop.get('type') not in ('string', 'integer', 'number', 'boolean'):
                raise ValueError('Tool parameters support named scalar values only.')
            if 'enum' in prop and (not isinstance(prop['enum'], list) or len(prop['enum']) > 40):
                raise ValueError('Invalid parameter choices.')
        if not isinstance(schema.get('required', []), list) or any(k not in props for k in schema.get('required', [])):
            raise ValueError('Invalid required parameters.')
    if len(json.dumps(tools)) > 5500:
        raise ValueError('Tool descriptions exceed the local model context budget.')
    # Unknown fields cannot become code, UI, headers or a launch command later.
    return {k: value[k] for k in ('manifest_version', 'id', 'name', 'description', 'version', 'connection', 'tools')}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Extension services cannot redirect requests.')


def tool_name(manifest, tool):
    return 'ext_' + hashlib.sha256(manifest['id'].encode()).hexdigest()[:10] + '_' + tool['name']


def revision(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


class ExtensionManager:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()

    def entries(self):
        return self.store.get(KEY, [])

    def listing(self):
        with self.lock:
            return {'extensions': [
                {k: e['manifest'][k] for k in ('id', 'name', 'version', 'description')} |
                {'enabled': e['enabled'], 'tools': [
                    {k: t[k] for k in ('name', 'description', 'approval')} for t in e['manifest']['tools']]}
                for e in self.entries()]}

    def manage(self, data):
        with self.lock:
            entries = self.entries()
            action = data.get('action')
            if action in ('preview', 'install'):
                manifest = checked(data.get('manifest'))
                safe = {k: manifest[k] for k in ('id', 'name', 'description', 'version', 'tools')}
                safe['service'] = manifest['connection']['url']
                if action == 'preview':
                    return safe
                entries = [e for e in entries if e['manifest']['id'] != manifest['id']]
                if len(entries) >= MAX_EXTENSIONS:
                    raise ValueError('Remove an extension before installing another.')
                entries.append({'manifest': manifest, 'enabled': False})
            elif action in ('enable', 'disable', 'remove'):
                entry = next((e for e in entries if e['manifest']['id'] == data.get('id')), None)
                if entry is None:
                    raise ValueError('Extension not found.')
                if action == 'remove':
                    entries.remove(entry)
                else:
                    if action == 'enable':
                        checked(entry['manifest'])
                        total = sum(len(e['manifest']['tools']) for e in entries if e['enabled'] and e is not entry)
                        budget = sum(len(json.dumps(e['manifest']['tools'])) for e in entries if e['enabled'] and e is not entry)
                        if total + len(entry['manifest']['tools']) > 4 or budget + len(json.dumps(entry['manifest']['tools'])) > 5500:
                            raise ValueError('Disable another extension to stay within the local model tool budget.')
                    entry['enabled'] = action == 'enable'
            else:
                raise ValueError('Unknown extension action.')
            self.store.set(KEY, entries)
            return self.listing()

    def resolve(self, name):
        if not self.store.get('tools_enabled', True):
            raise ValueError('Abilities are switched off.')
        with self.lock:
            for entry in self.entries():
                if entry['enabled']:
                    m = entry['manifest']
                    for tool in m['tools']:
                        if tool_name(m, tool) == name:
                            return copy.deepcopy(m), copy.deepcopy(tool)
        raise ValueError('That extension is disabled or was removed.')

    def schemas(self, local=False):
        if not local or not self.store.get('tools_enabled', True):
            return []
        with self.lock:
            return [{'type': 'function', 'function': {
                'name': tool_name(e['manifest'], t),
                'description': e['manifest']['name'] + ': ' + t['description'],
                'parameters': t['parameters']}}
                for e in self.entries() if e['enabled'] for t in e['manifest']['tools']]

    def prepare(self, name, args):
        m, t = self.resolve(name)
        props = t['parameters'].get('properties', {})
        if not isinstance(args, dict) or set(args) - props.keys():
            raise ValueError('Unknown extension arguments.')
        for key in t['parameters'].get('required', []):
            if key not in args:
                raise ValueError('Missing extension argument: ' + key)
        for key, value in args.items():
            p = props[key]
            typ = p['type']
            valid = {'string': isinstance(value, str) and len(value) <= 4000,
                     'boolean': isinstance(value, bool),
                     'integer': type(value) is int,
                     'number': type(value) in (int, float)}[typ]
            if not valid or ('enum' in p and value not in p['enum']):
                raise ValueError('Invalid extension argument: ' + key)
        return m, t

    def call(self, name, args, local=False, approved=False, expected=None):
        if not local:
            raise ValueError('Extensions are available on the PC only.')
        m, t = self.prepare(name, args)
        if expected and expected != revision(m):
            raise ValueError('The extension changed. Ask again before approving.')
        if t['approval'] and not approved:
            raise ValueError('Approve this extension action first.')
        body = json.dumps({'arguments': args, 'approved': bool(approved)}).encode()
        request = urllib.request.Request(m['connection']['url'].rstrip('/') + t['path'], data=body,
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + m['connection']['token']})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(request, timeout=15) as response:
                raw = response.read(32001)
            if len(raw) > 32000:
                raise ValueError('Extension response was too large.')
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError('Invalid extension response.')
            # Never echo a service token even if a misconfigured service sends it back.
            return json.loads(json.dumps(result).replace(m['connection']['token'], '[private]'))
        except Exception:
            return {'error': 'The extension service could not finish. Check that its local launcher is running.'}
