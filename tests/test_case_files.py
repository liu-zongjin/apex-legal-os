import errno
import plistlib
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from backend.case_files import (
    PARSER_VERSION,
    _cached_index,
    _chunks,
    _copy_destination,
    _directory_items,
    _ensure_schema,
    _expand_ai_paths,
    _finder_tags_for_path,
    _finder_tag_targets,
    _finder_tag_values_for_color,
    _apply_finder_tag_values,
    _set_finder_info_color,
    _write_finder_tag_values,
    _located_chunks,
    _parse_finder_tags,
    _resolve_inside,
    _rewrite_index_paths,
    _safe_relative,
    _score_chunks,
    _budgeted_file_chunks,
    _store_index,
)


class CaseFilesTests(unittest.TestCase):
    def test_file_evidence_budget_preserves_each_file_and_original_spans(self):
        from backend import ai_context
        rows=[{'relative_path':f'{i}.txt','display_name':f'{i}.txt','chunk_index':0,'locator':'第1页',
               'chunk_text':''.join(f'匿名合同明细项目{j}金额{i+j}元。' for j in range(1000))} for i in range(3)]
        selected,partial=_budgeted_file_chunks('合同金额是多少',rows,'fixture','')
        self.assertEqual({row['relative_path'] for row in selected},{row['relative_path'] for row in rows})
        self.assertTrue(partial)
        originals={row['relative_path']:row['chunk_text'] for row in rows}
        self.assertTrue(all(row['chunk_text'] in originals[row['relative_path']] for row in selected))
        self.assertLessEqual(sum(ai_context.tokens(row['chunk_text'])+200 for row in selected),14000)
        token=ai_context.CURRENT.set({'budget':24000,'items':[]})
        try:
            ai_context.guard_messages([{'role':'user','content':'\n'.join(row['chunk_text'] for row in selected)}],8000)
        finally:ai_context.CURRENT.reset(token)

    def test_file_budget_cannot_silently_omit_a_selected_file(self):
        from backend import ai_context
        rows=[{'relative_path':str(i),'display_name':str(i),'chunk_index':0,'locator':'第1页','chunk_text':'合同内容。'*100} for i in range(8)]
        token=ai_context.CURRENT.set({'budget':12000})
        try:
            with self.assertRaises(HTTPException) as caught:
                _budgeted_file_chunks('合同内容',rows,'fixture','')
        finally:ai_context.CURRENT.reset(token)
        self.assertEqual(caught.exception.status_code,413)
        self.assertIn('每个文件',caught.exception.detail)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.database = self.root / "case-files.db"

        def get_db():
            connection = sqlite3.connect(self.database)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            return connection

        self.get_db = get_db
        with self.get_db() as connection:
            connection.execute("CREATE TABLE case_manager_cases(id INTEGER PRIMARY KEY,title TEXT)")
            connection.execute("INSERT INTO case_manager_cases(id,title) VALUES (1,'测试案件')")
            connection.commit()
        _ensure_schema(self.get_db)

    def tearDown(self):
        self.temporary.cleanup()

    def test_relative_path_rejects_escape_and_absolute_paths(self):
        for value in ("../outside", "/tmp/outside", "folder/../outside", "folder//file"):
            with self.assertRaises(HTTPException):
                _safe_relative(value)

    def test_symlink_cannot_escape_bound_root(self):
        outside = self.root.parent / f"{self.root.name}-outside"
        outside.mkdir(exist_ok=True)
        try:
            link = self.root / "outside-link"
            link.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(HTTPException):
                _resolve_inside(self.root, "outside-link")
        finally:
            outside.rmdir()

    def test_directory_listing_does_not_calculate_folder_size(self):
        folder = self.root / "资料"
        folder.mkdir()
        (folder / "large.bin").write_bytes(b"x" * 10000)
        (self.root / "说明.txt").write_text("案件说明", encoding="utf-8")
        items = _directory_items(self.root, self.root, show_hidden=False)
        by_name = {item["name"]: item for item in items}
        self.assertIsNone(by_name["资料"]["size"])
        self.assertEqual(by_name["说明.txt"]["size"], len("案件说明".encode("utf-8")))
        self.assertTrue(by_name["说明.txt"]["ai_supported"])
        self.assertEqual(by_name["说明.txt"]["finder_tags"], [])

    def test_finder_tags_decode_binary_plist_color_suffixes(self):
        payload = plistlib.dumps(["Red\n6", "Blue\n3", "自定义标签"], fmt=plistlib.FMT_BINARY)
        self.assertEqual(_parse_finder_tags(payload), [
            {"name": "Red", "color": "red", "color_index": 6},
            {"name": "Blue", "color": "blue", "color_index": 3},
            {"name": "自定义标签", "color": None, "color_index": None},
        ])

    def test_finder_tags_are_read_without_following_symlinks(self):
        path = self.root / "标记文件.txt"
        path.write_text("标签", encoding="utf-8")
        payload = plistlib.dumps(["Green\n4"], fmt=plistlib.FMT_BINARY)
        completed = subprocess.CompletedProcess([], 0, payload.hex().encode("ascii"), b"")
        with patch("backend.case_files.shutil.which", return_value="/usr/bin/xattr"), \
             patch("backend.case_files.subprocess.run", return_value=completed) as run:
            self.assertEqual(_finder_tags_for_path(path)[0]["color"], "green")
        run.assert_called_once_with(
            ["xattr", "-px", "com.apple.metadata:_kMDItemUserTags", str(path)],
            capture_output=True,
            timeout=1,
        )

    def test_finder_color_update_preserves_existing_tag_names(self):
        path = self.root / "标记文件.txt"
        path.write_text("标签", encoding="utf-8")
        with patch("backend.case_files._finder_tags_for_path", return_value=[
            {"name": "重要", "color": "red", "color_index": 6},
            {"name": "待核对", "color": None, "color_index": None},
        ]):
            self.assertEqual(
                _finder_tag_values_for_color(path, 3),
                ["重要\n3", "待核对"],
            )

    def test_finder_color_update_creates_a_color_tag_when_unmarked(self):
        path = self.root / "未标记文件.txt"
        path.write_text("标签", encoding="utf-8")
        with patch("backend.case_files._finder_tags_for_path", return_value=[]):
            self.assertEqual(_finder_tag_values_for_color(path, 6), ["红色\n6"])

    def test_finder_color_clear_keeps_tag_names_without_colors(self):
        path = self.root / "标记文件.txt"
        path.write_text("标签", encoding="utf-8")
        with patch("backend.case_files._finder_tags_for_path", return_value=[
            {"name": "重要", "color": "red", "color_index": 6},
            {"name": "待核对", "color": None, "color_index": None},
        ]):
            self.assertEqual(_finder_tag_values_for_color(path, None), ["重要", "待核对"])

    def test_finder_color_clear_updates_legacy_finder_info_bits(self):
        path = self.root / "标记文件.txt"
        path.write_text("标签", encoding="utf-8")
        with patch("backend.case_files._finder_tag_values_for_color", return_value=["重要"]), \
             patch("backend.case_files._write_finder_tag_values"), \
             patch("backend.case_files._set_finder_info_color") as set_color:
            _apply_finder_tag_values([path], None)
        set_color.assert_called_once_with(path, None)

    def test_finder_info_color_bits_are_changed_without_overwriting_other_flags(self):
        path = self.root / "标记文件.txt"
        path.write_text("标签", encoding="utf-8")
        payload = bytearray(32)
        payload[8] = 0xA5
        payload[9] = 0xFF
        with patch("backend.case_files._read_finder_info", return_value=bytes(payload)), \
             patch("backend.case_files._write_finder_info") as write_info:
            _set_finder_info_color(path, None)
        updated = write_info.call_args.args[1]
        self.assertEqual(updated[8], 0xA5)
        self.assertEqual(updated[9], 0xF1)

    def test_finder_info_color_setting_preserves_other_flags(self):
        path = self.root / "标记文件.txt"
        path.write_text("标签", encoding="utf-8")
        payload = bytearray(32)
        payload[9] = 0xF1
        with patch("backend.case_files._read_finder_info", return_value=bytes(payload)), \
             patch("backend.case_files._write_finder_info") as write_info:
            _set_finder_info_color(path, 3)
        updated = write_info.call_args.args[1]
        self.assertEqual(updated[9], 0xF7)

    def test_empty_finder_tag_values_remove_the_xattr(self):
        path = self.root / "标记文件.txt"
        path.write_text("标签", encoding="utf-8")
        with patch("backend.case_files.os.removexattr", create=True) as remove_xattr:
            _write_finder_tag_values(path, [])
        remove_xattr.assert_called_once_with(
            path, "com.apple.metadata:_kMDItemUserTags", follow_symlinks=False
        )

    def test_missing_finder_tag_xattr_is_already_clear(self):
        path = self.root / "标记文件.txt"
        path.write_text("标签", encoding="utf-8")
        missing = OSError(errno.ENODATA, "missing")
        with patch("backend.case_files.os.removexattr", create=True, side_effect=missing):
            _write_finder_tag_values(path, [])

    def test_finder_color_targets_include_folder_descendants_without_links(self):
        folder = self.root / "案件文件夹"
        nested = folder / "子文件夹"
        nested.mkdir(parents=True)
        child = nested / "证据.txt"
        child.write_text("证据", encoding="utf-8")
        outside = self.root.parent / f"{self.root.name}-outside"
        outside.mkdir(exist_ok=True)
        try:
            (folder / "外部链接").symlink_to(outside, target_is_directory=True)
            targets = _finder_tag_targets([folder])
            self.assertIn(folder, targets)
            self.assertIn(nested, targets)
            self.assertIn(child, targets)
            self.assertNotIn(folder / "外部链接", targets)
            self.assertNotIn(outside, targets)
        finally:
            (folder / "外部链接").unlink(missing_ok=True)
            outside.rmdir()

    def test_hidden_items_are_optional(self):
        (self.root / ".secret.txt").write_text("secret", encoding="utf-8")
        hidden = _directory_items(self.root, self.root, show_hidden=False)
        shown = _directory_items(self.root, self.root, show_hidden=True)
        self.assertNotIn(".secret.txt", {item["name"] for item in hidden})
        self.assertIn(".secret.txt", {item["name"] for item in shown})

    def test_index_cache_invalidates_when_file_changes(self):
        path = self.root / "证据.txt"
        path.write_text("第一版证据内容。" * 80, encoding="utf-8")
        stored = _store_index(self.get_db, 1, "证据.txt", path, path.read_text(encoding="utf-8"))
        self.assertTrue(stored["id"])
        self.assertIsNotNone(_cached_index(self.get_db, 1, "证据.txt", path))
        path.write_text("第二版证据内容，已经发生变化。" * 80, encoding="utf-8")
        self.assertIsNone(_cached_index(self.get_db, 1, "证据.txt", path))

    def test_index_path_is_rewritten_after_local_rename(self):
        path = self.root / "原名称.txt"
        path.write_text("可供检索的案件事实。" * 80, encoding="utf-8")
        _store_index(self.get_db, 1, "原名称.txt", path, path.read_text(encoding="utf-8"))
        renamed = self.root / "新名称.txt"
        path.rename(renamed)
        _rewrite_index_paths(self.get_db, 1, "原名称.txt", "新名称.txt")
        self.assertIsNotNone(_cached_index(self.get_db, 1, "新名称.txt", renamed))
        with self.get_db() as connection:
            old = connection.execute(
                "SELECT 1 FROM case_manager_local_file_index WHERE relative_path='原名称.txt'"
            ).fetchone()
        self.assertIsNone(old)

    def test_chunks_overlap_and_relevant_chunks_rank_first(self):
        pieces = _chunks("甲" * 5000, limit=1000, overlap=100)
        self.assertGreater(len(pieces), 5)
        rows = [
            {"chunk_text": "一般背景", "display_name": "a", "chunk_index": 0},
            {"chunk_text": "建设工程价款优先受偿权与工程款", "display_name": "b", "chunk_index": 0},
        ]
        ranked = _score_chunks("建设工程价款优先受偿权", rows)
        self.assertEqual(ranked[0]["display_name"], "b")

    def test_page_and_worksheet_markers_become_citation_locators(self):
        located = _located_chunks("【第 2 页】\n本页证据内容\n\n【合同清单】\n表格数据")
        self.assertEqual(located[0][1], "第 2 页")
        self.assertEqual(located[-1][1], "工作表：合同清单")

    def test_unpaginated_chunks_do_not_claim_original_paragraph_numbers(self):
        located=_located_chunks('甲签约。\n乙付款。')
        self.assertEqual(len(located),1)
        self.assertIn('提取文本片段',located[0][1])
        self.assertIn('未取得原件页码或段落位置',located[0][1])

    def test_copy_destination_uses_finder_like_duplicate_names(self):
        source = self.root / "证据.pdf"
        source.write_text("one", encoding="utf-8")
        first = _copy_destination(source, self.root)
        self.assertEqual(first.name, "证据 副本.pdf")
        first.write_text("two", encoding="utf-8")
        self.assertEqual(_copy_destination(source, self.root).name, "证据 副本 2.pdf")

    def test_copy_destination_never_replaces_item_in_another_folder(self):
        source_dir = self.root / "来源"
        target_dir = self.root / "目标"
        source_dir.mkdir()
        target_dir.mkdir()
        source = source_dir / "证据.txt"
        source.write_text("source", encoding="utf-8")
        (target_dir / source.name).write_text("existing", encoding="utf-8")
        with self.assertRaises(HTTPException) as raised:
            _copy_destination(source, target_dir)
        self.assertEqual(raised.exception.status_code, 409)

    def test_ai_folder_selection_expands_supported_files_recursively(self):
        folder = self.root / "证据目录"
        nested = folder / "第二层"
        nested.mkdir(parents=True)
        (folder / "起诉状.pdf").write_bytes(b"%PDF-test")
        (nested / "清单.xlsx").write_bytes(b"sheet")
        (nested / "视频.mp4").write_bytes(b"video")
        (nested / ".隐藏.txt").write_text("hidden", encoding="utf-8")
        expanded = _expand_ai_paths(self.root, ["证据目录"])
        self.assertEqual(expanded, ["证据目录/起诉状.pdf", "证据目录/第二层/清单.xlsx"])

    def test_ai_folder_selection_deduplicates_explicit_child_file(self):
        folder = self.root / "材料"
        folder.mkdir()
        (folder / "说明.txt").write_text("text", encoding="utf-8")
        expanded = _expand_ai_paths(self.root, ["材料", "材料/说明.txt"])
        self.assertEqual(expanded, ["材料/说明.txt"])


if __name__ == "__main__":
    unittest.main()
