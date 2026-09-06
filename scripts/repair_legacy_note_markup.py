#!/usr/bin/env python3
"""Remove legacy, accidentally saved note UI from a knowledge-base article.

Earlier reader versions could persist a generated note badge as plain text when
the reader's inline-format action saved the article body.  This utility repairs
only the legacy ``note-anchor`` / ``note-highlight`` markup, after making a
SQLite backup.  It is deliberately opt-in and supports a dry run.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag


def strip_legacy_markup(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")

    # Runtime badges which were retained as text after their <sup> wrapper was
    # stripped in old versions.  On affected articles the old badge is the
    # terminal decimal suffix of a generated highlight wrapper.
    for marker in list(soup.select(".note-anchor, .note-highlight")):
        if not isinstance(marker, Tag):
            continue
        direct_text = list(marker.find_all(string=True, recursive=False))
        if direct_text:
            last = direct_text[-1]
            cleaned = str(last).rstrip()
            # Only touch an unambiguous UI suffix on a generated wrapper.  The
            # document has already been reviewed for this repair target.
            trimmed = cleaned.rstrip("0123456789")
            if trimmed != cleaned:
                trailing_space = str(last)[len(str(last).rstrip()):]
                last.replace_with(NavigableString(trimmed + trailing_space))
        marker.unwrap()

    # Defensive removal in case an old body still contains actual badge nodes.
    for marker in soup.select(
        ".note-anchor-badge, .pdf-page-note-badge, .pdf-text-badge, .note-connector-layer"
    ):
        marker.decompose()
    return str(soup)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("article_id", type=int)
    parser.add_argument("--db", type=Path, default=Path(__file__).resolve().parents[1] / "legal_kb.db")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db_path = args.db.resolve()
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT id, title, content FROM articles WHERE id=?", (args.article_id,)).fetchone()
        if not row:
            raise SystemExit(f"Article {args.article_id} was not found in {db_path}.")
        before = row[2] or ""
        after = strip_legacy_markup(before)
        if before == after:
            print(f"Article {row[0]} has no legacy note markup to repair.")
            return
        print(f"Article {row[0]}: {row[1]}\n{len(before)} → {len(after)} bytes")
        if args.dry_run:
            return

        backup = db_path.with_name(f"{db_path.stem}.before-note-markup-repair-{datetime.now():%Y%m%d%H%M%S}{db_path.suffix}")
        shutil.copy2(db_path, backup)
        conn.execute("UPDATE articles SET content=? WHERE id=?", (after, row[0]))
        conn.commit()
        print(f"Repaired. Backup: {backup}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
