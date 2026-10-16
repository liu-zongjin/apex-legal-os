"""Lossless, explicit repair of orphan rows and repeatable health schema."""
from __future__ import annotations

import base64
import datetime as dt
import json
import sqlite3

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, Response


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


def ensure_health_schema(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS integrity_recovery_records(
            id INTEGER PRIMARY KEY, source_table TEXT NOT NULL, original_rowid INTEGER NOT NULL,
            row_json TEXT NOT NULL, reason_json TEXT NOT NULL, created_at TEXT NOT NULL,
            restored_at TEXT, restored_row_json TEXT,
            UNIQUE(source_table,original_rowid));
        CREATE TABLE IF NOT EXISTS case_manager_maintenance(key TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS health_revisions(key TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0);
        INSERT OR IGNORE INTO health_revisions(key,revision) VALUES('relations',0);
    ''')


def install_relation_revisions(conn):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ('articles', 'notes', 'knowledge_issues', 'knowledge_nodes',
                  'knowledge_node_aliases', 'knowledge_claims', 'knowledge_claim_evidence',
                  'knowledge_claim_issues', 'article_paragraphs', 'national_law_articles'):
        if table not in tables:
            continue
        for action in ('INSERT', 'UPDATE', 'DELETE'):
            conn.execute(f'''CREATE TRIGGER IF NOT EXISTS {quoted('health_rel_' + table + '_' + action.lower())}
                AFTER {action} ON {quoted(table)} BEGIN
                UPDATE health_revisions SET revision=revision+1 WHERE key='relations'; END''')


def encode_row(row):
    return json.dumps({k: {'__bytes__': base64.b64encode(v).decode('ascii')} if isinstance(v, bytes) else v
                       for k, v in dict(row).items()}, ensure_ascii=False)


def decode_row(value):
    data = json.loads(value)
    return {k: base64.b64decode(v['__bytes__']) if isinstance(v, dict) and set(v) == {'__bytes__'} else v
            for k, v in data.items()}


def preserve_orphans(conn):
    """Requires a caller-created backup. Store all cascading descendants first.

    No invented parent rows, no silent reattachment, and no user text discarded.
    The transaction atomically moves invalid records into a reviewable archive.
    """
    ensure_health_schema(conn)
    conn.commit()
    conn.row_factory = sqlite3.Row
    conn.execute('BEGIN IMMEDIATE')
    try:
        violations = list(conn.execute('PRAGMA foreign_key_check'))
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        inbound = {}
        for table in tables:
            for fk in conn.execute('PRAGMA foreign_key_list(' + quoted(table) + ')'):
                inbound.setdefault(fk['table'], []).append((table, dict(fk)))
        pending = [(r['table'], r['rowid'], [{'parent_table': r['parent'], 'fkid': r['fkid']}]) for r in violations]
        captured = {}
        while pending:
            table, rowid, reason = pending.pop()
            if (table, rowid) in captured:
                continue
            if len(captured) >= 10000:
                raise ValueError('恢复记录超过安全上限，已回滚；需要分批核验')
            row = conn.execute('SELECT rowid AS __health_rowid__,* FROM ' + quoted(table) + ' WHERE rowid=?', (rowid,)).fetchone()
            if row is None:
                continue
            data = dict(row); data.pop('__health_rowid__')
            captured[table, rowid] = (data, reason)
            for child, fk in inbound.get(table, []):
                # Composite references require the entire row preserved too;
                # over-preserving is preferable to losing a cascading child.
                parent_key = fk['to'] or 'id'
                if parent_key in data:
                    for descendant in conn.execute('SELECT rowid FROM ' + quoted(child) + ' WHERE ' + quoted(fk['from']) + '=?', (data[parent_key],)):
                        pending.append((child, descendant[0], [{'parent_table': table, 'fkid': fk['id']}]))
        stamp = dt.datetime.now(dt.timezone.utc).isoformat()
        for (table, rowid), (data, reason) in captured.items():
            # Existing active archives must match exactly; never overwrite an
            # earlier preserved version if an ID has been reused.
            old = conn.execute('SELECT row_json,restored_at FROM integrity_recovery_records WHERE source_table=? AND original_rowid=?', (table, rowid)).fetchone()
            if old and (old['restored_at'] or decode_row(old['row_json']) != data):
                raise ValueError('恢复区存在同编号的其他版本，已回滚')
            conn.execute('INSERT OR IGNORE INTO integrity_recovery_records(source_table,original_rowid,row_json,reason_json,created_at) VALUES(?,?,?,?,?)',
                         (table, rowid, encode_row(data), json.dumps(reason), stamp))
        # Cascades are safe: every reachable child was copied in the same tx.
        for table, rowid in captured:
            conn.execute('DELETE FROM ' + quoted(table) + ' WHERE rowid=?', (rowid,))
        if list(conn.execute('PRAGMA foreign_key_check')):
            raise ValueError('引用仍有异常，已回滚所有变更')
        conn.commit()
        counts = {}
        for table, _ in captured:
            counts[table] = counts.get(table, 0) + 1
        return {'preserved': len(captured), 'by_table': counts, 'remaining_violations': 0}
    except BaseException:
        conn.rollback()
        raise


def restore_record(conn, identity, parent_id):
    conn.row_factory = sqlite3.Row
    record = conn.execute('SELECT * FROM integrity_recovery_records WHERE id=? AND restored_at IS NULL', (identity,)).fetchone()
    if record is None:
        raise HTTPException(404, '恢复记录不存在或已经恢复')
    table = record['source_table']; data = decode_row(record['row_json'])
    missing = []
    for fk in conn.execute('PRAGMA foreign_key_list(' + quoted(table) + ')'):
        value = data.get(fk['from'])
        if value is not None and not conn.execute('SELECT 1 FROM ' + quoted(fk['table']) + ' WHERE ' + quoted(fk['to'] or 'id') + '=?', (value,)).fetchone():
            missing.append(dict(fk))
    if len(missing) > 1:
        raise HTTPException(409, '需先恢复依赖记录，或由维护工具核验多重引用')
    if missing:
        fk = missing[0]
        if parent_id is None or parent_id < 1 or not conn.execute('SELECT 1 FROM ' + quoted(fk['table']) + ' WHERE ' + quoted(fk['to'] or 'id') + '=?', (parent_id,)).fetchone():
            raise HTTPException(400, '指定的父记录不存在')
        data[fk['from']] = parent_id
    elif parent_id is not None:
        raise HTTPException(409, '原关联已完整，请沿用原关联恢复')
    keys = list(data)
    try:
        conn.execute('INSERT INTO ' + quoted(table) + '(' + ','.join(map(quoted, keys)) + ') VALUES(' + ','.join('?' for _ in keys) + ')', [data[k] for k in keys])
        conn.execute('UPDATE integrity_recovery_records SET restored_at=?,restored_row_json=? WHERE id=?',
                     (dt.datetime.now(dt.timezone.utc).isoformat(), encode_row(data), identity))
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise HTTPException(409, '编号冲突或引用未满足；原记录仍完整保留') from exc
    return {'ok': True}


def register_recovery_routes(app, get_db, frontend_dir):
    @app.get('/data-recovery')
    def recovery_page():
        return HTMLResponse((frontend_dir / 'data-recovery.html').read_text(encoding='utf-8'), headers={'Cache-Control':'no-store'})

    @app.get('/api/maintenance/recovery')
    def recovery_records():
        with get_db() as conn:
            rows = conn.execute('SELECT * FROM integrity_recovery_records ORDER BY id DESC LIMIT 1000').fetchall()
            return {'items':[dict(r) for r in rows]}

    @app.get('/api/maintenance/recovery/export')
    def export_recovery():
        with get_db() as conn:
            rows = [dict(r) for r in conn.execute('SELECT * FROM integrity_recovery_records ORDER BY id')]
        return Response(json.dumps({'version':1,'records':rows}, ensure_ascii=False, indent=2), media_type='application/json',
                        headers={'Content-Disposition':'attachment; filename="Stella-preserved-records.json"','Cache-Control':'no-store'})

    @app.get('/api/maintenance/recovery/{identity}/parents')
    def recovery_parents(identity: int, q: str = ''):
        with get_db() as conn:
            record = conn.execute('SELECT * FROM integrity_recovery_records WHERE id=? AND restored_at IS NULL', (identity,)).fetchone()
            if record is None:
                raise HTTPException(404, '保全记录不存在')
            data = decode_row(record['row_json'])
            missing = []
            for fk in conn.execute('PRAGMA foreign_key_list(' + quoted(record['source_table']) + ')'):
                value = data.get(fk['from'])
                if value is not None and not conn.execute('SELECT 1 FROM ' + quoted(fk['table']) + ' WHERE ' + quoted(fk['to'] or 'id') + '=?', (value,)).fetchone():
                    missing.append(dict(fk))
            if len(missing) != 1:
                return {'items':[], 'parent_type':'需先恢复关联记录'}
            fk = missing[0]; table = fk['table']; key = fk['to'] or 'id'
            columns = {r[1] for r in conn.execute('PRAGMA table_info(' + quoted(table) + ')')}
            label = next((c for c in ('title','name','content','statement') if c in columns), key)
            query = str(q)[:100].replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
            rows = conn.execute('SELECT ' + quoted(key) + ' AS id,substr(' + quoted(label) + ',1,180) AS title FROM ' + quoted(table)
                + ' WHERE CAST(' + quoted(label) + " AS TEXT) LIKE ? ESCAPE '\\' ORDER BY " + quoted(key) + ' DESC LIMIT 30', ('%'+query+'%',)).fetchall()
            return {'items':[dict(r) for r in rows], 'parent_type':{'articles':'文章','research_projects':'研究项目','case_manager_cases':'案件','notes':'笔记'}.get(table,'关联记录')}

    @app.post('/api/maintenance/recovery/{identity}/restore')
    async def restore_recovery(identity: int, request: Request):
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(400, '无效的恢复请求')
        try:
            value = payload.get('parent_id')
            if value is None:
                parent_id = None
            else:
                if not str(value).isdigit(): raise ValueError('invalid parent')
                parent_id = int(value)
        except (TypeError, ValueError):
            raise HTTPException(400, '请填写有效的父记录编号')
        with get_db() as conn:
            return restore_record(conn, identity, parent_id)
