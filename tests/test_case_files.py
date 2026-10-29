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

    def test_complete_documents_are_not_limited_to_eighteen_short_spans(self):
        rows = [{'relative_path':str(i), 'display_name':f'材料{i}.txt',
                 'chunk_index':j, 'locator':f'段{j}',
                 'chunk_text':f'第{j}部分：' + '这是完整的原始材料内容。'*20}
                for i in range(2) for j in range(12)]
        selected, partial = _budgeted_file_chunks('总结两份材料', rows, 'deepseek-flash', '')
        self.assertFalse(partial)
        self.assertEqual(len(selected), 24)
        self.assertEqual(selected, rows)

    def test_generic_review_reaches_end_of_unstructured_documents(self):
        rows = [{'relative_path':str(i), 'display_name':f'材料{i}.txt',
                 'chunk_index':j, 'locator':f'段{j}',
                 'chunk_text':f'原始记录{j}：' + '设备运行正常，等待下一次检查。'*60 +
                              ('不得投入运行，最终检验未通过。' if j == 29 else '')}
                for i in range(2) for j in range(30)]
        selected, partial = _budgeted_file_chunks('总结这些材料', rows, 'fixture', '')
        self.assertTrue(partial)
        for i in range(2):
            text = ''.join(r['chunk_text'] for r in selected if r['relative_path'] == str(i))
            self.assertIn('最终检验未通过', text)

    def test_specific_question_preserves_late_numbers_and_negation(self):
        rows = [{'relative_path':'report', 'display_name':'运行报告.md',
                 'chunk_index':i, 'locator':f'段{i}',
                 'chunk_text': ('日常记录。'*150 if i != 23 else
                               '## Zeta接口\nZeta接口阈值为0.007，不得超过0.009；仅在离线模式适用。')}
                for i in range(30)]
        selected, partial = _budgeted_file_chunks('Zeta接口阈值及适用条件是什么', rows, 'fixture', '')
        self.assertTrue(partial)
        self.assertIn('Zeta接口阈值为0.007，不得超过0.009；仅在离线模式适用。',
                      ''.join(r['chunk_text'] for r in selected))
        self.assertTrue(all(r['chunk_text'] in rows[r['chunk_index']//100000]['chunk_text'] for r in selected))

    def test_generic_structures_and_table_rows_remain_verbatim(self):
        from backend.case_files import _file_coverage
        rows = [{'relative_path':'report', 'display_name':'采购报告.csv',
                 'chunk_index':i, 'locator':'工作表：成本',
                 'chunk_text': ('日常采购记录。'*200 if i != 20 else
                               '三、退款条件\n项目,金额,条件\n退款,783.25,未验收时不可退款\n')}
                for i in range(30)]
        selected, partial = _budgeted_file_chunks('退款金额和条件', rows, 'fixture', '')
        self.assertIn('退款,783.25,未验收时不可退款', ''.join(r['chunk_text'] for r in selected))
        self.assertIn('未提供部分不等于原文件缺失', _file_coverage(rows, selected, partial))
        self.assertTrue(all('字符' in r['locator'] for r in selected))

    def test_model_budget_and_skill_reduce_available_file_space(self):
        from backend import ai_context
        rows = [{'relative_path':'a', 'display_name':'a.txt', 'chunk_index':i,
                 'locator':str(i), 'chunk_text':'记录：abcdef0123456789。'*50} for i in range(40)]
        large, _ = _budgeted_file_chunks('分析材料', rows, 'deepseek-flash', '')
        token = ai_context.CURRENT.set({'budget':24000})
        try:
            small, _ = _budgeted_file_chunks('分析材料', rows, 'deepseek-flash', '规则'*500)
        finally:
            ai_context.CURRENT.reset(token)
        self.assertLess(sum(len(r['chunk_text']) for r in small), sum(len(r['chunk_text']) for r in large))

    def test_file_research_splits_fullwidth_issue_headings(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend import case_files, user_memory
        with self.get_db() as conn:
            user_memory.add_schema(conn)
        queries = []
        fail_first = [False]
        async def search(question, model):
            queries.append(question)
            if fail_first[0] and len(queries) == 1:
                raise RuntimeError('fixture unavailable')
            return {'answer': '已检索。'}
        async def web(question, **kwargs):
            return '', [], ''
        app = FastAPI()
        case_files.register_case_file_routes(app, self.get_db, self.root,
            parse_file=lambda path, consent: {'content': path.read_text()},
            call_ai=lambda model, messages: ('结果。', '', model), authoritative_answer=search)
        content = ('商品房预售合同纠纷\n第一类　交付后解除合同\n匿名案例。\n'
                   '第二类　解除权期间届满\n匿名案例。\n第三类　合同目的已经实现\n匿名案例。')
        with patch.object(case_files, '_AI_ATTACHMENT_ROOT', self.root/'sessions'), \
             patch.object(case_files, '_general_web_context', web):
            client = TestClient(app)
            prepared = client.post('/api/ai-ask/local-files/prepare', files=[('files', ('a.txt', content.encode(), 'text/plain'))])
            result = client.post('/api/ai-ask/local-files/ask', data={'question': '全网检索报告中三类案例',
                'model': 'deepseek-flash', 'session_id': prepared.json()['session_id']})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(queries), 3)
        self.assertTrue(all('商品房预售合同纠纷' in q for q in queries))
        self.assertTrue(all('报告' not in q for q in queries))
        self.assertIn('解除权期间届满', queries[1])
        queries.clear()
        fail_first[0] = True
        with patch.object(case_files, '_AI_ATTACHMENT_ROOT', self.root/'sessions'), \
             patch.object(case_files, '_general_web_context', web):
            result = client.post('/api/ai-ask/local-files/ask', data={'question': '全网检索报告中三类案例',
                'model': 'deepseek-flash', 'session_id': prepared.json()['session_id']})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(queries), 3)
        self.assertTrue(any('第 1 类权威法律来源检索未完成' in w for w in result.json()['warnings']))
        queries.clear()
        fail_first[0] = False
        with patch.object(case_files, '_AI_ATTACHMENT_ROOT', self.root/'sessions'), \
             patch.object(case_files, '_general_web_context', web):
            result = client.post('/api/ai-ask/local-files/ask', data={'question': '检索业主维修责任案例',
                'model': 'deepseek-flash', 'session_id': prepared.json()['session_id']})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(queries), 1)
        self.assertIn('业主维修责任', queries[0])

    def test_both_question_routes_deliver_complete_generic_materials(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend import case_files, user_memory
        import json
        with self.get_db() as conn:
            user_memory.add_schema(conn)
        captured = []
        def call(model, messages):
            captured.append(messages)
            return '材料说明见 [FILE:1] 和 [FILE:2]。', '', 'fixture'
        app = FastAPI()
        supplemental = {'answer':'额外资料。'*20000,
                        'external_sources':[{'id':'external-large', 'title':'未采用的额外资料'}]}
        case_files.register_case_file_routes(app, self.get_db, self.root,
            parse_file=lambda path, consent: {'content':path.read_text()}, call_ai=call,
            authoritative_answer=lambda question, model:supplemental)
        root = self.root.resolve()
        source = '项目说明。\n' + '采购金额为123.45元，不得提前退款。\n'*90 + '\n最终复核：仅在验收失败后退款。'
        with patch.object(case_files, '_AI_ATTACHMENT_ROOT', root/'sessions'), \
             patch.object(case_files, '_bound_root', return_value=root):
            client = TestClient(app)
            prepared = client.post('/api/ai-ask/local-files/prepare', files=[
                ('files', (name, source.encode(), 'text/plain')) for name in ('a.txt', 'b.txt')])
            self.assertEqual(prepared.status_code, 200, prepared.text)
            answer = client.post('/api/ai-ask/local-files/ask', data={
                'question':'总结两份材料', 'model':'deepseek-flash', 'session_id':prepared.json()['session_id']})
            self.assertEqual(answer.status_code, 200, answer.text)
            self.assertEqual(captured[-1][1]['content'].count('最终复核：仅在验收失败后退款。'), 2)
            self.assertIn('已提供全部提取文本', captured[-1][1]['content'])
            self.assertEqual(answer.json()['warnings'], [])
            for name in ('a.txt', 'b.txt'):
                (root/name).write_text(source)
            answer = client.post('/api/case-manager/cases/1/local-files/ask', data={
                'question':'总结两份材料', 'model':'deepseek-flash', 'paths':json.dumps(['a.txt', 'b.txt'])})
            self.assertEqual(answer.status_code, 200, answer.text)
            self.assertEqual(captured[-1][1]['content'].count('最终复核：仅在验收失败后退款。'), 2)
            self.assertEqual(answer.json()['warnings'], [])
            self.assertIn('片段引用编号', captured[-1][0]['content'])
            from unittest.mock import AsyncMock
            from backend.case_files import _file_input_remaining
            with patch.object(case_files, '_general_web_context', AsyncMock(return_value=(
                    '超预算网页。'*30000, [{'id':'web-large','title':'未采用网页'}], ''))):
                answer = client.post('/api/case-manager/cases/1/local-files/ask', data={
                    'question':'总结两份材料', 'model':'deepseek-flash',
                    'paths':json.dumps(['a.txt','b.txt']), 'include_authoritative':'true', 'include_public_web':'true'})
            self.assertEqual(answer.status_code, 200, answer.text)
            self.assertGreaterEqual(_file_input_remaining(captured[-1], 'deepseek-flash'), 0)
            self.assertEqual(len(answer.json()['external_sources']), 2)
            self.assertIn('额外资料', captured[-1][1]['content'])
            self.assertTrue(answer.json()['file_reading']['complete'])
            self.assertEqual(captured[-1][1]['content'].count('最终复核：仅在验收失败后退款。'), 2)
            supplemental['answer'] = '可用的补充资料。'
            supplemental['external_sources'] = [{'id':'external-small','title':'补充依据'}]
            with patch.object(case_files, '_general_web_context', AsyncMock(return_value=(
                    '可用网页资料 [WEB:1]', [{'id':'web-small','title':'网页依据'}], ''))):
                answer = client.post('/api/case-manager/cases/1/local-files/ask', data={
                    'question':'总结两份材料', 'model':'deepseek-flash',
                    'paths':json.dumps(['a.txt','b.txt']), 'include_authoritative':'true', 'include_public_web':'true'})
            self.assertEqual(answer.status_code, 200, answer.text)
            self.assertIn('可用的补充资料', captured[-1][1]['content'])
            self.assertIn('可用网页资料', captured[-1][1]['content'])
            self.assertEqual(len(answer.json()['external_sources']), 2)

    def test_match_keeps_qualification_across_old_span_boundary(self):
        text = 'x'*970 + 'Zeta threshold is 0.007; ' + 'Qualification: not applicable in online mode.\n' + 'ordinary observations. '*3000
        rows = [{'relative_path':'a', 'display_name':'data.txt', 'chunk_index':0,
                 'locator':'原文', 'chunk_text':text}]
        selected, partial = _budgeted_file_chunks('Zeta threshold', rows, 'fixture', '')
        self.assertTrue(partial)
        matching = [r for r in selected if 'Zeta threshold' in r['chunk_text']]
        self.assertTrue(matching)
        self.assertTrue(all('Qualification: not applicable in online mode.' in r['chunk_text'] for r in matching))
        import re
        for row in selected:
            start, end = map(int, re.search(r'字符 (\d+)–(\d+)', row['locator']).groups())
            self.assertEqual(row['chunk_text'], text[start-1:end])

    def test_inherited_heading_remains_visible_in_retrieved_evidence(self):
        rows = [{'relative_path':'a', 'display_name':'report.txt', 'chunk_index':0,
                 'locator':'原文', 'chunk_text':'## Zeta Dataset\n'+'ordinary records. '*400},
                {'relative_path':'a', 'display_name':'report.txt', 'chunk_index':1,
                 'locator':'原文', 'chunk_text':'filler '*30000+'Voltage limit is 783.25; offline only.'}]
        selected, partial = _budgeted_file_chunks('Voltage limit', rows, 'fixture', '')
        matching = [r for r in selected if 'Voltage limit is 783.25' in r['chunk_text']]
        self.assertTrue(partial)
        self.assertTrue(matching)
        self.assertTrue(all('章节：## Zeta Dataset' in r['locator'] for r in matching))

    def test_uncited_and_invalid_citations_are_not_invented(self):
        from backend.case_files import _referenced_file_indexes, _file_question_messages
        rows = [{'relative_path':path, 'display_name':'same.txt', 'chunk_index':i,
                 'locator':'原文', 'chunk_text':'原始资料。'} for path, i in [('a',0),('a',1),('b',0)]]
        self.assertEqual(_referenced_file_indexes('无引用标记', rows), set())
        self.assertEqual(_referenced_file_indexes('[FILE:999]', rows), set())
        self.assertEqual(_referenced_file_indexes('[FILE:2]', rows), {2})
        prompt = _file_question_messages('比较文件', rows, rows, False, '')[1]['content']
        self.assertIn('来源：a', prompt)
        self.assertIn('来源：b', prompt)

    def test_rendered_prompts_fit_request_and_skill_budgets(self):
        from backend import ai_context, case_files
        for budget in (12000,24000,64000):
            for filename_size in (5,160):
                rows = [{'relative_path':f'folder{i}/'+('字'*filename_size)+'.txt',
                         'display_name':('字'*filename_size)+'.txt', 'chunk_index':0,
                         'locator':'原始位置', 'chunk_text':'测量数值为0.007，不得超过上限。'*700}
                        for i in range(2)]
                skill = '审阅要求。'*100
                token = ai_context.CURRENT.set({'budget':budget})
                try:
                    with self.subTest(budget=budget, filename_size=filename_size):
                        try:
                            selected, partial = _budgeted_file_chunks('分析资料', rows, 'deepseek-flash', skill)
                        except HTTPException as exc:
                            self.assertEqual(exc.status_code, 413)
                            continue
                        messages = case_files._file_question_messages('分析资料', rows, selected, partial, skill)
                        self.assertGreaterEqual(case_files._file_input_remaining(messages, 'deepseek-flash'), 0)
                finally:
                    ai_context.CURRENT.reset(token)

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
        located = _located_chunks("【第 2 页】\n本页证据内容\n\n【工作表：合同清单】\n表格数据")
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


class FileEvidenceAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_retains_request_budget_and_leaves_loop_available(self):
        import asyncio
        import threading
        from backend import ai_context, case_files
        main_thread = threading.get_ident()
        rows = [{'relative_path':'a','display_name':'a.txt','chunk_index':0,'locator':'原文',
                 'chunk_text':'original material. '*3000}]
        state = {'budget':24000}
        token = ai_context.CURRENT.set(state)
        original = case_files._budgeted_file_chunks
        def select(*args):
            self.assertNotEqual(threading.get_ident(), main_thread)
            self.assertIs(ai_context.CURRENT.get(), state)
            return original(*args)
        try:
            with patch.object(case_files, '_budgeted_file_chunks', side_effect=select):
                selected, partial = await asyncio.wait_for(case_files._select_file_evidence(
                    '总结材料', rows, 'deepseek-flash', ''), timeout=5)
            self.assertTrue(partial)
            self.assertLess(sum(len(r['chunk_text']) for r in selected),len(rows[0]['chunk_text']))
        finally:
            ai_context.CURRENT.reset(token)

    async def test_cancellation_signals_the_selection_worker(self):
        import asyncio
        import threading
        from backend import case_files
        started, stopped = threading.Event(), threading.Event()
        def select(question, rows, model, skill, cancelled):
            started.set()
            while not cancelled():
                if stopped.wait(.005):
                    return [], True
            stopped.set()
            raise asyncio.CancelledError()
        with patch.object(case_files, '_budgeted_file_chunks', side_effect=select):
            task = asyncio.create_task(case_files._select_file_evidence('总结材料', [], 'fixture', ''))
            try:
                self.assertTrue(await asyncio.get_running_loop().run_in_executor(None, started.wait, 2))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertTrue(await asyncio.get_running_loop().run_in_executor(None, stopped.wait, 2))
            finally:
                stopped.set()
                if not task.done():
                    task.cancel()

    async def test_sync_parser_runs_off_loop_and_async_parser_remains_supported(self):
        import threading
        from backend.case_files import _parse_ai_file
        from backend import ai_context
        main_thread = threading.get_ident()
        state = {'budget':12000}
        def sync_parser(path, consent):
            self.assertNotEqual(threading.get_ident(), main_thread)
            self.assertIs(ai_context.CURRENT.get(), state)
            return {'content':'原文'}
        async def async_parser(path, consent):
            self.assertEqual(threading.get_ident(), main_thread)
            return {'content':'原文'}
        token = ai_context.CURRENT.set(state)
        try:
            self.assertEqual(await _parse_ai_file(sync_parser, Path('fixture'), False), {'content':'原文'})
            self.assertEqual(await _parse_ai_file(async_parser, Path('fixture'), False), {'content':'原文'})
        finally:
            ai_context.CURRENT.reset(token)


if __name__ == "__main__":
    unittest.main()
