"""Two-level article taxonomy and non-destructive classification state."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sqlite3
from typing import Any, Iterable


# Specific legal issues found in article titles and summaries. These are
# proposals, never formal catalog entries until the user accepts them.
CHILD_TOPIC_RULES: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "建设工程": (
        ("工程价款与优先受偿", ("工程价款", "工程款", "优先受偿权", "结算支付")),
        ("招标投标", ("招标", "投标", "中标")),
        ("资质借用与转包", ("挂靠", "资质借用", "转包", "违法分包")),
        ("工程质量与验收", ("工程质量", "竣工验收", "质量缺陷")),
        ("实际施工人", ("实际施工人",)),
        ("工期与索赔", ("工期", "停窝工", "工期延误")),
    ),
    "强制执行": (
        ("执行异议", ("执行异议", "案外人异议")),
        ("司法拍卖与以物抵债", ("司法拍卖", "网拍", "流拍", "以物抵债")),
        ("参与分配", ("参与分配", "分配方案")),
        ("执行终本与恢复", ("终结本次执行", "终本", "恢复执行")),
    ),
    "合同法": (
        ("合同效力", ("合同效力", "合同无效", "无效合同")),
        ("违约责任", ("违约责任", "违约金", "可得利益")),
        ("合同解除", ("合同解除", "解除合同")),
        ("买卖合同", ("买卖合同",)),
        ("租赁合同", ("租赁合同", "房屋租赁")),
    ),
    "破产法": (
        ("破产重整", ("破产重整", "重整计划", "预重整")),
        ("破产清算", ("破产清算", "清算程序")),
        ("管理人履职", ("破产管理人", "管理人报酬", "管理人履职")),
        ("债权申报与审查", ("债权申报", "债权审查", "债权确认")),
        ("取回权与抵销权", ("取回权", "破产抵销")),
    ),
    "公司法": (
        ("股东出资", ("股东出资", "抽逃出资", "出资加速", "未缴出资")),
        ("股权转让", ("股权转让", "股权代持")),
        ("公司决议与治理", ("公司决议", "股东会决议", "董事会决议")),
        ("公司人格否认", ("人格否认", "人格混同")),
    ),
    "房地产": (
        ("商品房买卖", ("商品房买卖", "商品房销售", "购房人")),
        ("房屋租赁", ("房屋租赁", "租赁合同")),
        ("土地征收与补偿", ("土地征收", "征地补偿", "房屋征收")),
        ("物业服务", ("物业服务", "物业费")),
    ),
    "担保合同": (
        ("保证责任", ("保证责任", "保证人", "连带保证")),
        ("抵押权", ("抵押权", "抵押登记")),
        ("担保效力", ("担保合同效力", "对外担保", "担保函")),
    ),
    "金融证券": (
        ("私募基金", ("私募基金", "基金管理人")),
        ("融资租赁", ("融资租赁",)),
        ("金融借款", ("金融借款", "借款合同")),
    ),
    "商事仲裁": (
        ("仲裁协议", ("仲裁协议", "仲裁条款")),
        ("裁决撤销与执行", ("撤销仲裁裁决", "仲裁裁决执行")),
    ),
    "行政法": (
        ("行政诉讼", ("行政诉讼", "行政起诉")),
        ("行政处罚", ("行政处罚",)),
        ("政府信息公开", ("政府信息公开",)),
    ),
    "知识产权": (
        ("商标", ("商标侵权", "商标权")),
        ("著作权", ("著作权", "版权侵权")),
        ("专利", ("专利侵权", "专利权")),
    ),
    "劳动法": (
        ("劳动合同", ("劳动合同", "劳动关系")),
        ("工资支付", ("工资支付", "拖欠工资", "农民工工资")),
        ("工伤", ("工伤认定", "工伤保险")),
    ),
    "税务": (
        ("企业所得税", ("企业所得税",)),
        ("增值税", ("增值税",)),
        ("税收征管", ("税收征管", "税费征管")),
    ),
}

# AI used to describe the same reusable topic with a different case-specific
# phrase for nearly every article. Only these unambiguous families are folded
# together; unknown phrases stay as candidates awaiting another article.
SUGGESTION_FAMILIES: dict[str | None, tuple[tuple[str, str, tuple[str, ...]], ...]] = {
    None: (
        ("民事诉讼", r"民事诉讼|民事案件管辖|协议管辖|举证责任|诉讼[中外]?自认|民事检察监督", ("民事诉讼", "管辖", "举证责任", "自认", "民事检察监督")),
        ("民法总则", r"民法典总则|民事主体|法律行为", ("民法典总则", "民事主体", "法律行为")),
        ("物权", r"物权|共有与优先购买权|预告登记|善意取得", ("物权", "共有", "预告登记", "善意取得")),
        ("国有企业", r"国有企业|国有资产", ("国有企业", "国有资产")),
        ("民商事审判", r"民商事审判|民商事司法解释|八民纪要", ("民商事审判", "司法解释", "八民纪要")),
    ),
    "公司法": (
        ("公司清算", r"清算|公司解散", ("公司清算", "清算责任", "公司解散")),
        ("股东权益保护", r"股东权益|股东代表诉讼|股东分歧", ("股东权益", "股东代表诉讼", "股东分歧")),
        ("国企合规", r"国有企业|国有资产|国企", ("国有企业", "国有资产", "国企")),
        ("公司人格否认", r"人格否认|实际控制人.*责任|滥用法人独立", ("人格否认", "实际控制人", "人格混同")),
        ("股东出资", r"出资|注册资本|资本充实", ("股东出资", "出资", "注册资本")),
        ("股权转让", r"股权转让", ("股权转让", "股权受让")),
        ("公司决议与治理", r"公司决议|公司组织|股东会|董事|利润分配|关联交易|公司治理", ("公司决议", "股东会", "董事会", "公司治理")),
    ),
    "强制执行": (
        ("财产保全", r"财产保全|反担保", ("财产保全", "反担保")),
        ("财产调查与查控", r"网络执行查控|财产调查|电子数据调取", ("财产调查", "执行查控", "网络查控")),
        ("刑事涉财产执行", r"刑事追缴|刑事裁判涉财产", ("刑事追缴", "涉财产执行", "案外人资金")),
        ("对待给付执行", r"对待给付", ("对待给付", "履行顺序")),
        ("执行款分配", r"执行回款|执行抵扣|本息抵扣", ("执行回款", "抵扣顺序", "本息抵扣")),
    ),
    "合同法": (
        ("合同效力", r"合同.*效力|合同生效|不法原因给付|违规请托|违背公序良俗|恶意串通|职业放贷", ("合同效力", "合同无效", "合同生效", "不法原因给付")),
        ("民间借贷", r"民间借贷", ("民间借贷", "借贷合同")),
        ("合同履行", r"继续履行|司法终止", ("合同履行", "继续履行")),
    ),
    "破产法": (
        ("购房人权益", r"购房.*权益|购房消费者", ("购房人权益", "购房消费者")),
        ("执行转破产", r"执行转破产", ("执行转破产", "执转破")),
        ("债权申报与审查", r"债权申报|债权确认|债权审查", ("债权申报", "债权确认", "债权审查")),
    ),
    "行政法": (
        ("政府拖欠账款", r"政府.*拖欠.*账款|政府拖欠账款", ("政府拖欠账款", "政府机关拖欠")),
        ("环境保护", r"环境保护|环境监管", ("环境保护", "环境监管")),
    ),
    "刑民交叉": (
        ("刑民交叉程序", r"民刑交叉.*程序|刑民交叉.*处理|刑民交叉.*界限", ("刑民交叉", "民刑交叉", "程序处理")),
        ("涉刑合同效力", r"涉刑合同|刑事犯罪与合同效力", ("涉刑合同", "合同效力")),
    ),
}


def canonical_suggestion(name: str, parent_name: str | None) -> tuple[str, list[str]]:
    """Return a known broad topic and its matching terms, or the original name."""
    for broad_name, pattern, keywords in SUGGESTION_FAMILIES.get(parent_name, ()):
        if re.search(pattern, name):
            return broad_name, list(keywords)
    return name, []


def _now() -> str:
    return dt.datetime.now().isoformat()


def _items(raw: Any) -> list[str]:
    try:
        values = json.loads(raw or "[]") if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        values = []
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip())) if isinstance(values, list) else []


def _json(values: Iterable[str]) -> str:
    return json.dumps(list(values), ensure_ascii=False)


def is_source_label(name: str) -> bool:
    """Only unmistakable web addresses are omitted from the topic hierarchy."""
    value = name.strip().lower()
    return bool(re.match(r"^(?:https?://|www\.)\S+|^[\w.-]+\.[a-z]{2,}(?:/\S*)?$", value))


def ensure_article_triggers(conn: sqlite3.Connection) -> None:
    """Cover imports which write articles directly instead of using save_article."""
    conn.executescript("""
        CREATE TRIGGER IF NOT EXISTS article_domain_queue_insert AFTER INSERT ON articles
        BEGIN
            INSERT OR REPLACE INTO domain_classification_jobs(article_id,status,updated_at)
            VALUES (new.id,'queued',datetime('now'));
        END;
        CREATE TRIGGER IF NOT EXISTS article_domain_queue_edit
        AFTER UPDATE OF title,content ON articles
        BEGIN
            INSERT OR REPLACE INTO domain_classification_jobs(article_id,status,updated_at)
            VALUES (new.id,'queued',datetime('now'));
        END;
    """)


def ensure_roots(conn: sqlite3.Connection, predefined: Iterable[str]) -> None:
    names = list(predefined)
    suppressed = {row[0] for row in conn.execute("SELECT name FROM domain_taxonomy_suppressed_roots")}
    for row in conn.execute("SELECT domains FROM articles"):
        names.extend(_items(row[0]))
    for name in dict.fromkeys(names):
        if name != "综合法律" and name not in suppressed and not is_source_label(name):
            conn.execute(
                "INSERT OR IGNORE INTO domain_taxonomy(name,parent_id,created_at) VALUES (?,NULL,?)",
                (name, _now()),
            )


def taxonomy(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    roots = [dict(row) for row in conn.execute(
        "SELECT id,name,keywords_json FROM domain_taxonomy WHERE parent_id IS NULL ORDER BY id"
    )]
    children = [dict(row) for row in conn.execute(
        "SELECT id,name,parent_id,keywords_json FROM domain_taxonomy WHERE parent_id IS NOT NULL ORDER BY sort_order,id"
    )]
    for root in roots:
        root["children"] = [child for child in children if child["parent_id"] == root["id"]]
    return roots


def _topic_match(title: str, summary: str, terms: Iterable[str]) -> bool:
    """Require a topic to be central, rather than an incidental body mention."""
    matches = [term for term in terms if len(term) >= 2]
    return any(term in title for term in matches) or any(term in summary[:180] for term in matches) or sum(
        term in summary for term in matches
    ) >= 2


def rule_child_candidates(conn: sqlite3.Connection, title: str, summary: str, roots: Iterable[str]) -> list[dict[str, Any]]:
    """Infer reusable second-level topics from article subject matter."""
    parent_ids = {row["name"]: row["id"] for row in taxonomy(conn)}
    candidates = []
    for root_name in roots:
        parent_id = parent_ids.get(root_name)
        if parent_id is None:
            continue
        for name, terms in CHILD_TOPIC_RULES.get(root_name, ()):
            if _topic_match(title, summary, terms):
                candidates.append({"name": name, "parent_id": parent_id, "keywords": list(terms)})
    return candidates[:5]


def category_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    roots = taxonomy(conn)
    counts: dict[str, int] = {}
    for row in conn.execute("SELECT domains FROM articles"):
        for name in _items(row[0]):
            if not is_source_label(name):
                counts[name] = counts.get(name, 0) + 1
    child_counts = {row[0]: row[1] for row in conn.execute("""
        SELECT subcategory_id, COUNT(*) FROM article_subcategory_choices
        WHERE mode <> 'excluded' GROUP BY subcategory_id
    """)}
    for root in roots:
        root["domain"] = root["name"]
        root["count"] = counts.get(root["name"], 0)
        for child in root["children"]:
            child["count"] = child_counts.get(child["id"], 0)
    roots.sort(key=lambda row: (-row["count"], row["name"]))
    return roots


def _keywords_match(text: str, keywords: list[str], name: str) -> bool:
    terms = [term for term in keywords if len(term) >= 2] or [name]
    return bool(text and any(term in text for term in terms))


def classified_children(conn: sqlite3.Connection, article_id: int, title: str, summary: str, roots: list[str]) -> list[int]:
    matches: list[int] = []
    for root in taxonomy(conn):
        if root["name"] not in roots:
            continue
        for child in root["children"]:
            if _topic_match(title, summary, _items(child["keywords_json"]) or [child["name"]]):
                matches.append(child["id"])
    return matches


def apply_classification(
    conn: sqlite3.Connection, article_id: int, auto_roots: list[str], auto_children: list[int],
    *, status: str = "done", expected_hash: str | None = None,
) -> bool:
    article = conn.execute(
        "SELECT title,content,domains,manual_domains,excluded_auto_domains FROM articles WHERE id=?",
        (article_id,),
    ).fetchone()
    if article is None:
        return False
    fingerprint = hashlib.sha256(((article["title"] or "") + (article["content"] or "")).encode()).hexdigest()
    if expected_hash and fingerprint != expected_hash:
        return False
    conn.execute(
        "INSERT OR IGNORE INTO domain_classification_jobs(article_id,status,updated_at) VALUES (?,'queued',?)",
        (article_id, _now()),
    )
    manual = _items(article["manual_domains"])
    excluded = set(_items(article["excluded_auto_domains"]))
    roots = list(dict.fromkeys(
        [name for name in auto_roots if name not in excluded and name != "综合法律" and not is_source_label(name)]
        + [name for name in manual if not is_source_label(name)]
    ))
    choices = {row["subcategory_id"]: row["mode"] for row in conn.execute(
        "SELECT subcategory_id,mode FROM article_subcategory_choices WHERE article_id=?", (article_id,)
    )}
    child_parents = {row["id"]: row["parent_name"] for row in conn.execute("""
        SELECT child.id,root.name AS parent_name FROM domain_taxonomy child
        JOIN domain_taxonomy root ON root.id=child.parent_id WHERE child.parent_id IS NOT NULL
    """)}
    for child_id, mode in choices.items():
        if mode == "manual" and child_parents.get(child_id) not in roots and child_parents.get(child_id) not in excluded:
            roots.append(child_parents[child_id])
    conn.execute("DELETE FROM article_subcategory_choices WHERE article_id=? AND mode='auto'", (article_id,))
    for child_id in set(auto_children):
        if child_parents.get(child_id) in roots and choices.get(child_id) not in {"manual", "excluded"}:
            conn.execute(
                "INSERT INTO article_subcategory_choices(article_id,subcategory_id,mode) VALUES (?,?,'auto')",
                (article_id, child_id),
            )
    conn.execute(
        "UPDATE articles SET domains=?,manual_domains=? WHERE id=?",
        (_json(roots), _json(manual), article_id),
    )
    conn.execute(
        "UPDATE domain_classification_jobs SET status=?,content_hash=?,auto_domains_json=?,updated_at=?,error='' WHERE article_id=?",
        (status, fingerprint, _json(auto_roots), _now(), article_id),
    )
    return True


def suggest(conn: sqlite3.Connection, name: str, parent_id: int | None, article_id: int, keywords: list[str]) -> int | None:
    name = re.sub(r"\s+", "", str(name or ""))[:40]
    parent = conn.execute("SELECT name FROM domain_taxonomy WHERE id=? AND parent_id IS NULL", (parent_id,)).fetchone() if parent_id is not None else None
    name, family_keywords = canonical_suggestion(name, parent[0] if parent else None)
    if family_keywords:
        keywords = family_keywords
    # A taxonomy node must be a reusable topic, not a sentence describing one
    # article's holding. Narrow issues remain searchable in article text.
    max_length = 12 if parent_id is not None else 8
    if (not 2 <= len(name) <= max_length or is_source_label(name)
            or any(token in name for token in ("来源", "网址", "其他", "综合"))
            or re.search(r"[：:，,；;。！？?!（）()《》“”]", name)):
        return None
    siblings = conn.execute("SELECT name FROM domain_taxonomy WHERE parent_id IS ?", (parent_id,)).fetchall()
    proposals = conn.execute(
        "SELECT id,name,status FROM domain_suggestions WHERE parent_id IS ?", (parent_id,)
    ).fetchall()
    def comparable(value: str) -> str:
        return re.sub(r"(法|法律|纠纷|争议)$", "", value.strip())
    normalized = comparable(name)
    if any(comparable(row[0]) == normalized for row in siblings):
        return None
    existing = next((row for row in proposals if comparable(row["name"]) == normalized), None)
    if existing:
        if existing["status"] == "pending":
            conn.execute("INSERT OR IGNORE INTO domain_suggestion_articles(suggestion_id,article_id) VALUES (?,?)",
                         (existing["id"], article_id))
            if family_keywords:
                conn.execute("UPDATE domain_suggestions SET keywords_json=? WHERE id=?",
                             (_json(family_keywords), existing["id"]))
            return existing["id"]
        return None
    cur = conn.execute(
        "INSERT INTO domain_suggestions(name,parent_id,keywords_json,article_id,created_at) VALUES (?,?,?,?,?)",
        (name, parent_id, _json(keywords[:8]), article_id, _now()),
    )
    conn.execute("INSERT OR IGNORE INTO domain_suggestion_articles(suggestion_id,article_id) VALUES (?,?)",
                 (cur.lastrowid, article_id))
    return cur.lastrowid


def backfill_reusable_suggestions(conn: sqlite3.Connection) -> None:
    """Build broad review candidates from historical one-article AI proposals.

    Original proposals remain intact for auditability. The candidate table's
    unique article links make this safe to rerun on an interrupted migration.
    """
    rows = list(conn.execute("""SELECT s.id,s.name,s.parent_id,s.article_id,s.keywords_json,
                                    p.name AS parent_name
                             FROM domain_suggestions s
                             LEFT JOIN domain_taxonomy p ON p.id=s.parent_id
                             WHERE s.status='pending' ORDER BY s.id"""))
    for row in rows:
        broad_name, broad_keywords = canonical_suggestion(row["name"], row["parent_name"])
        if not broad_keywords:
            continue
        article_ids = [item[0] for item in conn.execute(
            "SELECT article_id FROM domain_suggestion_articles WHERE suggestion_id=?", (row["id"],)
        )]
        if not article_ids and row["article_id"] is not None:
            article_ids = [row["article_id"]]
        for article_id in article_ids:
            suggest(conn, broad_name, row["parent_id"], article_id, broad_keywords)


def update_job_domain_names(conn: sqlite3.Connection, renames: dict[str, str], deletes: set[str]) -> None:
    for row in conn.execute("SELECT article_id,auto_domains_json FROM domain_classification_jobs"):
        values = _items(row["auto_domains_json"])
        updated = list(dict.fromkeys(renames.get(name, name) for name in values if name not in deletes))
        if updated != values:
            conn.execute("UPDATE domain_classification_jobs SET auto_domains_json=? WHERE article_id=?",
                         (_json(updated), row["article_id"]))
