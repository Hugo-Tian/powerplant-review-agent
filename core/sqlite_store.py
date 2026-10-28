"""SQLite persistence for the local demo; one connection per operation."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    event_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    level TEXT NOT NULL CHECK(level IN ('一般','重要','紧急','建议')),
    order_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS predictions (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id TEXT NOT NULL UNIQUE,
    event_id TEXT NOT NULL REFERENCES orders(event_id),
    user_id TEXT NOT NULL,
    score REAL NOT NULL CHECK(score BETWEEN 0 AND 1),
    confidence REAL CHECK(confidence BETWEEN 0 AND 1),
    push_type TEXT NOT NULL CHECK(push_type IN ('emergency','personal','device_group')),
    model_version TEXT NOT NULL,
    predicted_at TEXT NOT NULL,
    request_json TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_predictions_order ON predictions(event_id, sequence);
CREATE INDEX IF NOT EXISTS idx_predictions_user ON predictions(user_id, event_id, sequence);
CREATE TABLE IF NOT EXISTS feedback (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_id TEXT NOT NULL UNIQUE,
    prediction_id TEXT NOT NULL REFERENCES predictions(prediction_id),
    action TEXT NOT NULL CHECK(action IN ('confirm','correct')),
    reviewer TEXT NOT NULL,
    comment TEXT NOT NULL,
    corrected_score REAL CHECK(corrected_score BETWEEN 0 AND 1),
    corrected_push_type TEXT CHECK(corrected_push_type IN ('emergency','personal','device_group')),
    created_at TEXT NOT NULL,
    CHECK((action = 'confirm' AND corrected_score IS NULL AND corrected_push_type IS NULL)
       OR (action = 'correct' AND (corrected_score IS NOT NULL OR corrected_push_type IS NOT NULL)))
);
CREATE INDEX IF NOT EXISTS idx_feedback_prediction ON feedback(prediction_id, sequence);
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT '',
    responsible_units TEXT NOT NULL DEFAULT '[]',
    base_profile_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS behaviors (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    behavior_id TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL REFERENCES users(user_id),
    action_type TEXT NOT NULL,
    event_id TEXT,
    query_content TEXT,
    stay_sec REAL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_behaviors_user ON behaviors(user_id, occurred_at);
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS term_candidates (
    term TEXT NOT NULL,
    category TEXT NOT NULL,
    hits INTEGER NOT NULL,
    example_span TEXT NOT NULL,
    last_event_id TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','rejected')),
    PRIMARY KEY (term, category)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings_history (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    value_json TEXT,
    reviewer TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS custom_terms (
    term TEXT NOT NULL,
    category TEXT NOT NULL,
    code TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (term, category)
);
CREATE TABLE IF NOT EXISTS agent_runs (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    prediction_id TEXT NOT NULL REFERENCES predictions(prediction_id),
    user_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    status TEXT NOT NULL,
    recommendation TEXT,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_prediction ON agent_runs(prediction_id, sequence);
CREATE TABLE IF NOT EXISTS profiles (
    user_id TEXT PRIMARY KEY REFERENCES users(user_id),
    profile_json TEXT NOT NULL,
    behavior_count INTEGER NOT NULL,
    computed_at TEXT NOT NULL
);
"""

INTEREST_BUCKETS = ('device_interests', 'mfr_interests', 'fault_interests', 'keyword_interests')


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


class SQLiteOrderStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def save(self, request, result):
        order = request['order']
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute("""INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET title=excluded.title,
                content=excluded.content, level=excluded.level,
                order_json=excluded.order_json, updated_at=excluded.updated_at""",
                (order['event_id'], order['title'], order['content'], order['level'], encode(order), now, now))
            conn.execute("""INSERT INTO predictions
                (prediction_id,event_id,user_id,score,confidence,push_type,model_version,
                 predicted_at,request_json,result_json) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (result['prediction_id'], order['event_id'], result['user_id'], result['score'],
                 result['confidence'], result['push_type'], result['model_version'],
                 result['predicted_at'], encode(request), encode(result)))

    def feedback(self, prediction_id, body):
        record = dict(body, feedback_id=str(uuid4()), prediction_id=prediction_id,
                      created_at=datetime.now(timezone.utc).isoformat())
        with self.connection() as conn:
            if conn.execute('SELECT 1 FROM predictions WHERE prediction_id=?', (prediction_id,)).fetchone() is None:
                raise KeyError(prediction_id)
            conn.execute("""INSERT INTO feedback
                (feedback_id,prediction_id,action,reviewer,comment,corrected_score,corrected_push_type,created_at)
                VALUES (?,?,?,?,?,?,?,?)""", tuple(record[k] for k in (
                    'feedback_id','prediction_id','action','reviewer','comment',
                    'corrected_score','corrected_push_type','created_at')))
        return record

    def list(self, user_id, offset, limit):
        where = 'WHERE user_id=?' if user_id is not None else ''
        params = (user_id,) if user_id is not None else ()
        with self.connection() as conn:
            # Use a consistent read snapshot for count, page and histories.
            conn.execute('BEGIN')
            total = conn.execute(f'SELECT COUNT(DISTINCT event_id) FROM predictions {where}', params).fetchone()[0]
            page = conn.execute(f"""SELECT event_id, MAX(sequence) AS latest
                FROM predictions {where} GROUP BY event_id ORDER BY latest DESC LIMIT ? OFFSET ?""",
                (*params, limit, offset)).fetchall()
            items = []
            for row in page:
                history_rows = conn.execute('SELECT * FROM predictions WHERE event_id=?'
                    + (' AND user_id=?' if user_id is not None else '') + ' ORDER BY sequence',
                    (row['event_id'], *params)).fetchall()
                history = []
                for prediction in history_rows:
                    reviews = conn.execute('SELECT * FROM feedback WHERE prediction_id=? ORDER BY sequence',
                                           (prediction['prediction_id'],)).fetchall()
                    feedback = [{k: r[k] for k in r.keys() if k != 'sequence'} for r in reviews]
                    history.append(dict(**json.loads(prediction['request_json']),
                                        result=json.loads(prediction['result_json']), feedback=feedback))
                latest = history[-1]
                # Reviews apply only to the specific prediction. A later prediction is pending again.
                review = latest['feedback'][-1] if latest['feedback'] else None
                effective = dict(score=latest['result']['score'], push_type=latest['result']['push_type'],
                                 source='model', review_status='pending')
                if review:
                    effective.update(source='human', review_status=review['action'])
                    for field in ('score', 'push_type'):
                        value = review['corrected_' + field]
                        if value is not None:
                            effective[field] = value
                run = conn.execute("""SELECT result_json, created_at, run_id FROM agent_runs WHERE prediction_id=?
                    ORDER BY sequence DESC LIMIT 1""", (latest['result']['prediction_id'],)).fetchone()
                agent = None
                if run:
                    r = json.loads(run['result_json'])
                    agent = {k: r.get(k) for k in ('status', 'recommendation', 'recommendation_label',
                                                    'suggested_score', 'confidence')}
                    agent.update(run_id=run['run_id'], created_at=run['created_at'])
                items.append(dict(order=latest['order'], latest_prediction=latest['result'],
                                  history=history, latest_feedback=review, effective_result=effective,
                                  agent_review=agent))
        return dict(items=items, total=total, offset=offset, limit=limit, storage='sqlite')

    # ── 用户、行为与画像（原 PostgreSQL 模块 2/3 的 SQLite 版） ──────────────

    @staticmethod
    def _user_row(row):
        base = json.loads(row['base_profile_json'])
        return dict(user_id=row['user_id'], name=row['name'], role=row['role'],
                    responsible_units=json.loads(row['responsible_units']),
                    **{b: base.get(b, {}) for b in INTEREST_BUCKETS},
                    created_at=row['created_at'], updated_at=row['updated_at'])

    def upsert_user(self, user, *, overwrite=True):
        """Create or update a user. Base interests act as the profile floor."""
        now = datetime.now(timezone.utc).isoformat()
        base = encode({b: user.get(b) or {} for b in INTEREST_BUCKETS})
        values = (user['user_id'], user.get('name') or '', user.get('role') or '',
                  encode(list(user.get('responsible_units') or [])), base, now, now)
        with self.connection() as conn:
            if overwrite:
                conn.execute("""INSERT INTO users VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, role=excluded.role,
                    responsible_units=excluded.responsible_units,
                    base_profile_json=excluded.base_profile_json, updated_at=excluded.updated_at""", values)
                conn.execute('DELETE FROM profiles WHERE user_id=?', (user['user_id'],))
            else:
                conn.execute('INSERT OR IGNORE INTO users VALUES (?,?,?,?,?,?,?)', values)
        return self.get_user(user['user_id'])

    def get_user(self, user_id):
        with self.connection() as conn:
            row = conn.execute('SELECT * FROM users WHERE user_id=?', (user_id,)).fetchone()
        return self._user_row(row) if row else None

    def list_users(self):
        with self.connection() as conn:
            rows = conn.execute('SELECT * FROM users ORDER BY created_at, user_id').fetchall()
        return [self._user_row(r) for r in rows]

    def event_tags(self, event_id, user_id=None):
        """Tags from the latest stored prediction of an order (prefer this user's)."""
        with self.connection() as conn:
            row = None
            if user_id is not None:
                row = conn.execute("""SELECT result_json FROM predictions WHERE event_id=? AND user_id=?
                    ORDER BY sequence DESC LIMIT 1""", (event_id, user_id)).fetchone()
            if row is None:
                row = conn.execute("""SELECT result_json FROM predictions WHERE event_id=?
                    ORDER BY sequence DESC LIMIT 1""", (event_id,)).fetchone()
        if row is None:
            return None
        return [{'code': t['code'], 'category': t.get('category')} for t in json.loads(row['result_json'])['tags']]

    def add_behavior(self, body):
        if self.get_user(body['user_id']) is None:
            raise KeyError(body['user_id'])
        tags = body.get('tags')
        if not tags and body.get('event_id'):
            tags = self.event_tags(body['event_id'], body['user_id']) or []
        now = datetime.now(timezone.utc).isoformat()
        record = dict(behavior_id=str(uuid4()), user_id=body['user_id'], action_type=body['action_type'],
                      event_id=body.get('event_id'), query_content=body.get('query_content'),
                      stay_sec=body.get('stay_sec'), tags=tags or [],
                      occurred_at=body.get('occurred_at') or now, created_at=now)
        with self.connection() as conn:
            conn.execute("""INSERT INTO behaviors (behavior_id,user_id,action_type,event_id,query_content,
                stay_sec,tags_json,occurred_at,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                (record['behavior_id'], record['user_id'], record['action_type'], record['event_id'],
                 record['query_content'], record['stay_sec'], encode(record['tags']),
                 record['occurred_at'], now))
            conn.execute('DELETE FROM profiles WHERE user_id=?', (body['user_id'],))
        return record

    def list_behaviors(self, user_id, days=None, limit=None):
        sql, params = 'SELECT * FROM behaviors WHERE user_id=?', [user_id]
        if days is not None:
            sql += ' AND occurred_at >= ?'
            params.append((datetime.now(timezone.utc) - timedelta(days=days)).isoformat())
        sql += ' ORDER BY occurred_at DESC, sequence DESC'
        if limit is not None:
            sql += ' LIMIT ?'
            params.append(limit)
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(behavior_id=r['behavior_id'], user_id=r['user_id'], action_type=r['action_type'],
                     event_id=r['event_id'], query_content=r['query_content'], stay_sec=r['stay_sec'],
                     tags=json.loads(r['tags_json']), occurred_at=r['occurred_at'],
                     created_at=r['created_at']) for r in rows]

    def save_profile(self, profile, behavior_count):
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute("""INSERT INTO profiles VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                profile_json=excluded.profile_json, behavior_count=excluded.behavior_count,
                computed_at=excluded.computed_at""", (profile['user_id'], encode(profile), behavior_count, now))
        return dict(profile=profile, behavior_count=behavior_count, computed_at=now)

    def cached_profile(self, user_id):
        with self.connection() as conn:
            row = conn.execute('SELECT * FROM profiles WHERE user_id=?', (user_id,)).fetchone()
        if row is None:
            return None
        return dict(profile=json.loads(row['profile_json']), behavior_count=row['behavior_count'],
                    computed_at=row['computed_at'])

    def all_orders(self):
        with self.connection() as conn:
            rows = conn.execute('SELECT order_json FROM orders ORDER BY created_at, event_id').fetchall()
        return [json.loads(r['order_json']) for r in rows]

    def latest_result(self, user_id, event_id):
        with self.connection() as conn:
            row = conn.execute("""SELECT result_json FROM predictions WHERE user_id=? AND event_id=?
                ORDER BY sequence DESC LIMIT 1""", (user_id, event_id)).fetchone()
        return json.loads(row['result_json']) if row else None

    # ── 大模型结果缓存与新词候选 ─────────────────────────────────────────────

    def llm_cache_get(self, key):
        with self.connection() as conn:
            row = conn.execute('SELECT value_json FROM llm_cache WHERE cache_key=?', (key,)).fetchone()
        return json.loads(row['value_json']) if row else None

    def llm_cache_set(self, key, value):
        with self.connection() as conn:
            conn.execute('INSERT OR REPLACE INTO llm_cache VALUES (?,?,?)',
                         (key, encode(value), datetime.now(timezone.utc).isoformat()))

    def llm_cache_count(self):
        with self.connection() as conn:
            return conn.execute('SELECT COUNT(*) FROM llm_cache').fetchone()[0]

    def add_term_candidates(self, event_id, terms):
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            for t in terms:
                conn.execute("""INSERT INTO term_candidates
                    (term,category,hits,example_span,last_event_id,first_seen,last_seen)
                    VALUES (?,?,1,?,?,?,?) ON CONFLICT(term,category) DO UPDATE SET
                    hits = hits + (excluded.last_event_id != term_candidates.last_event_id),
                    last_event_id=excluded.last_event_id, last_seen=excluded.last_seen""",
                    (t['term'], t['category'], t['span'], event_id, now, now))

    def list_term_candidates(self, status=None):
        sql = 'SELECT * FROM term_candidates'
        params = ()
        if status:
            sql += ' WHERE status=?'
            params = (status,)
        sql += ' ORDER BY hits DESC, last_seen DESC'
        with self.connection() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    # ── 相似检索、人工结论、设置 ──────────────────────────────────────────

    def orders_version(self):
        with self.connection() as conn:
            row = conn.execute('SELECT COUNT(*) AS n, MAX(updated_at) AS t FROM orders').fetchone()
            seq = conn.execute('SELECT MAX(sequence) FROM predictions').fetchone()[0]
        return (row['n'], row['t'], seq)

    def latest_tags_by_event(self):
        """event_id -> set of tag codes from the latest prediction of each order."""
        with self.connection() as conn:
            rows = conn.execute("""SELECT p.event_id, p.result_json FROM predictions p
                JOIN (SELECT event_id, MAX(sequence) AS s FROM predictions GROUP BY event_id) m
                ON m.event_id = p.event_id AND m.s = p.sequence""").fetchall()
        return {r['event_id']: {t['code'] for t in json.loads(r['result_json'])['tags']} for r in rows}

    def feedback_summary(self, event_ids, user_id=None, exclude_user=None):
        """Human review outcome per order. ``user_id``: only reviews of that user's pushes;
        ``exclude_user``: only reviews of other users' pushes."""
        if not event_ids:
            return {}
        marks = ','.join('?' * len(event_ids))
        where, params = '', list(event_ids)
        if user_id is not None:
            where, params = ' AND p.user_id=?', params + [user_id]
        elif exclude_user is not None:
            where, params = ' AND p.user_id<>?', params + [exclude_user]
        with self.connection() as conn:
            rows = conn.execute(f"""SELECT p.event_id, p.user_id, p.score AS model_score, f.action,
                    f.corrected_score, f.corrected_push_type, f.comment, f.reviewer, f.created_at
                FROM feedback f JOIN predictions p ON p.prediction_id = f.prediction_id
                WHERE p.event_id IN ({marks}){where} ORDER BY f.sequence""", tuple(params)).fetchall()
        out = {}
        for r in rows:
            s = out.setdefault(r['event_id'], {'confirm': 0, 'correct': 0, 'latest': None})
            s[r['action']] += 1
            s['latest'] = {k: r[k] for k in ('user_id', 'action', 'model_score', 'corrected_score',
                                               'corrected_push_type', 'comment', 'reviewer', 'created_at')}
        return out

    def get_prediction(self, prediction_id):
        with self.connection() as conn:
            row = conn.execute('SELECT request_json, result_json FROM predictions WHERE prediction_id=?',
                               (prediction_id,)).fetchone()
        if row is None:
            return None
        return dict(request=json.loads(row['request_json']), result=json.loads(row['result_json']))

    # ── 反馈学习（第 5 步） ───────────────────────────────────────────────

    def reviewed_samples(self, user_id=None):
        """Each prediction that has feedback, with its latest feedback."""
        where = 'AND p.user_id=?' if user_id else ''
        params = (user_id,) if user_id else ()
        with self.connection() as conn:
            rows = conn.execute(f"""SELECT p.request_json, p.result_json, f.action, f.corrected_score,
                    f.corrected_push_type, f.comment, f.reviewer, f.created_at, f.feedback_id
                FROM predictions p JOIN feedback f ON f.prediction_id = p.prediction_id
                WHERE f.sequence = (SELECT MAX(sequence) FROM feedback WHERE prediction_id = p.prediction_id)
                {where} ORDER BY p.sequence""", params).fetchall()
        out = []
        for r in rows:
            req = json.loads(r['request_json'])
            out.append(dict(order=req['order'], profile=req['profile'], result=json.loads(r['result_json']),
                            feedback={k: r[k] for k in ('feedback_id', 'action', 'corrected_score',
                                                         'corrected_push_type', 'comment', 'reviewer',
                                                         'created_at')}))
        return out

    def get_setting(self, key):
        with self.connection() as conn:
            row = conn.execute('SELECT value_json, updated_at FROM settings WHERE key=?', (key,)).fetchone()
        return (json.loads(row['value_json']), row['updated_at']) if row else (None, None)

    def set_setting(self, key, value, reviewer, note=''):
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            if value is None:
                conn.execute('DELETE FROM settings WHERE key=?', (key,))
            else:
                conn.execute('INSERT OR REPLACE INTO settings VALUES (?,?,?)', (key, encode(value), now))
            conn.execute('INSERT INTO settings_history (key,value_json,reviewer,note,created_at) VALUES (?,?,?,?,?)',
                         (key, None if value is None else encode(value), reviewer, note, now))

    def setting_history(self, key, limit=20):
        with self.connection() as conn:
            rows = conn.execute('SELECT * FROM settings_history WHERE key=? ORDER BY sequence DESC LIMIT ?',
                                (key, limit)).fetchall()
        return [dict(value=json.loads(r['value_json']) if r['value_json'] else None, reviewer=r['reviewer'],
                     note=r['note'], created_at=r['created_at']) for r in rows]

    def review_term(self, term, category, status, reviewer, code=None):
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cur = conn.execute('UPDATE term_candidates SET status=? WHERE term=? AND category=?',
                               (status, term, category))
            if cur.rowcount == 0:
                raise KeyError(term)
            if status == 'accepted':
                conn.execute('INSERT OR REPLACE INTO custom_terms VALUES (?,?,?,?,?)',
                             (term, category, code, reviewer, now))
            else:
                conn.execute('DELETE FROM custom_terms WHERE term=? AND category=?', (term, category))

    def custom_terms(self):
        with self.connection() as conn:
            return [dict(r) for r in conn.execute('SELECT * FROM custom_terms ORDER BY created_at').fetchall()]

    def latest_results(self):
        """(user_id, event_id) -> latest prediction result."""
        with self.connection() as conn:
            rows = conn.execute("""SELECT p.user_id, p.event_id, p.result_json FROM predictions p
                JOIN (SELECT user_id, event_id, MAX(sequence) AS s FROM predictions GROUP BY user_id, event_id) m
                ON m.user_id = p.user_id AND m.event_id = p.event_id AND m.s = p.sequence""").fetchall()
        return {(r['user_id'], r['event_id']): json.loads(r['result_json']) for r in rows}

    # ── 审核助手 Agent 运行记录 ─────────────────────────────────────────────

    def save_agent_run(self, prediction_id, user_id, event_id, result):
        record = dict(result, run_id=str(uuid4()), prediction_id=prediction_id,
                      created_at=datetime.now(timezone.utc).isoformat())
        with self.connection() as conn:
            conn.execute("""INSERT INTO agent_runs (run_id,prediction_id,user_id,event_id,status,recommendation,
                result_json,created_at) VALUES (?,?,?,?,?,?,?,?)""",
                (record['run_id'], prediction_id, user_id, event_id, record['status'],
                 record.get('recommendation'), encode(record), record['created_at']))
        return record

    def latest_agent_run(self, prediction_id):
        with self.connection() as conn:
            row = conn.execute("""SELECT result_json FROM agent_runs WHERE prediction_id=?
                ORDER BY sequence DESC LIMIT 1""", (prediction_id,)).fetchone()
        return json.loads(row['result_json']) if row else None

    def agent_run_stats(self, user_id=None):
        sql = 'SELECT status, recommendation, COUNT(*) AS n FROM agent_runs'
        params = ()
        if user_id:
            sql += ' WHERE user_id=?'
            params = (user_id,)
        with self.connection() as conn:
            return [dict(r) for r in conn.execute(sql + ' GROUP BY 1,2', params).fetchall()]
