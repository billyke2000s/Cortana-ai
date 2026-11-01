"""Cortana's local storage on this PC (SQLite): settings, remembered facts, conversation log, timers, reminders and tasks."""
import sqlite3, threading, time, json, re, math, uuid

SCHEMA = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY, text TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, role TEXT NOT NULL, content TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS items(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, text TEXT NOT NULL, due REAL,
  done INTEGER NOT NULL DEFAULT 0, announced INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, path TEXT, pages INTEGER, chars INTEGER NOT NULL, summary TEXT, added REAL NOT NULL);
CREATE TABLE IF NOT EXISTS doc_chunks(doc_id INTEGER NOT NULL, idx INTEGER NOT NULL, page TEXT, text TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS doc_chunks_doc ON doc_chunks(doc_id);
CREATE TABLE IF NOT EXISTS agent_records(id TEXT PRIMARY KEY, kind TEXT NOT NULL, data TEXT NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, title TEXT NOT NULL, start REAL NOT NULL, end REAL NOT NULL, created REAL NOT NULL);
'''
MAX_DOCUMENTS = 200
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
            if 'notified' not in {r[1] for r in self.db.execute('PRAGMA table_info(items)')}:
                self.db.execute('ALTER TABLE items ADD COLUMN notified INTEGER NOT NULL DEFAULT 0')
            self.db.commit()

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

    def edit_fact(self,fact_id,text):
        text=' '.join(str(text).split())[:300]
        if not text:raise ValueError('Nothing to remember.')
        if not self.q('SELECT id FROM facts WHERE id=?',(int(fact_id),)):raise ValueError('That memory no longer exists.')
        self.q('UPDATE facts SET text=?,created=? WHERE id=?',(text,time.time(),int(fact_id)))

    def relevant_facts(self,query,limit=12,budget=1800):
        stop={'the','and','what','with','that','this','about','have','does','from','your','please','user'}
        words=lambda t:set(w for w in re.findall(r"[a-z0-9']+",t.lower()) if len(w)>2 and w not in stop)
        wanted=words(query);facts=self.facts()
        counts={w:sum(w in words(f['text']) for f in facts) for w in wanted}
        score=lambda f:sum(math.log(1+len(facts)/(1+counts[w])) for w in wanted & words(f['text']))
        output=[]
        for f in sorted(facts,key=lambda f:(score(f),f['created'],f['id']),reverse=True):
            if len(output)>=limit:break
            if len(f['text'])+2>budget:continue
            output.append(f);budget-=len(f['text'])+2
        return output

    def fact_conflicts(self):
        groups={}
        for f in self.facts():
            m=re.match(r"(.{3,90}?) (?:is|are|=) (.+)",f['text'],re.I)
            if m:groups.setdefault(m[1].lower().strip(),[]).append(f['id'])
        return [ids for ids in groups.values() if len(ids)>1]

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

    def conversation_version(self):return self.get('conversation_version',0)

    def log_exchange(self,user,assistant,version):
        # A reply completing after Clear History cannot bring the old conversation back.
        with self.lock:
            row=self.db.execute("SELECT value FROM settings WHERE key='conversation_version'").fetchone()
            if (json.loads(row[0]) if row else 0)!=version:return
            now=time.time()
            self.db.executemany('INSERT INTO messages(role,content,created) VALUES(?,?,?)',
                [('user',str(user)[:6000],now),('assistant',str(assistant)[:6000],now)])
            self.db.execute('DELETE FROM messages WHERE id NOT IN (SELECT id FROM messages ORDER BY id DESC LIMIT ?)',(MAX_MESSAGES,))
            self.db.commit()

    def clear_messages(self):
        with self.lock:
            row=self.db.execute("SELECT value FROM settings WHERE key='conversation_version'").fetchone()
            version=(json.loads(row[0]) if row else 0)+1
            self.db.execute('DELETE FROM messages')
            self.db.execute("INSERT INTO settings(key,value) VALUES('conversation_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(version),))
            self.db.commit()

    def conversation_summary(self,budget=800):
        rows=self.q('SELECT role,content FROM messages ORDER BY id DESC LIMIT 30 OFFSET 16')
        lines=[];size=0
        for m in rows:
            text=' '.join(m['content'].split('[[SCREEN]]')[0].split())[:130]
            line=m['role']+': '+text
            if size+len(line)+1>budget:break
            lines.append(line);size+=len(line)+1
        return '\n'.join(reversed(lines))

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

    def snooze(self,item_id,minutes=10):
        minutes=float(minutes)
        if not math.isfinite(minutes) or not 1<=minutes<=1440:raise ValueError('Snooze for 1 to 1440 minutes.')
        item=self.item(item_id)
        if not item or item['kind'] not in ('timer','reminder'):raise ValueError('Choose a timer or reminder.')
        self.q('UPDATE items SET due=?,done=0,announced=0,notified=0 WHERE id=?',(time.time()+minutes*60,int(item_id)))

    def pending_notifications(self):
        return self.q('SELECT * FROM items WHERE done=0 AND announced=0 AND notified=0 AND due<=? ORDER BY due',(time.time(),))

    def mark_notified(self,item_id,due):
        self.q('UPDATE items SET notified=1 WHERE id=? AND due=?',(int(item_id),float(due)))

    def recent_alerts(self):
        return self.q("SELECT * FROM items WHERE kind='timer' AND announced=1 AND due>? ORDER BY due DESC LIMIT 20",(time.time()-86400,))

    # ---- documents the user added (text is stored in pieces for searching)
    def add_document(self, name, text, pieces, pages=None, path=None):
        """Store a document; re-adding the same name/path replaces it. Returns its id."""
        name = ' '.join(str(name).split())[:160] or 'Document'
        old = self.q('SELECT id FROM documents WHERE name=? OR (path IS NOT NULL AND path=?)', (name, path or ''))
        for d in old:
            self.remove_document(d['id'])
        did = self.insert('INSERT INTO documents(name,path,pages,chars,added) VALUES(?,?,?,?,?)',
                          (name, path, pages, len(text), time.time()))
        with self.lock:
            self.db.executemany('INSERT INTO doc_chunks(doc_id,idx,page,text) VALUES(?,?,?,?)',
                                [(did, i, page, t) for i, (page, t) in enumerate(pieces)])
            self.db.commit()
        extra = self.q('SELECT id FROM documents ORDER BY id DESC LIMIT -1 OFFSET ?', (MAX_DOCUMENTS,))
        for d in extra:
            self.remove_document(d['id'])
        return did

    def documents(self):
        return self.q('SELECT id,name,path,pages,chars,added,(summary IS NOT NULL) AS summarised FROM documents ORDER BY id DESC')

    def document(self, doc_id):
        rows = self.q('SELECT * FROM documents WHERE id=?', (int(doc_id),))
        return rows[0] if rows else None

    def find_document(self, match):
        """Best document for words like 'the brief' or 'chapter notes'; empty match = the most recent one."""
        docs = self.documents()
        words = [w for w in str(match or '').lower().replace('.', ' ').split() if len(w) > 2 and w not in ('the', 'this', 'that', 'document', 'file', 'pdf')]
        if not docs:
            return None
        if not words:
            return docs[0]
        scored = sorted(((sum(w in d['name'].lower() for w in words), -i, d) for i, d in enumerate(docs)), key=lambda x: (-x[0], -x[1]))
        return scored[0][2] if scored[0][0] else None

    def document_text(self, doc_id):
        return '\n\n'.join(r['text'] for r in self.q('SELECT text FROM doc_chunks WHERE doc_id=? ORDER BY idx', (int(doc_id),)))

    def document_chunks(self, doc_id=None):
        sql = 'SELECT c.doc_id, d.name AS doc, c.page, c.text FROM doc_chunks c JOIN documents d ON d.id=c.doc_id'
        return self.q(sql + (' WHERE c.doc_id=? ORDER BY c.idx' if doc_id else ' ORDER BY c.doc_id DESC, c.idx'), ((int(doc_id),) if doc_id else ()))

    def set_summary(self, doc_id, summary):
        self.q('UPDATE documents SET summary=? WHERE id=?', (str(summary)[:4000], int(doc_id)))

    def remove_document(self, doc_id):
        self.q('DELETE FROM doc_chunks WHERE doc_id=?', (int(doc_id),))
        self.q('DELETE FROM documents WHERE id=?', (int(doc_id),))

    # ---- calendar events kept by Cortana
    def add_event(self, title, start, end):
        title = ' '.join(str(title).split())[:160] or 'Event'
        return self.insert('INSERT INTO events(title,start,end,created) VALUES(?,?,?,?)', (title, float(start), float(end), time.time()))

    def events_between(self, lo, hi):
        return self.q('SELECT * FROM events WHERE start<? AND end>? ORDER BY start', (float(hi), float(lo)))

    def upcoming_events(self, limit=20):
        return self.q('SELECT * FROM events WHERE end>? ORDER BY start LIMIT ?', (time.time(), int(limit)))

    def remove_event(self, event_id):
        self.q('DELETE FROM events WHERE id=?', (int(event_id),))

    # Agent metadata is additive; credentials stay in settings and never enter these records.
    def agent_put(self,kind,data,record_id=None):
        record_id=record_id or uuid.uuid4().hex
        self.q('INSERT INTO agent_records(id,kind,data,updated) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data,updated=excluded.updated',
               (record_id,kind,json.dumps(data,default=str),time.time()))
        return record_id

    def agent_get(self,record_id,kind=None):
        rows=self.q('SELECT * FROM agent_records WHERE id=?',(str(record_id),))
        if not rows or (kind and rows[0]['kind']!=kind):return None
        return {'id':rows[0]['id'],**json.loads(rows[0]['data'])}

    def agent_list(self,kind,limit=100):
        return [{'id':r['id'],**json.loads(r['data'])} for r in self.q('SELECT * FROM agent_records WHERE kind=? ORDER BY updated DESC LIMIT ?',(kind,int(limit)))]

    def agent_artifact(self,path,name,size):
        return self.agent_put('artifact',{'path':path,'name':name,'bytes':size,'created':time.time()})
