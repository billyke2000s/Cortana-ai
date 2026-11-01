"""Cortana's local storage on this PC (SQLite): settings, remembered facts, conversation log, timers, reminders and tasks."""
import sqlite3, threading, time, json

SCHEMA = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY, text TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, role TEXT NOT NULL, content TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS items(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, text TEXT NOT NULL, due REAL,
  done INTEGER NOT NULL DEFAULT 0, announced INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
'''
KINDS = ('timer', 'reminder', 'task')
MAX_FACTS = 200
MAX_MESSAGES = 2000


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)

    def close(self):
        with self.lock:
            self.db.close()

    def q(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return [dict(r) for r in cur.fetchall()]

    def insert(self, sql, args):
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur.lastrowid

    # ---- settings
    def get(self, key, default=None):
        rows = self.q('SELECT value FROM settings WHERE key=?', (key,))
        return json.loads(rows[0]['value']) if rows else default

    def set(self, key, value):
        self.q('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
               (key, json.dumps(value)))

    # ---- remembered facts
    def facts(self):
        return self.q('SELECT id,text,created FROM facts ORDER BY id')

    def add_fact(self, text):
        text = ' '.join(str(text).split())[:300]
        if not text:
            raise ValueError('Nothing to remember.')
        existing = [f for f in self.facts() if f['text'].lower() == text.lower()]
        if existing:
            return existing[0]['id']
        fid = self.insert('INSERT INTO facts(text,created) VALUES(?,?)', (text, time.time()))
        self.q('DELETE FROM facts WHERE id NOT IN (SELECT id FROM facts ORDER BY id DESC LIMIT ?)', (MAX_FACTS,))
        return fid

    def forget_fact(self, fact_id=None, match=None):
        if fact_id is not None:
            return self.q('DELETE FROM facts WHERE id=? RETURNING id', (int(fact_id),))
        words = [w for w in str(match or '').lower().split() if len(w) > 2]
        if not words:
            return []
        gone = [f for f in self.facts() if all(w in f['text'].lower() for w in words)]
        for f in gone:
            self.q('DELETE FROM facts WHERE id=?', (f['id'],))
        return gone

    # ---- conversation log
    def log_message(self, role, content):
        if role in ('user', 'assistant') and content:
            self.insert('INSERT INTO messages(role,content,created) VALUES(?,?,?)', (role, str(content)[:6000], time.time()))
            self.q('DELETE FROM messages WHERE id NOT IN (SELECT id FROM messages ORDER BY id DESC LIMIT ?)', (MAX_MESSAGES,))

    def recent_messages(self, limit=40):
        return list(reversed(self.q('SELECT id,role,content,created FROM messages ORDER BY id DESC LIMIT ?', (int(limit),))))

    def clear_messages(self):
        self.q('DELETE FROM messages')

    # ---- timers, reminders, tasks
    def add_item(self, kind, text, due=None):
        if kind not in KINDS:
            raise ValueError('Unknown item type.')
        text = ' '.join(str(text).split())[:200] or kind.title()
        return self.insert('INSERT INTO items(kind,text,due,created) VALUES(?,?,?,?)', (kind, text, due, time.time()))

    def items(self, include_done=False):
        sql = 'SELECT * FROM items' + ('' if include_done else ' WHERE done=0') + ' ORDER BY (due IS NULL), due, id'
        return self.q(sql)

    def item(self, item_id):
        rows = self.q('SELECT * FROM items WHERE id=?', (int(item_id),))
        return rows[0] if rows else None

    def find_items(self, match, kinds=KINDS):
        words = [w for w in str(match or '').lower().split() if len(w) > 2]
        return [i for i in self.items() if i['kind'] in kinds and words and all(w in i['text'].lower() for w in words)]

    def complete_item(self, item_id):
        self.q('UPDATE items SET done=1, announced=1 WHERE id=?', (int(item_id),))

    def delete_item(self, item_id):
        self.q('DELETE FROM items WHERE id=?', (int(item_id),))

    def due_alerts(self, now=None):
        """Timers/reminders whose time has come and that nobody has been told about yet."""
        now = now or time.time()
        return self.q('SELECT * FROM items WHERE done=0 AND announced=0 AND due IS NOT NULL AND due<=? ORDER BY due', (now,))

    def acknowledge(self, item_id):
        item = self.item(item_id)
        if item and item['kind'] == 'timer':
            self.q('UPDATE items SET announced=1, done=1 WHERE id=?', (item['id'],))
        elif item:
            self.q('UPDATE items SET announced=1 WHERE id=?', (item['id'],))
