#!/usr/bin/env python3
"""Audit legal_kb.db for likely bad imported records.

Default mode is read-only and prints a report. Use --delete-flagged only after
reviewing the output.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "legal_kb.db"
AUTHOR_NOISE = {
    "作者:名称已清空",
    "作者:专业规则创新价值",
    "作者:指导性案例",
    "作者:喜欢作者其它金额",
}


def strip_html(value: str) -> str:
    value = re.sub(r"<(script|style|noscript|iframe)[\s\S]*?</\1>", " ", value or "", flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"https?://\S+", " ", value)
    value = value.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", value).strip()


def classify(row: sqlite3.Row) -> list[str]:
    content = row["content"] or ""
    summary = row["summary"] or ""
    tags = json.loads(row["tags"] or "[]")
    plain = strip_html(content)
    compact = re.sub(r"\s+", "", plain)
    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", compact))
    d_noise = len(re.findall(r"D[，。,.、]?", compact + summary))
    img_count = len(re.findall(r"<img\b", content, flags=re.I))
    reasons = []

    if chinese_count < 80:
        reasons.append("正文中文过短")
    if d_noise >= 12 and d_noise > max(8, chinese_count * 0.2):
        reasons.append("疑似D乱码")
    if img_count and chinese_count < 180 and re.search(r"来源[:：]|END|指导性案例|本文仅供交流学习", compact):
        reasons.append("疑似只抓到来源/尾图")
    if any(tag in AUTHOR_NOISE for tag in tags):
        reasons.append("作者标签疑似误判")
    if summary and len(re.findall(r"D[，。,.、]?", summary)) >= 8:
        reasons.append("摘要疑似乱码")
    return reasons


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit legal knowledge base records.")
    parser.add_argument("--db", default=str(DB_PATH), help="Path to legal_kb.db")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    parser.add_argument("--delete-flagged", action="store_true", help="Delete flagged records after audit")
    parser.add_argument("--repair-author-tags", action="store_true", help="Remove known bad author tags")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, title, summary, content, source_type, source_url, source_filename, tags, created_at FROM articles ORDER BY id"
    ).fetchall()

    flagged = []
    for row in rows:
        reasons = classify(row)
        if reasons:
            flagged.append({
                "id": row["id"],
                "title": row["title"],
                "source_type": row["source_type"],
                "source": row["source_url"] or row["source_filename"] or "",
                "created_at": row["created_at"],
                "reasons": reasons,
            })

    repaired_author_tags = 0
    if args.repair_author_tags:
        for row in rows:
            tags = json.loads(row["tags"] or "[]")
            cleaned = [tag for tag in tags if tag not in AUTHOR_NOISE]
            if cleaned != tags:
                if not any(str(tag).startswith("作者:") for tag in cleaned):
                    cleaned.append("作者:未知")
                conn.execute(
                    "UPDATE articles SET tags=? WHERE id=?",
                    (json.dumps(cleaned, ensure_ascii=False), row["id"]),
                )
                repaired_author_tags += 1
        conn.commit()

    if args.delete_flagged and flagged:
        ids = [item["id"] for item in flagged]
        placeholders = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM articles WHERE id IN ({placeholders})", ids)
        conn.commit()

    conn.close()

    result = {
        "db": str(Path(args.db).resolve()),
        "total": len(rows),
        "flagged_count": len(flagged),
        "deleted": bool(args.delete_flagged),
        "repaired_author_tags": repaired_author_tags,
        "flagged": flagged,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"数据库：{result['db']}")
        print(f"总记录：{result['total']}，疑似问题记录：{result['flagged_count']}")
        if repaired_author_tags:
            print(f"已修复作者误判标签：{repaired_author_tags} 条")
        if args.delete_flagged:
            print("已删除上述疑似问题记录。")
        for item in flagged:
            reasons = "、".join(item["reasons"])
            print(f"- #{item['id']} {item['title']} [{reasons}]")
            if item["source"]:
                print(f"  来源：{item['source']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
