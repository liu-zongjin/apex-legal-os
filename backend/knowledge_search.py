"""Disposable, local corpus index shared by article and verified-knowledge search.

Business SQLite is read-only here. A versioned sidecar holds segmented FTS5 and
chunk vectors; it can always be deleted and rebuilt. No implicit network calls.
"""
from __future__ import annotations

import hashlib
import heapq
import json
import os
import re
import sqlite3
import sys
import threading
import time
from pathlib import Path

from .case_embeddings import MODEL_SHA256, local_embeddings
from .case_hybrid import terms
from .legal_knowledge import article_processing_text

VERSION = 'knowledge-v1-' + MODEL_SHA256[:12]
# Loose candidate gate only: high BGE cosine does not establish relevance.
# The separate cross-encoder below checks semantic-only candidates before display.
MIN_DENSE_SIMILARITY = .50
FIELDS = ('title', 'summary', 'content')
KNOWLEDGE_FIELDS = ('issue_titles', 'statement', 'conditions_text', 'exceptions_text', 'source_titles')
LABELS = {'title': '标题', 'summary': '摘要', 'content': '正文', 'issue_titles': '争点',
          'statement': '规则结论', 'conditions_text': '适用条件', 'exceptions_text': '例外与限制', 'source_titles': '来源'}
_MANAGERS = {}
_LOCK = threading.Lock()


def is_exact_lookup(query):
    text = str(query or '').strip()
    # Identifiers and explicit quoted phrases remain literal lookups.
    return bool(
        re.fullmatch(r'[（(]\d{4}[）)].{1,24}?\d+号', text)
        or re.fullmatch(r'.{1,80}第[一二三四五六七八九十百千万零〇\d]+条(?:之[一二三四五六七八九十\d]+)?', text)
        or (len(text) > 2 and (text[0], text[-1]) in {('"', '"'), ('“', '”')})
    )


def supports_semantics(query):
    return len(str(query or '').strip()) >= 3 and not is_exact_lookup(query)


def plain_text(value):
    return article_processing_text(value)


def document_fields(row, kind):
    return {field: plain_text(row.get(field)) for field in (FIELDS if kind == 'article' else KNOWLEDGE_FIELDS)}


def fingerprint(fields):
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def passages(fields):
    for field, text in fields.items():
        for start in range(0, len(text), 180):
            excerpt = text[start:start + 220]
            if excerpt.strip():
                yield field, start, excerpt
            if start + 220 >= len(text):
                break


def cache_directory():
    if os.environ.get('STELLA_SEARCH_CACHE_DIR'):
        return Path(os.environ['STELLA_SEARCH_CACHE_DIR']).expanduser()
    root = Path.home() / 'Library' / 'Caches' if sys.platform == 'darwin' else Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.cache')))
    return root / 'Stella' / 'knowledge-search'


class CorpusIndex:
    def __init__(self, db_path, cache_root=None, encoder=None, reranker=None):
        self.db_path = Path(db_path).resolve()
        key = hashlib.sha256((str(self.db_path) + VERSION).encode()).hexdigest()[:24]
        self.path = Path(cache_root or cache_directory()) / (key + '.sqlite3')
        self.encoder = encoder or local_embeddings
        if reranker is None and encoder is None:
            from .knowledge_reranker import relevance_scores
            self.reranker = relevance_scores
        else:
            self.reranker = reranker
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.thread = None
        self.last_run = 0.0
        self.dirty = True
        self.error = ''
        self.vector_error = ''
        self.processed = 0

    def connect(self, initialize=True):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        conn = sqlite3.connect(str(self.path), timeout=2)
        if os.name != 'nt':
            self.path.chmod(0o600)
        conn.row_factory = sqlite3.Row
        if not initialize:
            return conn
        conn.execute('PRAGMA journal_mode=WAL')
        conn.executescript('''
          CREATE TABLE IF NOT EXISTS documents(kind TEXT,id INTEGER,digest TEXT,vector_ready INTEGER,
            PRIMARY KEY(kind,id));
          CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY,kind TEXT,doc_id INTEGER,
            field TEXT,start INTEGER,text TEXT,vector BLOB);
          CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(kind,doc_id);
          CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(tokens);
        ''')
        return conn

    def invalidate(self):
        with self.lock:
            self.dirty = True

    def schedule(self):
        with self.lock:
            if self.stop.is_set() or (self.thread and self.thread.is_alive()):
                return
            if not self.dirty and time.monotonic() - self.last_run < 60:
                return
            self.dirty = False
            self.last_run = time.monotonic()
            self.thread = threading.Thread(target=self._run, name='stella-knowledge-index', daemon=True)
            self.thread.start()

    def _run(self):
        try:
            self.refresh()
            self.error = ''
        except Exception as exc:
            self.error = type(exc).__name__

    def refresh(self):
        """Finite incremental sweep, no idle polling; callable synchronously by tests."""
        import numpy as np
        self.processed = 0
        self.vector_error = ''
        source = sqlite3.connect(self.db_path.as_uri() + '?mode=ro', uri=True, timeout=2)
        source.row_factory = sqlite3.Row
        target = self.connect()
        try:
            tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            queries = []
            if {'knowledge_claims', 'knowledge_claim_issues', 'knowledge_issues', 'knowledge_claim_evidence'} <= tables:
                queries.append(('claim', '''SELECT c.id,c.statement,c.conditions_text,c.exceptions_text,
                    GROUP_CONCAT(DISTINCT i.title) issue_titles,
                    GROUP_CONCAT(DISTINCT CASE WHEN e.verified=1 THEN a.title END) source_titles
                    FROM knowledge_claims c
                    JOIN knowledge_claim_issues ci ON ci.claim_id=c.id
                    JOIN knowledge_issues i ON i.id=ci.issue_id
                    LEFT JOIN knowledge_claim_evidence e ON e.claim_id=c.id
                    LEFT JOIN articles a ON a.id=e.article_id
                    WHERE c.review_status='approved' AND i.status='active'
                    GROUP BY c.id'''))
            # Make the compact knowledge cards available before long article bodies.
            queries.append(('article', 'SELECT id,title,summary,content FROM articles'))
            seen = set()
            for kind, sql in queries:
                for row in source.execute(sql):
                    if self.stop.is_set():
                        return
                    doc_id = int(row['id']); seen.add((kind, doc_id))
                    fields = document_fields(dict(row), kind); digest = fingerprint(fields)
                    old = target.execute('SELECT digest,vector_ready FROM documents WHERE kind=? AND id=?', (kind, doc_id)).fetchone()
                    if old and old['digest'] == digest and (old['vector_ready'] or self.vector_error):
                        continue
                    # Store a complete document atomically. Encoding stays outside write transactions.
                    pending = list(passages(fields)); vectors = []; ready = True
                    for offset in range(0, len(pending), 8):
                        if self.stop.is_set():
                            return
                        batch = pending[offset:offset + 8]
                        try:
                            if self.vector_error:
                                raise RuntimeError(self.vector_error)
                            encoded = np.asarray(self.encoder([p[2] for p in batch]), dtype=np.float32)
                            norms = np.linalg.norm(encoded, axis=1, keepdims=True)
                            if encoded.ndim != 2 or encoded.shape[0] != len(batch) or not np.isfinite(encoded).all() or np.any(norms <= 0):
                                raise ValueError('invalid vectors')
                            vectors.extend(vector.astype('<f4').tobytes() for vector in encoded / norms)
                        except Exception as exc:
                            self.vector_error = type(exc).__name__; ready = False
                            vectors.extend([None] * len(batch))
                        self.stop.wait(.015)
                    with target:
                        self._delete(target, kind, doc_id)
                        for (field, start, text), vector in zip(pending, vectors):
                            cursor = target.execute('INSERT INTO chunks(kind,doc_id,field,start,text,vector) VALUES (?,?,?,?,?,?)', (kind, doc_id, field, start, text, vector))
                            target.execute('INSERT INTO chunk_fts(rowid,tokens) VALUES (?,?)', (cursor.lastrowid, ' '.join(terms(text))))
                        target.execute('INSERT OR REPLACE INTO documents VALUES (?,?,?,?)', (kind, doc_id, digest, int(ready)))
                    self.processed += 1
            for row in target.execute('SELECT kind,id FROM documents').fetchall():
                if (row['kind'], row['id']) not in seen:
                    with target:
                        self._delete(target, row['kind'], row['id'])
        finally:
            source.close(); target.close()

    @staticmethod
    def _delete(conn, kind, doc_id):
        conn.execute('DELETE FROM chunk_fts WHERE rowid IN (SELECT id FROM chunks WHERE kind=? AND doc_id=?)', (kind, doc_id))
        conn.execute('DELETE FROM chunks WHERE kind=? AND doc_id=?', (kind, doc_id))
        conn.execute('DELETE FROM documents WHERE kind=? AND id=?', (kind, doc_id))

    def search(self, query, kind, allowed_ids, fields=None, limit=100):
        """Each channel searches the eligible corpus independently, then RRF fuses."""
        self.schedule()
        status = {'method': 'keywords', 'building': bool(self.thread and self.thread.is_alive()),
                  'indexed_documents': 0, 'vector_documents': 0, 'notice': ''}
        if not allowed_ids or not self.path.exists():
            status['notice'] = '本地索引正在准备，当前使用关键词搜索'
            return [], status
        conn = None
        try:
            import numpy as np
            conn = self.connect(initialize=False)
            conn.execute('CREATE TEMP TABLE eligible(id INTEGER PRIMARY KEY)')
            conn.executemany('INSERT OR IGNORE INTO eligible VALUES (?)', ((int(i),) for i in allowed_ids))
            counts = conn.execute('SELECT COUNT(*),COALESCE(SUM(vector_ready),0) FROM documents d JOIN eligible e ON e.id=d.id WHERE kind=?', (kind,)).fetchone()
            status.update(indexed_documents=counts[0], vector_documents=counts[1])
            fields = fields or (FIELDS if kind == 'article' else KNOWLEDGE_FIELDS)
            field_sql = ','.join('?' for _ in fields)
            params = [kind, *fields]
            base = f'''FROM chunks c JOIN eligible e ON e.id=c.doc_id
                JOIN documents d ON d.kind=c.kind AND d.id=c.doc_id
                WHERE c.kind=? AND c.field IN ({field_sql})'''
            sparse = {}; dense = {}
            tokens = list(dict.fromkeys(terms(query)))[:48]
            expression = ' OR '.join('"' + token.replace('"', '""') + '"' for token in tokens)
            if expression:
                rows = conn.execute(f'''SELECT c.*,d.digest,bm25(chunk_fts) rank
                    FROM chunk_fts JOIN chunks c ON c.id=chunk_fts.rowid
                    JOIN eligible e ON e.id=c.doc_id
                    JOIN documents d ON d.kind=c.kind AND d.id=c.doc_id
                    WHERE chunk_fts MATCH ? AND c.kind=? AND c.field IN ({field_sql})
                    ORDER BY rank LIMIT 2000''', [expression, *params])
                for r in rows:
                    sparse.setdefault(r['doc_id'], dict(r))
            vector_failure = ''
            try:
                q = np.asarray(self.encoder(['为这个句子生成表示以用于检索相关文章：' + query]), dtype=np.float32)[0]
                norm = np.linalg.norm(q)
                if not np.isfinite(q).all() or norm <= 0:
                    raise ValueError('invalid query vector')
                q = q / norm
                cursor = conn.execute('SELECT c.*,d.digest ' + base + ' AND c.vector IS NOT NULL', params)
                # Bound intermediate RAM. Exact scan retains corpus-wide vector recall.
                while True:
                    batch = cursor.fetchmany(512)
                    if not batch:
                        break
                    matrix = np.stack([np.frombuffer(r['vector'], dtype='<f4') for r in batch])
                    scores = matrix @ q
                    for row, score in zip(batch, scores):
                        doc_id = row['doc_id']; score = float(score)
                        if score >= MIN_DENSE_SIMILARITY and (doc_id not in dense or score > dense[doc_id]['cosine']):
                            dense[doc_id] = dict(row, cosine=score)
                    if len(dense) > limit * 4:
                        dense = dict(heapq.nlargest(limit * 2, dense.items(), key=lambda pair: pair[1]['cosine']))
            except Exception as exc:
                vector_failure = type(exc).__name__
            sparse_order = list(sparse)[:limit]
            dense_order = sorted(dense, key=lambda i: -dense[i]['cosine'])[:limit]
            scores = {}; matches = {}
            for channel, ids in (('keyword', sparse_order), ('semantic', dense_order)):
                for rank, doc_id in enumerate(ids):
                    scores[doc_id] = scores.get(doc_id, 0) + 1 / (60 + rank + 1)
                    match = sparse.get(doc_id) if channel == 'keyword' else dense[doc_id]
                    if doc_id not in matches or channel == 'semantic':
                        matches[doc_id] = match
            hits = []
            for doc_id in sorted(scores, key=lambda i: (-scores[i], i))[:limit]:
                row = matches[doc_id]
                hits.append({'id': doc_id, 'score': scores[doc_id], 'digest': row['digest'],
                    'channels': [c for c, values in (('keyword', sparse), ('semantic', dense)) if doc_id in values],
                    'field': row['field'], 'label': LABELS[row['field']], 'text': row['text'],
                    'offset': row['start'], 'cosine': dense.get(doc_id, {}).get('cosine')})
            if self.reranker and hits:
                try:
                    reviewed = hits[:48]
                    contexts = []
                    for hit in reviewed:
                        context_fields = ('title', 'summary') if kind == 'article' else ('issue_titles', 'statement', 'conditions_text', 'exceptions_text')
                        context = conn.execute('SELECT field,text FROM chunks WHERE kind=? AND doc_id=? AND start=0', (kind, hit['id'])).fetchall()
                        # Explicit field scopes must constrain the cross-encoder as well.
                        texts = [LABELS[r['field']] + '：' + r['text'][:100] for r in context if r['field'] in context_fields and r['field'] in fields]
                        contexts.append('\n'.join(texts) + '\n原文：' + hit['text'])
                    relevance = self.reranker(query, contexts)
                    if len(relevance) != len(reviewed) or not all(np.isfinite(value) for value in relevance):
                        raise ValueError('invalid relevance scores')
                    kept = []
                    for hit, value in zip(reviewed, relevance):
                        hit['relevance_logit'] = float(value)
                        if value >= 0 or 'keyword' in hit['channels']:
                            kept.append(hit)
                    kept.sort(key=lambda hit: (-hit['relevance_logit'], -hit['score'], hit['id']))
                    for rank, hit in enumerate(kept):
                        hit['score'] = 2 / (61 + rank)
                    tail = [h for h in hits[48:] if 'keyword' in h['channels']]
                    for rank, hit in enumerate(tail):
                        hit['score'] = 1 / (200 + rank)
                    hits = kept + tail
                    status['relevance_review'] = 'local_cross_encoder'
                except Exception as exc:
                    # Preserve text retrieval; don't promote unreviewed vector-only hits.
                    hits = [h for h in hits if 'keyword' in h['channels']]
                    status['relevance_error'] = type(exc).__name__
                    status['notice'] = '本地相关性复核暂不可用，当前仅展示文字匹配结果'
            status['method'] = 'bm25+dense_rrf' if status['vector_documents'] and not vector_failure else 'bm25'
            if status.get('relevance_error'):
                status['method'] = 'bm25'
            elif vector_failure or self.vector_error:
                status['notice'] = '本地语义模型暂不可用，当前使用关键词搜索'
            elif status['indexed_documents'] < len(allowed_ids) or status['building']:
                status['notice'] = '本地索引正在更新，部分内容暂仅参与关键词搜索'
            status['vector_error'] = vector_failure or self.vector_error
            return hits, status
        except Exception as exc:
            status['notice'] = '本地索引暂不可用，当前使用关键词搜索'
            status['index_error'] = type(exc).__name__
            return [], status
        finally:
            if conn:
                conn.close()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=2)


def index_for(conn, create=True):
    path = conn.execute('PRAGMA database_list').fetchone()[2]
    if not path:
        return None
    key = str(Path(path).resolve())
    with _LOCK:
        if key not in _MANAGERS and not create:
            return None
        if key not in _MANAGERS:
            # A runtime has one business DB. Bound retained managers in test/multi-profile processes.
            if len(_MANAGERS) >= 4:
                oldest = next(iter(_MANAGERS)); _MANAGERS.pop(oldest).close()
            _MANAGERS[key] = CorpusIndex(key)
        return _MANAGERS[key]


def invalidate(conn):
    index = index_for(conn, create=False)
    if index:
        index.invalidate()


def retrieve(conn, query, kind, eligible, scope='all'):
    index = index_for(conn)
    if not index:
        return [], {'method': 'keywords', 'notice': '当前存储不支持持久语义索引'}
    fields = [scope] if kind == 'article' and scope in FIELDS else None
    hits, status = index.search(query, kind, eligible, fields)
    if not hits:
        return hits, status
    if kind == 'article':
        marks = ','.join('?' for _ in hits)
        rows = conn.execute('SELECT id,title,summary,content FROM articles WHERE id IN (' + marks + ')', [h['id'] for h in hits]).fetchall()
        current = {int(r['id']): fingerprint(document_fields(dict(r), kind)) for r in rows}
    else:
        current = {int(r['id']): fingerprint(document_fields(r, kind)) for r in eligible.values()}
    valid = [h for h in hits if current.get(h['id']) == h['digest']]
    if len(valid) != len(hits):
        index.invalidate(); index.schedule()
        status['notice'] = '内容已更新，相关语义索引正在刷新'
    return valid, status


def shutdown():
    with _LOCK:
        for index in _MANAGERS.values():
            index.close()
        _MANAGERS.clear()
    from .knowledge_reranker import shutdown as close_relevance
    close_relevance()
