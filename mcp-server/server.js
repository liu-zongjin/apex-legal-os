#!/usr/bin/env node
/**
 * 法律操作系统 MCP Server
 * 通过 MCP 协议暴露知识库搜索和查询能力
 * 配合 WorkBuddy 使用，让 AI 能够直接访问法律操作系统
 */

const { Server } = require('@modelcontextprotocol/sdk/server/index.js');
const { StdioServerTransport } = require('@modelcontextprotocol/sdk/server/stdio.js');
const {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} = require('@modelcontextprotocol/sdk/types.js');
const sqlite3 = require('better-sqlite3');
const path = require('path');

// ── 数据库路径（指向 legal-kb 根目录）───────────────────
const DB_PATH = path.join(__dirname, '..', 'legal_kb.db');
const NPC_LAW_DB_URL = String(process.env.NPC_LAW_DB_URL || 'https://flk.npc.gov.cn').replace(/\/$/, '');
const NPC_STATUS_LABELS = { 1: '已废止', 2: '已修改', 3: '有效', 4: '尚未生效' };

function cleanNpcText(value) {
  return String(value || '').replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();
}

function normalizeNpcTitle(value) {
  return cleanNpcText(value).replace(/[《》〈〉\s]/g, '')
    .replace(/[（(](?:失效|废止|已修改|\d{4}年修(?:正|订)(?:文本)?)[）)]$/, '');
}

async function npcJson(pathname, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeout || 20000);
  try {
    const response = await fetch(NPC_LAW_DB_URL + pathname, {
      method: options.method || 'GET',
      headers: {
        'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/json;charset=UTF-8',
        'Referer': NPC_LAW_DB_URL + '/',
        'User-Agent': 'LegalKnowledgeBase-MCP/1.0',
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    });
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const data = await response.json();
    if (Number(data.code || 0) !== 200) throw new Error(data.msg || '国家法律法规数据库返回异常');
    return data;
  } catch (err) {
    if (err && err.name === 'AbortError') throw new Error('国家法律法规数据库连接超时');
    throw err;
  } finally {
    clearTimeout(timeout);
  }
}

function npcLawRow(row) {
  const code = row.sxx == null ? null : Number(row.sxx);
  const bbbs = String(row.bbbs || '');
  return {
    bbbs,
    title: cleanNpcText(row.title),
    status_code: code,
    status_label: NPC_STATUS_LABELS[code] || '未知',
    category: String(row.flxz || ''),
    issuer: String(row.zdjgName || ''),
    published_at: String(row.gbrq || ''),
    effective_at: String(row.sxrq || ''),
    source_url: NPC_LAW_DB_URL + '/detail?bbbs=' + encodeURIComponent(bbbs),
    score: Number(row.score || 0),
  };
}

async function searchNpcLaws(args) {
  const query = String(args.query || '').trim().slice(0, 200);
  if (!query) throw new Error('检索内容不能为空');
  const limit = Math.max(1, Math.min(Number(args.limit || 10), 30));
  const statuses = Array.isArray(args.statuses) && args.statuses.length ? args.statuses : [3, 4];
  const data = await npcJson('/law-search/search/list', {
    method: 'POST',
    body: {
      searchRange: args.search_scope === 'fulltext' ? 2 : 1,
      sxrq: [], gbrq: [], sxx: statuses.map(Number),
      searchType: args.exact ? 1 : 2, xgzlSearch: false,
      searchContent: query, pageNum: 1, pageSize: limit,
    },
  });
  const normalized = normalizeNpcTitle(query);
  const results = (data.rows || []).filter(row => row.bbbs).map(npcLawRow);
  results.sort((a, b) => {
    const ae = normalizeNpcTitle(a.title) === normalized ? 0 : 1;
    const be = normalizeNpcTitle(b.title) === normalized ? 0 : 1;
    return ae - be || (a.status_code === 3 ? 0 : 1) - (b.status_code === 3 ? 0 : 1) || b.score - a.score;
  });
  return { query, total: Number(data.total || 0), results: results.slice(0, limit) };
}

async function getNpcLawHits(args) {
  const bbbs = String(args.bbbs || '').trim();
  const query = String(args.query || '').trim().slice(0, 200);
  if (!bbbs || !query) throw new Error('法规标识和检索内容不能为空');
  const data = await npcJson('/law-search/search/hitDisplay', {
    method: 'POST',
    body: { bbbs, searchContent: query, searchRange: 2, searchType: args.exact === false ? 2 : 1 },
  });
  return (data.data && data.data.contentHitDisplay || []).map(cleanNpcText).filter(Boolean);
}

async function getNpcLawDetail(bbbs) {
  const id = String(bbbs || '').trim();
  if (!id) throw new Error('法规标识不能为空');
  const data = await npcJson('/law-search/search/flfgDetails?bbbs=' + encodeURIComponent(id));
  const raw = data.data || {};
  const row = npcLawRow({ ...raw, bbbs: id });
  return { ...row, toc: raw.content || {}, word_path: raw.ossFile && raw.ossFile.ossWordPath || '', history: raw.lsyg || null };
}

async function checkNpcLawUpdate(args) {
  const current = await getNpcLawDetail(args.bbbs);
  const found = await searchNpcLaws({ query: args.title || current.title, exact: true, limit: 20, statuses: [1, 2, 3, 4] });
  const normalized = normalizeNpcTitle(args.title || current.title);
  const versions = found.results.filter(row => normalizeNpcTitle(row.title) === normalized);
  const preferred = versions.find(row => row.status_code === 3) || versions.find(row => row.status_code === 4) || null;
  return {
    current, preferred, same_title_versions: versions,
    status_changed: args.known_status != null && Number(args.known_status) !== current.status_code,
    new_version_available: Boolean(preferred && preferred.bbbs !== current.bbbs),
  };
}

// ── 数据库工具 ──────────────────────────────────────────
let db;

function getDb() {
  if (!db) {
    db = new sqlite3(DB_PATH);
    ensureArticlesFts(db);
  }
  return db;
}

function ensureArticlesFts(conn) {
  try {
    const existing = conn.prepare(
      "SELECT sql FROM sqlite_master WHERE type='table' AND name='articles_fts'"
    ).get();
    let needsRebuild = !existing;
    if (existing && !String(existing.sql || '').includes("tokenize='trigram'")) {
      conn.exec(`
        DROP TRIGGER IF EXISTS articles_fts_ai;
        DROP TRIGGER IF EXISTS articles_fts_ad;
        DROP TRIGGER IF EXISTS articles_fts_au;
        DROP TABLE IF EXISTS articles_fts;
      `);
      needsRebuild = true;
    }
    const trigger = conn.prepare("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='articles_fts_au'").get();
    if (trigger && !trigger.sql.includes('AFTER UPDATE OF')) conn.exec('DROP TRIGGER articles_fts_au');
    conn.exec(`
      CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts
      USING fts5(
        title,
        summary,
        content,
        tags,
        domains,
        content='articles',
        content_rowid='id',
        tokenize='trigram'
      );
      CREATE TRIGGER IF NOT EXISTS articles_fts_ai AFTER INSERT ON articles BEGIN
        INSERT INTO articles_fts(rowid, title, summary, content, tags, domains)
        VALUES (new.id, new.title, new.summary, new.content, new.tags, new.domains);
      END;
      CREATE TRIGGER IF NOT EXISTS articles_fts_ad AFTER DELETE ON articles BEGIN
        INSERT INTO articles_fts(articles_fts, rowid, title, summary, content, tags, domains)
        VALUES ('delete', old.id, old.title, old.summary, old.content, old.tags, old.domains);
      END;
      CREATE TRIGGER IF NOT EXISTS articles_fts_au AFTER UPDATE OF title,summary,content,tags,domains ON articles
            WHEN old.title IS NOT new.title OR old.summary IS NOT new.summary
              OR old.content IS NOT new.content OR old.tags IS NOT new.tags OR old.domains IS NOT new.domains
            BEGIN
        INSERT INTO articles_fts(articles_fts, rowid, title, summary, content, tags, domains)
        VALUES ('delete', old.id, old.title, old.summary, old.content, old.tags, old.domains);
        INSERT INTO articles_fts(rowid, title, summary, content, tags, domains)
        VALUES (new.id, new.title, new.summary, new.content, new.tags, new.domains);
      END;
    `);
    const articleCount = conn.prepare('SELECT COUNT(*) as n FROM articles').get().n;
    const ftsCount = conn.prepare('SELECT COUNT(*) as n FROM articles_fts').get().n;
    if (needsRebuild || articleCount !== ftsCount) {
      conn.prepare("INSERT INTO articles_fts(articles_fts) VALUES ('rebuild')").run();
    }
  } catch (err) {
    console.error('[legal-kb-mcp] FTS 初始化失败，继续使用 LIKE 搜索:', err.message);
  }
}

function buildFtsQuery(keyword) {
  const raw = String(keyword || '').trim();
  if (!raw) return '';
  const tokens = raw.match(/[\w\u4e00-\u9fff]+/g) || [];
  const candidates = [];
  const compact = tokens.join('');
  if (compact && compact !== raw) candidates.push(compact);
  candidates.push(raw, ...tokens);
  const seen = new Set();
  return candidates
    .map(s => String(s || '').trim())
    .filter(s => s.length >= 2 && !seen.has(s) && (seen.add(s), true))
    .map(s => '"' + s.replace(/"/g, '""') + '"')
    .join(' OR ');
}

function searchArticlesFts(keyword, limit) {
  const conn = getDb();
  const query = buildFtsQuery(keyword);
  if (!query) return [];
  try {
    return conn.prepare(`
      SELECT a.id, a.title, a.summary, a.domains, a.source_type, a.created_at,
             bm25(articles_fts, 8.0, 3.0, 1.0, 1.5, 1.5) as score
      FROM articles_fts
      JOIN articles a ON a.id = articles_fts.rowid
      WHERE articles_fts MATCH ?
      ORDER BY score
      LIMIT ?
    `).all(query, limit);
  } catch (_) {
    return [];
  }
}

function searchArticles(keyword, limit = 10) {
  const conn = getDb();
  if (!keyword || keyword.trim().length === 0) {
    const rows = conn.prepare(`
      SELECT id, title, summary, domains, source_type, created_at
      FROM articles ORDER BY created_at DESC LIMIT ?
    `).all(limit);
    return rows;
  }

  const ftsRows = searchArticlesFts(keyword, limit);
  if (ftsRows.length > 0) {
    return ftsRows;
  }

  const rows = conn.prepare(`
    SELECT id, title, summary, domains, source_type, created_at,
           (CASE WHEN title LIKE ? THEN 3 ELSE 0 END +
            CASE WHEN summary LIKE ? THEN 2 ELSE 0 END +
            CASE WHEN domains LIKE ? THEN 1 ELSE 0 END) as score
    FROM articles
    WHERE title LIKE ? OR summary LIKE ? OR domains LIKE ? OR content LIKE ?
    ORDER BY score DESC, created_at DESC
    LIMIT ?
  `).all(
    '%' + keyword + '%', '%' + keyword + '%', '%' + keyword + '%',
    '%' + keyword + '%', '%' + keyword + '%', '%' + keyword + '%', '%' + keyword + '%',
    limit
  );
  return rows;
}

function getArticle(id) {
  const conn = getDb();
  return conn.prepare(`
    SELECT id, title, content, summary, domains, source_type,
           source_url, source_filename, source_localpath,
           created_at, tags, starred, pinned
    FROM articles WHERE id = ?
  `).get(id);
}

function getArticleNotes(articleId) {
  const conn = getDb();
  return conn.prepare(`
    SELECT id, content, selected_text, created_at
    FROM notes WHERE article_id = ?
    ORDER BY created_at DESC
  `).all(articleId);
}

function getDomains() {
  const conn = getDb();
  // domains 是 JSON 数组如 ["破产法","公司法"]，逐行解析后聚合
  const rows = conn.prepare(`
    SELECT domains FROM articles WHERE domains IS NOT NULL AND domains != ''
  `).all();
  const tally = {};
  for (const row of rows) {
    try {
      const arr = JSON.parse(row.domains);
      if (Array.isArray(arr)) {
        for (const d of arr) {
          tally[d] = (tally[d] || 0) + 1;
        }
      }
    } catch (_) {}
  }
  return Object.entries(tally)
    .sort((a, b) => b[1] - a[1])
    .map(([domain, count]) => ({ domain, count }));
}

function getStats() {
  const conn = getDb();
  const total = conn.prepare('SELECT COUNT(*) as n FROM articles').get().n;
  const withSummary = conn.prepare(
    "SELECT COUNT(*) as n FROM articles WHERE summary IS NOT NULL AND summary != ''"
  ).get().n;
  const starred = conn.prepare('SELECT COUNT(*) as n FROM articles WHERE starred = 1').get().n;
  const pinned = conn.prepare('SELECT COUNT(*) as n FROM articles WHERE pinned = 1').get().n;
  const domains = getDomains();
  return { total, withSummary, starred, pinned, domains };
}

function getRecentArticles(limit) {
  const conn = getDb();
  return conn.prepare(`
    SELECT id, title, summary, domains, source_type, created_at
    FROM articles ORDER BY created_at DESC LIMIT ?
  `).all(limit || 10);
}

// ── MCP 工具定义 ────────────────────────────────────────
const TOOLS = [
  {
    name: 'search_articles',
    description: '搜索法律操作系统文章。支持关键词全文搜索，返回标题/摘要/领域/类型。法律专业问题建议先用此工具检索相关资料。',
    inputSchema: {
      type: 'object',
      properties: {
        keyword: {
          type: 'string',
          description: '搜索关键词，可为法律术语、案由、罪名、法规名称等',
        },
        limit: {
          type: 'number',
          description: '返回数量上限，默认10',
          default: 10,
        },
      },
    },
  },
  {
    name: 'get_article',
    description: '获取指定文章的完整内容（正文/摘要/元数据），可指定摘要字数限制。',
    inputSchema: {
      type: 'object',
      properties: {
        id: {
          type: 'number',
          description: '文章ID（来自 search_articles 的返回结果）',
        },
        content_length: {
          type: 'number',
          description: '正文字数限制，超过则截断，默认不限制',
          default: 0,
        },
      },
      required: ['id'],
    },
  },
  {
    name: 'get_article_notes',
    description: '获取某篇文章的所有笔记和标注内容。',
    inputSchema: {
      type: 'object',
      properties: {
        article_id: {
          type: 'number',
          description: '文章ID',
        },
      },
      required: ['article_id'],
    },
  },
  {
    name: 'get_domains',
    description: '获取知识库的专业领域分类统计（各领域文章数量），了解知识库覆盖范围。',
    inputSchema: {
      type: 'object',
      properties: {},
    },
  },
  {
    name: 'get_stats',
    description: '获取知识库整体统计信息：文章总数、有摘要数、收藏数、置顶数、领域分布等。',
    inputSchema: {
      type: 'object',
      properties: {},
    },
  },
  {
    name: 'get_recent_articles',
    description: '获取最近入库的文章列表（按入库时间倒序）。',
    inputSchema: {
      type: 'object',
      properties: {
        limit: {
          type: 'number',
          description: '返回数量，默认10',
          default: 10,
        },
      },
    },
  },
  {
    name: 'search_national_laws',
    description: '实时检索全国人大国家法律法规数据库。默认仅返回有效和尚未生效法规，可按标题或全文检索。',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: '法规名称或法律问题关键词' },
        search_scope: { type: 'string', enum: ['title', 'fulltext'], default: 'title' },
        exact: { type: 'boolean', default: false },
        statuses: { type: 'array', items: { type: 'number', enum: [1, 2, 3, 4] }, default: [3, 4] },
        limit: { type: 'number', default: 10 },
      },
      required: ['query'],
    },
  },
  {
    name: 'get_national_law_hits',
    description: '取得某部法规中命中检索问题的法条原文，用于精确引用。',
    inputSchema: {
      type: 'object',
      properties: {
        bbbs: { type: 'string', description: '国家库法规唯一标识' },
        query: { type: 'string', description: '需要在法规正文中定位的词句' },
        exact: { type: 'boolean', default: true },
      },
      required: ['bbbs', 'query'],
    },
  },
  {
    name: 'get_national_law_detail',
    description: '取得国家库法规的效力状态、制定机关、日期、目录和官方原文链接。',
    inputSchema: {
      type: 'object',
      properties: { bbbs: { type: 'string', description: '国家库法规唯一标识' } },
      required: ['bbbs'],
    },
  },
  {
    name: 'check_national_law_update',
    description: '检查已绑定法规的效力状态变化和同名新版本。只检测，不修改本地文章。',
    inputSchema: {
      type: 'object',
      properties: {
        bbbs: { type: 'string', description: '当前法规唯一标识' },
        title: { type: 'string', description: '当前法规标题' },
        known_status: { type: 'number', description: '本地记录的效力状态码' },
      },
      required: ['bbbs'],
    },
  },
];

// ── 工具执行逻辑 ────────────────────────────────────────
async function handleToolCall(name, args) {
  try {
    switch (name) {
      case 'search_articles': {
        const rows = searchArticles(args.keyword || '', args.limit || 10);
        if (rows.length === 0) {
          const total = getStats().total;
          return { content: [{ type: 'text', text: '未找到与"' + (args.keyword || '') + '"相关的文章。知识库目前共 ' + total + ' 篇文章。' }] };
        }
        const lines = rows.map(function(r) {
          const domain = r.domains || '';
          return '[' + r.id + '] ' + r.title + '\n   ' + (domain ? domain + ' | ' : '') + (r.created_at ? r.created_at.slice(0,10) : '') + ' | ' + (r.summary ? r.summary.slice(0,80) : '') + '...';
        });
        return { content: [{ type: 'text', text: '找到 ' + rows.length + ' 篇相关文章：\n\n' + lines.join('\n\n') }] };
      }

      case 'get_article': {
        const a = getArticle(args.id);
        if (!a) {
          return { content: [{ type: 'text', text: '未找到 ID=' + args.id + ' 的文章。' }] };
        }
        let content = a.content || '';
        if (args.content_length && content.length > args.content_length) {
          content = content.slice(0, args.content_length) + '...（已截断）';
        }
        const parts = [
          '📄 标题：' + a.title,
          '📁 领域：' + (a.domains || '未分类'),
          '📅 入库：' + (a.created_at ? a.created_at.slice(0,10) : ''),
          '🏷️ 类型：' + (a.source_type || ''),
          a.source_url ? '🔗 来源：' + a.source_url : '',
          a.summary ? '📝 摘要：' + a.summary : '',
          '',
          '────────── 正文 ──────────',
          content,
        ].filter(Boolean);
        return { content: [{ type: 'text', text: parts.join('\n') }] };
      }

      case 'get_article_notes': {
        const notes = getArticleNotes(args.article_id);
        if (notes.length === 0) {
          return { content: [{ type: 'text', text: '该文章暂无笔记。' }] };
        }
        const lines = notes.map(function(n) {
          const sel = n.selected_text ? '\n   📌 引用："' + n.selected_text + '"\n   📝 笔记：' : '\n   📝 笔记：';
          return '[' + n.id + '] ' + sel + n.content + '\n   🕐 ' + (n.created_at ? n.created_at.slice(0,16) : '');
        });
        return { content: [{ type: 'text', text: lines.join('\n\n') }] };
      }

      case 'get_domains': {
        const rows = getDomains();
        if (rows.length === 0) {
          return { content: [{ type: 'text', text: '暂无领域分类数据。' }] };
        }
        const lines = rows.map(function(r) { return '  • ' + r.domain + '（' + r.count + '篇）'; });
        return { content: [{ type: 'text', text: '📊 专业领域分布（共' + rows.length + '个领域）：\n\n' + lines.join('\n') }] };
      }

      case 'get_stats': {
        const s = getStats();
        const topDomains = s.domains.slice(0, 5).map(function(d) { return '    • ' + d.domain + '（' + d.count + '篇）'; });
        return {
          content: [{
            type: 'text',
            text: '📊 法律操作系统统计\n\n  📄 文章总数：' + s.total + '\n  📝 有摘要：' + s.withSummary + '\n  ⭐ 收藏：' + s.starred + '\n  📌 置顶：' + s.pinned + '\n  📁 领域数：' + s.domains.length + '\n\n  Top 领域：\n' + topDomains.join('\n')
          }]
        };
      }

      case 'get_recent_articles': {
        const rows = getRecentArticles(args.limit || 10);
        if (rows.length === 0) {
          return { content: [{ type: 'text', text: '暂无文章。' }] };
        }
        const lines = rows.map(function(r) { return '[' + r.id + '] ' + r.title + ' | ' + (r.created_at ? r.created_at.slice(0,10) : ''); });
        return { content: [{ type: 'text', text: '📋 最近入库 ' + rows.length + ' 篇：\n\n' + lines.join('\n') }] };
      }

      case 'search_national_laws': {
        const result = await searchNpcLaws(args || {});
        return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
      }

      case 'get_national_law_hits': {
        const hits = await getNpcLawHits(args || {});
        return { content: [{ type: 'text', text: JSON.stringify({ bbbs: args.bbbs, query: args.query, hits }, null, 2) }] };
      }

      case 'get_national_law_detail': {
        const detail = await getNpcLawDetail(args.bbbs);
        return { content: [{ type: 'text', text: JSON.stringify(detail, null, 2) }] };
      }

      case 'check_national_law_update': {
        const result = await checkNpcLawUpdate(args || {});
        return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
      }

      default:
        return { content: [{ type: 'text', text: '未知工具：' + name }], isError: true };
    }
  } catch (err) {
    return { content: [{ type: 'text', text: '错误：' + err.message }], isError: true };
  }
}

// ── 启动 MCP Server ─────────────────────────────────────
const server = new Server(
  { name: 'legal-kb-mcp', version: '1.0.0' },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async function() {
  return { tools: TOOLS };
});

server.setRequestHandler(CallToolRequestSchema, async function(request) {
  return await handleToolCall(request.params.name, request.params.arguments || {});
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('[legal-kb-mcp] 已启动，监听 stdio...');
}

main().catch(function(err) {
  console.error('[legal-kb-mcp] 启动失败：', err.message);
  process.exit(1);
});
