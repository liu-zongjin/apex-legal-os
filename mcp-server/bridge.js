#!/usr/bin/env node
/**
 * MCP HTTP Bridge
 * 将 MCP Server（stdio 协议）桥接为 HTTP API
 * 让外部服务（如 FastAPI）可以通过 HTTP 调用 MCP 工具
 *
 * 运行端口：3099
 * 端点：
 *   GET  /tools          - 列出所有可用工具
 *   POST /call           - 调用指定工具  {name, arguments}
 *   POST /ask            - 通用问答（内部调用 search + get_article）{question, context}
 */

const http = require('http');
const { spawn } = require('child_process');
const path = require('path');

const BRIDGE_PORT = 3099;
const BRIDGE_HOST = process.env.LEGAL_KB_MCP_HOST || '127.0.0.1';
const BRIDGE_CORS_ORIGIN = process.env.LEGAL_KB_MCP_CORS_ORIGIN || 'http://localhost:8765';
const MCP_SERVER_PATH = path.join(__dirname, 'server.js');

// ── MCP 子进程管理 ──────────────────────────────────────
let mcpProcess = null;
let mcpReady = false;
const pendingRequests = new Map();
let requestId = 0;

// 启动 MCP Server 子进程
function startMcpProcess() {
  if (mcpProcess) {
    try { mcpProcess.kill(); } catch (_) {}
  }

  // launchd 的默认 PATH 通常只有 /usr/bin:/bin:/usr/sbin:/sbin。
  // 使用当前 Bridge 自己的 Node 可执行文件，避免子进程因找不到 `node`
  // 而每隔几秒崩溃一次并持续灌满 bridge.log。
  mcpProcess = spawn(process.execPath, [MCP_SERVER_PATH], {
    stdio: ['pipe', 'pipe', 'pipe'],
    env: { ...process.env, NODE_ENV: 'production' }
  });

  mcpProcess.stdout.on('data', (data) => {
    const lines = data.toString().trim().split('\n');
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const resp = JSON.parse(line);
        if (resp.id !== undefined && pendingRequests.has(resp.id)) {
          const { resolve, reject, timeout } = pendingRequests.get(resp.id);
          clearTimeout(timeout);
          pendingRequests.delete(resp.id);
          if (resp.error) reject(new Error(resp.error.message || JSON.stringify(resp.error)));
          else resolve(resp.result);
        }
      } catch (_) {
        // 非 JSON 行可能是日志，忽略
      }
    }
  });

  mcpProcess.stderr.on('data', (data) => {
    // MCP Server 的 console.error 输出，忽略
  });

  mcpProcess.on('error', (err) => {
    // 必须监听 error；否则 spawn 失败会成为未处理事件并直接杀死 Bridge。
    console.error('[MCP Bridge] MCP Server 启动失败：' + err.message);
  });

  mcpProcess.on('exit', (code) => {
    console.error('[MCP Bridge] MCP Server 子进程退出，code=' + code + '，1秒后重启...');
    mcpProcess = null;
    mcpReady = false;
    setTimeout(startMcpProcess, 1000);
  });

  setTimeout(() => { mcpReady = true; }, 500);
}

// 发送 JSON-RPC 请求到 MCP Server，等待响应
function mcpCall(method, params) {
  return new Promise((resolve, reject) => {
    if (!mcpProcess || !mcpReady) {
      reject(new Error('MCP Server 未就绪，请稍后重试'));
      return;
    }

    const id = ++requestId;
    const payload = JSON.stringify({ jsonrpc: '2.0', id, method, params });

    const timeout = setTimeout(() => {
      if (pendingRequests.has(id)) {
        pendingRequests.delete(id);
        reject(new Error('MCP 调用超时（10秒）'));
      }
    }, 10000);

    pendingRequests.set(id, { resolve, reject, timeout });
    mcpProcess.stdin.write(payload + '\n');
  });
}

// ── HTTP 服务器 ─────────────────────────────────────────
const server = http.createServer(async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', BRIDGE_CORS_ORIGIN);
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  res.setHeader('Content-Type', 'application/json; charset=utf-8');

  let body = '';
  req.on('data', chunk => { body += chunk; });
  req.on('end', async () => {
    try {
      // GET /tools
      if (req.method === 'GET' && req.url === '/tools') {
        const result = await mcpCall('tools/list', {});
        res.writeHead(200);
        res.end(JSON.stringify({ ok: true, tools: result.tools || [] }));
        return;
      }

      // POST /call
      if (req.method === 'POST' && req.url === '/call') {
        const { name, arguments: args = {} } = JSON.parse(body || '{}');
        if (!name) {
          res.writeHead(400);
          res.end(JSON.stringify({ error: '缺少 name 参数' }));
          return;
        }
        const result = await mcpCall('tools/call', { name, arguments: args });
        res.writeHead(200);
        res.end(JSON.stringify({ ok: true, result }));
        return;
      }

      // POST /ask - 通用问答
      if (req.method === 'POST' && req.url === '/ask') {
        const { question, article_id } = JSON.parse(body || '{}');
        let searchResult;
        if (article_id) {
          const artResult = await mcpCall('tools/call', {
            name: 'get_article',
            arguments: { id: article_id }
          });
          searchResult = artResult;
        } else {
          searchResult = await mcpCall('tools/call', {
            name: 'search_articles',
            arguments: { keyword: question, limit: 5 }
          });
        }
        res.writeHead(200);
        res.end(JSON.stringify({
          ok: true,
          search_result: searchResult,
          question,
          context_type: 'general'
        }));
        return;
      }

      // 健康检查
      if (req.method === 'GET' && req.url === '/health') {
        res.writeHead(200);
        res.end(JSON.stringify({ status: mcpReady ? 'ready' : 'starting', mcpReady }));
        return;
      }

      res.writeHead(404);
      res.end(JSON.stringify({ error: '未知路径' }));

    } catch (err) {
      console.error('[Bridge Error]', err.message);
      res.writeHead(500);
      res.end(JSON.stringify({ error: err.message }));
    }
  });
});

// ── 启动 ────────────────────────────────────────────────
startMcpProcess();
server.listen(BRIDGE_PORT, BRIDGE_HOST, () => {
  console.log('[MCP Bridge] 已启动，监听 http://' + BRIDGE_HOST + ':' + BRIDGE_PORT);
});
