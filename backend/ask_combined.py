"""Answer one question from several selected sources at once.

Each source keeps its own retrieval rules: local articles are ranked by the
existing knowledge search, 法答网 keeps its own authoritative answers, and
selected files keep the indexed-span selection used by the file routes. This
module only numbers the evidence, splits one input budget, asks once and maps
the model's citations back to the source that supplied them.
"""
from __future__ import annotations

import json
import re

from fastapi import HTTPException

SOURCE_LABELS = {"knowledge": "知识库文章", "fada": "法答网答问", "files": "所选文件"}
# Shares of the free input budget. Verbatim file spans cost the most per unit of
# evidence, but they stay first-class for case work.
SHARES = {"knowledge": 0.40, "fada": 0.22, "files": 0.38}
FIXED_RESERVE = 2600
MAX_KNOWLEDGE_ARTICLES = 12
MAX_FADA_ITEMS = 12


def _tokens(text):
    from .ai_context import tokens
    return tokens(text)


def _clip(text, budget):
    text = str(text or "").strip()
    if budget <= 0:
        return ""
    if _tokens(text) <= budget:
        return text
    return text[: max(0, int(budget))] + "\n…（本次因篇幅只提供上述原文）"


def _escape_like(value):
    return str(value or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _ids_by_tags(conn, names):
    """Articles carrying at least one of the given tags (same rule as tag routes)."""
    wanted = {str(name) for name in names if str(name).strip()}
    if not wanted:
        return []
    matched = []
    for row in conn.execute("SELECT id, tags FROM articles ORDER BY created_at DESC"):
        try:
            tags = json.loads(row[1] or "[]")
        except (TypeError, ValueError):
            tags = []
        if isinstance(tags, list) and any(isinstance(tag, str) and tag in wanted for tag in tags):
            matched.append(row[0])
    return matched


def article_ids_for_scope(conn, scope):
    """Resolve a knowledge scope to article IDs; None means the whole library."""
    scope = scope if isinstance(scope, dict) else {}
    kind = str(scope.get("type") or "section")
    if kind == "article":
        try:
            article_id = int(scope.get("id") or 0)
        except (TypeError, ValueError, OverflowError):
            return []
        return [article_id] if article_id > 0 else []
    if kind == "results":
        ids = scope.get("ids")
        return [int(value) for value in ids if re.fullmatch(r"[0-9]{1,18}", str(value).strip())] if isinstance(ids, list) else []
    if kind == "tag":
        escaped = _escape_like(scope.get("tag"))
        return [row[0] for row in conn.execute(
            "SELECT id FROM articles WHERE tags LIKE ? ESCAPE '\\' ORDER BY created_at DESC",
            (f'%"{escaped}"%',)).fetchall()]
    if kind == "author":
        escaped = _escape_like(f"作者:{scope.get('author') or ''}")
        return [row[0] for row in conn.execute(
            "SELECT id FROM articles WHERE tags LIKE ? ESCAPE '\\' ORDER BY created_at DESC",
            (f'%"{escaped}"%',)).fetchall()]
    if kind == "domain":
        escaped = _escape_like(scope.get("domain"))
        return [row[0] for row in conn.execute(
            "SELECT id FROM articles WHERE domains LIKE ? ESCAPE '\\' ORDER BY created_at DESC",
            (f'%"{escaped}"%',)).fetchall()]
    if kind == "category":
        try:
            category_id = int(scope.get("catId") or 0)
        except (TypeError, ValueError):
            return []
        names = [row[0] for row in conn.execute(
            "SELECT name FROM tag_groups WHERE category_id=?", (category_id,)).fetchall()]
        return _ids_by_tags(conn, names)
    return None if kind == "section" else []


def knowledge_evidence(question, conn, scope, budget, progress=None):
    """Ranked local articles, trimmed to the knowledge share of the budget."""
    from . import main
    ids = article_ids_for_scope(conn, scope)
    if ids is not None and not ids:
        return [], ["所选知识库范围中没有可用的文章，本次未提供知识库材料。"]
    articles, _counts = main._search_ask_articles(
        question, conn, top_k=MAX_KNOWLEDGE_ARTICLES, article_ids=ids, original_question=question)
    if not articles:
        return [], ["本次在所选知识库范围内没有检索到相关文章。"]
    if progress:
        progress(f"知识库检索完成，召回 {len(articles)} 篇相关文章")
    share = max(400, budget // max(1, len(articles)))
    items = []
    for article in articles:
        body = _clip(article.get("content") or "", share)
        if not body:
            continue
        block = f"《{article.get('title') or '未命名文章'}》（来源：{article.get('source') or '本地知识库'}）\n{body}"
        items.append({
            "kind": "knowledge", "article_id": int(article.get("id") or 0),
            "title": article.get("title") or "未命名文章",
            "source": article.get("source") or "",
            "excerpt": body[:400],
            "block": block,
        })
    return items, []


def fada_evidence(question, scope, budget, progress=None):
    """法答网 authoritative answers, verbatim, trimmed to its share."""
    from . import main
    scope = scope if isinstance(scope, dict) else {}
    try:
        library = main._load_fada_structured_items(include_notes=True)
    except Exception as exc:  # noqa: BLE001 - surface a readable reason, not a 500
        return [], [f"法答网数据读取失败：{str(exc)[:120]}"]
    ids = {str(value) for value in (scope.get("ids") or []) if str(value).strip()}
    scoped = [item for item in library if str(item.get("id")) in ids] if ids else library
    if ids and not scoped:
        return [], ["所选法答网答问已不存在，本次未提供法答网材料。"]
    tokens = main._fada_query_tokens(question)
    scored = []
    for item in scoped:
        score, snippets = main._fada_score_item(dict(item), tokens, "all")
        hit_tokens = set()
        for snippet in snippets:
            hit_tokens.update(snippet.get("tokens", []))
        scored.append((score, len(hit_tokens), item))
    scored.sort(key=lambda row: (-row[0], row[2].get("idx", 0)))
    # 与法答网单独问答一致：明确勾选时放宽，否则要求真正的相关性，
    # 避免把不相关答问塞进组合回答。
    threshold = 1 if ids else 8
    ranked = [item for score, hits, item in scored
              if score >= threshold and (ids or len(tokens) < 3 or hits >= 2)]
    if not ranked:
        if ids:
            ranked = [item for _score, _hits, item in scored]
        elif not tokens:
            ranked = [item for _score, _hits, item in scored][:MAX_FADA_ITEMS]
        else:
            return [], ["本次没有检索到与问题相关的法答网答问。"]
    ranked = ranked[:MAX_FADA_ITEMS]
    if progress:
        progress(f"法答网检索完成，命中 {len(ranked)} 条答问")
    share = max(500, budget // max(1, len(ranked)))
    items = []
    for item in ranked:
        basis = "；".join((item.get("legal_basis") or [])[:5]) or "未抽取到明确法律依据"
        note = str(item.get("note") or "").strip()
        block = (f"【{item.get('batch')}｜{item.get('topic')}｜{item.get('procedure')}】\n"
                 f"问：{item.get('question')}\n"
                 f"答：{_clip(item.get('answer'), share)}\n"
                 f"法律依据：{basis}"
                 + (f"\n本人批注：{note}" if note else ""))
        items.append({
            "kind": "fada", "id": item.get("id"), "idx": item.get("idx"),
            "batch": item.get("batch"), "topic": item.get("topic"),
            "question": item.get("question"), "title": item.get("question"),
            "excerpt": (item.get("answer") or "")[:400],
            "block": block,
        })
    return items, []


async def file_evidence(question, model, file_scope, budget, get_db, parse_file, progress=None):
    """Selected file spans, using the indexed-span selection of the file routes."""
    from . import case_files
    file_scope = file_scope if isinstance(file_scope, dict) else {}
    rows, visual_files, warnings = await case_files.collect_ai_file_rows(
        get_db, parse_file,
        case_id=file_scope.get("case_id"),
        paths=file_scope.get("paths") or [],
        session_id=file_scope.get("session_id") or "",
        file_ids=json.dumps(file_scope.get("file_ids") or []),
        allow_cloud_ocr=bool(file_scope.get("allow_cloud_ocr")),
        model=model,
        question=question,
    )
    if visual_files:
        warnings.append("组合问答按原文提取处理所选文件；扫描页/图片页未逐页送入模型，如需逐页阅读请使用“案件文件/本地文件”单独问答。")
    if not rows:
        return [], warnings
    if progress:
        progress(f"已读取所选文件，共 {len(rows)} 个原文片段，正在与知识库、法答网材料统一分配篇幅")
    selected, partial = case_files._budgeted_file_chunks(
        question, rows, model, "", budget_share=budget)
    items = []
    for index, row in enumerate(selected, 1):
        items.append({
            "kind": "files", "file_index": index,
            "title": row.get("display_name") or row.get("relative_path") or "所选文件",
            "source": row.get("relative_path") or "",
            "locator": row.get("locator") or "",
            "case_id": file_scope.get("case_id"),
            "session_id": file_scope.get("session_id") or "",
            "excerpt": (row.get("chunk_text") or "")[:400],
            "block": (f"《{row.get('display_name') or '所选文件'}》"
                      f"来源：{row.get('relative_path') or ''} · {row.get('locator') or ''}\n"
                      f"{row.get('chunk_text') or ''}"),
        })
    if partial:
        warnings.append("所选文件原文较多，已按问题与文档结构分配篇幅；未提供的片段不代表原文件缺失。")
    return items, warnings


COMBINED_RULES = (
    "你是法律工作助手。本次同时提供三类材料：知识库文章、法答网答问、所选文件。\n"
    "1. 只能依据下方材料回答，材料没有的事实、条号、案号、金额一律不得补写；不确定就说明缺失。\n"
    "2. 每条材料前有【依据N】编号。引用时在对应句子后写【依据N】，可连写多个；不得引用未提供的编号。\n"
    "3. 三类材料的性质不同，引用时必须让用户看得出出处：法答网是最高人民法院官方答问观点，写成“法答网观点”；"
    "知识库文章写作“文章《标题》”；所选文件写作“《文件名》+位置”，属于本案材料原文。\n"
    "4. 先按争点（用户问题有几个层次就分几节）分别归纳各方材料，再给结论；同一争点上材料之间不一致或法答网观点与文章观点不同时，"
    "并列说明各自内容与依据，不要自行择一。\n"
    "5. 严格区分三种内容：材料原文 / 材料中的观点 / 你的归纳。不得把归纳说成原文。\n"
    "6. 材料未覆盖的部分单列“未覆盖与待核实”，不得因为没有材料就断言不存在或没有相关规定。\n"
    "7. 全文只使用本消息材料前的【依据N】编号，不要使用 [FILE:…]、[REF:…] 或自造编号。\n"
    "8. 使用 Markdown：标题、列表各占一行，段落之间空行。不要输出表格以外的排版指令。"
)


def build_messages(question, items, skill_instruction=""):
    blocks = []
    for index, item in enumerate(items, 1):
        blocks.append(f"【依据{index}｜{SOURCE_LABELS[item['kind']]}】\n{item['block']}")
    materials = "\n\n---\n\n".join(blocks)
    system = (skill_instruction + "\n\n" if skill_instruction else "") + COMBINED_RULES
    user = (f"以下是本次提供的材料，共 {len(items)} 条：\n\n{materials}\n\n"
            f"----\n\n用户问题：{question}\n\n请按上述规则回答，并在正文中使用【依据N】标注出处。")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


MARKER = re.compile(r"【依据(\d+)】")


def map_citations(answer, items):
    """Renumber only the evidence the answer actually cites, so the source count is honest."""
    order, mapping = [], {}
    for match in MARKER.finditer(answer or ""):
        number = int(match.group(1))
        if not 1 <= number <= len(items):
            continue
        if number not in mapping:
            mapping[number] = len(order) + 1
            order.append(items[number - 1])
    if not order:
        return MARKER.sub("", answer or ""), [], False
    cleaned = MARKER.sub(lambda m: f"【依据{mapping[int(m.group(1))]}】"
                         if int(m.group(1)) in mapping else "", answer)
    return cleaned, order, True


def citation_payload(item, index):
    """Shape one evidence item as the citation card the shared panel already renders."""
    if item["kind"] == "knowledge":
        return {
            "id": item["article_id"], "article_id": item["article_id"],
            "title": item["title"], "source": item.get("source") or "",
            "quote": item.get("excerpt") or "", "excerpt": item.get("excerpt") or "",
            "source_type": "article", "citation_index": index,
        }
    if item["kind"] == "fada":
        return {
            "source_type": "fada", "id": item.get("id"), "idx": item.get("idx"),
            "batch": item.get("batch"), "topic": item.get("topic") or "",
            "question": (item.get("question") or "")[:80],
            "title": item.get("title") or "法答网答问",
            "excerpt": item.get("excerpt") or "", "citation_index": index,
        }
    payload = {
        "id": f"file-{index}", "title": item.get("title") or "所选文件",
        "source": item.get("source") or "", "locator": item.get("locator") or "",
        "heading": item.get("locator") or "", "quote": item.get("excerpt") or "",
        "source_type": "local_file" if item.get("case_id") else "local_attachment",
        "citation_index": index,
    }
    if item.get("case_id"):
        payload["case_id"] = int(item["case_id"])
    else:
        payload["session_id"] = item.get("session_id") or ""
        payload["source"] = item.get("source") or ""
    return payload


async def answer_combined(question, model, sources, *, get_db, call_ai, parse_file,
                          kb_scope=None, fada_scope=None, file_scope=None,
                          skill_instruction="", progress=None):
    """Collect every selected source, then answer once with unified citations."""
    from .ai_context import model_budget
    wanted = [name for name in ("knowledge", "fada", "files") if name in sources]
    if not wanted:
        raise HTTPException(status_code=400, detail="请至少选择一个数据源")
    budget = max(6000, model_budget(model) - FIXED_RESERVE)
    free = budget - _tokens(question)
    if free <= 0:
        raise HTTPException(status_code=413, detail="问题过长，请缩短后重试")
    weight = sum(SHARES[name] for name in wanted)
    shares = {name: int(free * SHARES[name] / weight) for name in wanted}
    items, warnings = [], []
    conn = None
    try:
        if "knowledge" in wanted:
            if progress:
                progress("正在检索知识库文章")
            conn = get_db()
            found, notes = knowledge_evidence(question, conn, kb_scope, shares["knowledge"], progress)
            conn.close()
            conn = None
            items.extend(found)
            warnings.extend(notes)
        if "fada" in wanted:
            if progress:
                progress("正在检索法答网答问")
            found, notes = fada_evidence(question, fada_scope, shares["fada"], progress)
            items.extend(found)
            warnings.extend(notes)
        if "files" in wanted:
            if progress:
                progress("正在读取所选文件原文")
            found, notes = await file_evidence(
                question, model, file_scope or {}, shares["files"], get_db, parse_file, progress)
            items.extend(found)
            warnings.extend(notes)
    finally:
        if conn is not None:
            conn.close()
    if not items:
        raise HTTPException(
            status_code=422,
            detail="所选来源都没有取得可用材料：" + "；".join(warnings) if warnings
            else "所选来源都没有取得可用材料，请调整问题或来源后重试")
    # Keep one result per available source when trimming the assembled prompt.
    messages = build_messages(question, items, skill_instruction)
    while sum(_tokens(message["content"]) for message in messages) > budget:
        counts = {name: sum(item["kind"] == name for item in items) for name in wanted}
        removable = [index for index, item in enumerate(items) if counts[item["kind"]] > 1]
        if not removable:
            raise HTTPException(status_code=413, detail="所选材料超出模型输入容量，请缩小材料范围后重试")
        longest = max(removable, key=lambda index: _tokens(items[index]["block"]))
        items.pop(longest)
        messages = build_messages(question, items, skill_instruction)
    breakdown = {name: sum(item["kind"] == name for item in items) for name in wanted}
    if progress:
        progress(f"已汇总 {len(items)} 条材料，正在统一归纳")
    answer, reasoning, actual_model = await call_ai(model, messages)
    answer = str(answer or "").strip()
    if not answer:
        raise HTTPException(status_code=502, detail="AI 未返回回答正文")
    clean, cited, matched = map_citations(answer, items)
    # Span numbers belong to a single file's own view; here every source shares
    # one numbering, so a stray [FILE:n] would jump to the wrong material.
    clean = re.sub(r"\[FILE:\d+\]", "", clean).strip()
    if not matched:
        cited = items
        warnings.append("本次回答未标注【依据N】，请按下方材料和原文自行核对结论。")
    payload = [citation_payload(item, index) for index, item in enumerate(cited, 1)]
    kinds = sorted({item["kind"] for item in cited})
    trace = [
        f"本次同时使用{len(wanted)}个数据源：" + "、".join(SOURCE_LABELS[name] for name in wanted),
        "材料条数：" + "、".join(f"{SOURCE_LABELS[name]} {breakdown.get(name, 0)} 条" for name in wanted),
    ]
    if len(kinds) > 1:
        trace.append("回答引用了多个来源，具体出处见引用卡片。")
    return {
        "answer": clean,
        "reasoning": reasoning or "",
        "model_used": actual_model,
        "source_mode": "combined",
        "sources": [],
        "cited_sources": payload,
        "external_sources": [],
        "warnings": warnings,
        "research_trace": trace,
        "source_breakdown": breakdown,
        "combined_sources": wanted,
    }
