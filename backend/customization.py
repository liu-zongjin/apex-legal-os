"""Shared informational entry; the experience uses the original page and APIs."""
import html
from fastapi.responses import HTMLResponse


def customization_notice(route,title):
    if route not in ('/mingsi-meeting','/quick-approval'):raise ValueError('unsupported route')
    return HTMLResponse('''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>'''+html.escape(title)+'''</title>
<meta name="stella-experience-route" content="'''+route+'''">
<link rel="stylesheet" href="/static/apex-design-tokens.css?v=1">
<script src="/static/apex-customization.js?v=2026102001" defer></script>
<style>body{margin:0;background:var(--apex-surface-muted);color:var(--apex-text);font:14px/1.8 var(--apex-font-sans);display:grid;min-height:100vh;place-items:center}main{box-sizing:border-box;max-width:580px;margin:24px;padding:36px;border:1px solid var(--apex-border-subtle);border-radius:var(--apex-radius-xl);background:var(--apex-surface-solid);box-shadow:var(--apex-shadow-float)}h1{font-size:25px;letter-spacing:-.6px;margin:0 0 16px}p{color:var(--apex-text-secondary)}button{font:inherit;color:white;background:var(--apex-accent);border:0;border-radius:var(--apex-radius-md);padding:10px 18px;cursor:pointer}label{display:flex;align-items:center;gap:8px;margin:24px 0 16px}input{accent-color:var(--apex-accent)}button:focus-visible,input:focus-visible{outline:2px solid var(--apex-accent);outline-offset:4px}</style></head>
<body><main><h1>'''+html.escape(title)+''' · 律所系统适配</h1>
<p>这项功能需要连接您所在律所的内部系统。如需适配本所流程，请联系作者定制。</p>
<p>您也可以直接体验现有的明思律所版本。页面和操作流程与本地 Stella 一致，联网操作需要对应系统的有效账号与权限。</p>
<label><input type="checkbox" id="customization-remember">知悉以上情况，不再提示</label>
<button type="button" id="customization-continue">打开明思律所版本体验</button></main></body></html>''',headers={'Cache-Control':'no-store'})
