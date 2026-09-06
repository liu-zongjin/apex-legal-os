#!/usr/bin/env python3
"""Read-only structural audit for all stored knowledge-base articles."""

from __future__ import annotations

import argparse
import collections
import re
import sqlite3
import sys
from pathlib import Path

from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.article_structure import classify_article_block, is_heading_class  # noqa: E402


HEADING_CLASSES = {"body-heading", "body-heading-secondary", "body-label-heading"}


def stored_blocks(content: str):
    if re.search(r"<\w+[^>]*>", (content or "")[:2000]):
        soup = BeautifulSoup(content, "html.parser")
        for node in soup.select("p, h1, h2, h3, h4, h5, h6, li, blockquote"):
            text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
            if not text:
                continue
            classes = set(node.get("class") or [])
            yield text, classes, node.name.lower()
    else:
        for block in re.split(r"\n{2,}", content or ""):
            text = re.sub(r"\s+", " ", block).strip()
            if text:
                yield text, set(), "text"


def inspect_article(row):
    blocks = list(stored_blocks(row["content"] or ""))
    counts = collections.Counter()
    examples = []
    title_key = re.sub(r"\s+", "", row["title"] or "")
    previous_text = ""

    for index, (text, classes, tag) in enumerate(blocks):
        predicted = classify_article_block(
            text,
            source_tag=tag,
            explicit_heading=tag.startswith("h"),
        )
        stored_heading = bool(classes & HEADING_CLASSES) or tag.startswith("h")
        if stored_heading and not is_heading_class(predicted):
            counts["false_heading"] += 1
            examples.append(("false_heading", text[:90]))
        if not stored_heading and is_heading_class(predicted):
            counts["missed_heading"] += 1
            examples.append(("missed_heading", text[:90]))
        if "body-toc-entry" in classes and predicted == "body-list-item":
            counts["toc_list_pollution"] += 1
        if len(text) >= 1200:
            counts["oversized_block"] += 1
        if len(text) <= 3 and re.fullmatch(r"[，。；：、！？,.!?;:（）()【】《》]+", text):
            counts["orphan_punctuation"] += 1
        if index and re.match(r"^[，,；;。！？?!、]", text):
            counts["continuation_fragment"] += 1
            examples.append(("continuation_fragment", f"{previous_text[-35:]} ⟶ {text[:55]}"))
        if previous_text and previous_text == text:
            counts["adjacent_duplicate"] += 1
        if index < 5 and title_key and re.sub(r"\s+", "", text) == title_key:
            counts["repeated_document_title"] += 1
        previous_text = text
    return counts, examples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(PROJECT_ROOT / "legal_kb.db"))
    parser.add_argument("--limit", type=int, default=25, help="maximum articles shown per issue")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, title, source_type, content FROM articles ORDER BY id").fetchall()
    conn.close()

    totals = collections.Counter()
    by_issue = collections.defaultdict(list)
    source_counts = collections.Counter(row["source_type"] or "unknown" for row in rows)
    html_count = 0
    for row in rows:
        if re.search(r"<\w+[^>]*>", (row["content"] or "")[:2000]):
            html_count += 1
        counts, examples = inspect_article(row)
        totals.update(counts)
        example_map = collections.defaultdict(list)
        for issue, text in examples:
            if len(example_map[issue]) < 2:
                example_map[issue].append(text)
        for issue, count in counts.items():
            if count:
                by_issue[issue].append((count, row["id"], row["source_type"], row["title"], example_map[issue]))

    print(f"articles={len(rows)} html={html_count} plain={len(rows) - html_count}")
    print("sources=" + ", ".join(f"{key}:{value}" for key, value in source_counts.most_common()))
    for issue, total in totals.most_common():
        print(f"\n[{issue}] total={total} articles={len(by_issue[issue])}")
        for count, article_id, source_type, title, examples in sorted(by_issue[issue], reverse=True)[:args.limit]:
            suffix = " | ".join(examples)
            print(f"  {count:4d}  #{article_id:<4d} {source_type:<12} {title[:55]}" + (f" :: {suffix}" if suffix else ""))


if __name__ == "__main__":
    main()

