import ast
from pathlib import Path
import sqlite3
import tempfile
import unittest

from backend.hearing_case_numbers import sync_hearing_case_numbers, number_type
from tests.test_series_manager import BASE_SCHEMA
from scripts.sync_hearing_case_numbers import repair


class HearingCaseNumbersTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'fixture.db'
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(BASE_SCHEMA)
        for title in ('匿名案件', '另一案件'):
            self.db.execute("INSERT INTO case_manager_cases(title,created_at,updated_at) VALUES (?,'2026-01-01','2026-01-01')", (title,))
        self.db.commit()
        self.hearing = {'id': 1, 'case_id': 1, 'case_no': '（2026）测试01民终123号', 'court': '匿名中级法院', 'reminder_type': '庭询谈话'}

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def numbers(self, case_id=1):
        return [dict(row) for row in self.db.execute('SELECT * FROM case_manager_case_numbers WHERE case_id=? ORDER BY sort_order,id', (case_id,))]

    def test_adds_second_instance_with_court_without_changing_first_instance(self):
        self.db.execute("""INSERT INTO case_manager_case_numbers(case_id,number_type,case_no,court,first_filing_at,created_at,updated_at)
                           VALUES (1,'一审','（2025）测试01民初1号','匿名基层法院','2025-01-02','old','old')""")
        original = self.numbers()[0]
        self.assertEqual(len(sync_hearing_case_numbers(self.db, self.hearing)), 1)
        self.assertEqual(self.numbers()[0], original)
        self.assertEqual(self.numbers()[1]['number_type'], '二审')
        self.assertEqual(self.numbers()[1]['court'], '匿名中级法院')
        self.assertEqual(self.numbers(2), [])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM case_manager_audit_logs').fetchone()[0], 1)

    def test_repeat_normalizes_spacing_and_brackets_without_duplicates_or_timestamp_changes(self):
        sync_hearing_case_numbers(self.db, self.hearing)
        before = self.numbers()
        self.hearing['case_no'] = '(2026) 测试01民终 123 号'
        self.assertEqual(sync_hearing_case_numbers(self.db, self.hearing), [])
        self.assertEqual(self.numbers(), before)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM case_manager_audit_logs').fetchone()[0], 1)

    def test_fills_empty_fields_but_keeps_manual_dates_and_conflicting_court(self):
        self.db.execute("""INSERT INTO case_manager_case_numbers(case_id,case_no,handler_contact,second_filing_at,created_at,updated_at)
                           VALUES (1,'(2026)测试01民终123号','人工联系人','2026-10-01','old','old')""")
        sync_hearing_case_numbers(self.db, self.hearing)
        saved = self.numbers()[0]
        self.assertEqual(saved['handler_contact'], '人工联系人')
        self.assertEqual(saved['second_filing_at'], '2026-10-01')
        self.assertEqual(saved['number_type'], '二审')
        self.hearing['court'] = '另一法院'
        self.assertEqual(sync_hearing_case_numbers(self.db, self.hearing), [])
        self.assertEqual(self.numbers()[0]['court'], '匿名中级法院')

    def test_multiple_numbers_pair_courts_and_do_not_infer_filing_dates_from_hearing(self):
        self.hearing.update(case_no='（2026）测试民初1号\n（2026）测试仲字2号', court='匿名法院\n匿名仲裁委', hearing_at='2026-11-03 15:00')
        sync_hearing_case_numbers(self.db, self.hearing)
        rows = self.numbers()
        self.assertEqual([(row['number_type'], row['court']) for row in rows], [('一审','匿名法院'), ('仲裁','匿名仲裁委')])
        self.assertFalse(any(row['first_filing_at'] or row['second_filing_at'] for row in rows))

    def test_missing_number_missing_case_and_deleted_case_do_nothing(self):
        for hearing in ({**self.hearing, 'case_no':''}, {**self.hearing, 'case_no':'待定'}, {**self.hearing, 'case_id':999}):
            self.assertEqual(sync_hearing_case_numbers(self.db, hearing), [])
        self.db.execute("UPDATE case_manager_cases SET source_status='deleted' WHERE id=1")
        self.assertEqual(sync_hearing_case_numbers(self.db, self.hearing), [])
        self.assertEqual(self.numbers(), [])

    def test_concatenated_legacy_numbers_and_annotations_are_not_copied_as_one_number(self):
        self.hearing['case_no'] = '（2026）测试民初1号（2026）测试民终2号【案件备注】'
        sync_hearing_case_numbers(self.db, self.hearing)
        self.assertEqual([row['case_no'] for row in self.numbers()], ['（2026）测试民初1号', '（2026）测试民终2号'])
        self.assertEqual(sync_hearing_case_numbers(self.db, self.hearing), [])

    def test_existing_combined_manual_record_is_preserved_without_duplicate_numbers(self):
        self.db.execute("""INSERT INTO case_manager_case_numbers(case_id,number_type,case_no,court,created_at,updated_at)
                           VALUES (1,'人工性质','（2026）测试民初1号（2026）测试民终2号','人工法院','old','old')""")
        self.hearing['case_no'] = '（2026）测试民初1号\n（2026）测试民终2号'
        self.assertEqual(sync_hearing_case_numbers(self.db, self.hearing), [])
        self.assertEqual(len(self.numbers()), 1)

    def test_rollback_reverts_numbers_case_timestamp_and_audit_together(self):
        sync_hearing_case_numbers(self.db, self.hearing)
        self.db.rollback()
        self.assertEqual(self.numbers(), [])
        self.assertEqual(self.db.execute('SELECT updated_at FROM case_manager_cases WHERE id=1').fetchone()[0], '2026-01-01')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM case_manager_audit_logs').fetchone()[0], 0)

    def test_existing_record_repair_is_previewed_backed_up_and_idempotent(self):
        self.db.execute("""INSERT INTO case_manager_hearings(case_id,title,case_no,court,created_at,updated_at)
                           VALUES (1,'匿名案件',?,'匿名中级法院','old','old')""", (self.hearing['case_no'],))
        self.db.commit()
        self.assertEqual(repair(self.path)['changed_cases'], 1)
        self.assertEqual(self.numbers(), [])
        result = repair(self.path, apply=True)
        self.assertTrue(Path(result['backup']).is_file())
        with sqlite3.connect(result['backup']) as backup:
            self.assertEqual(backup.execute('SELECT COUNT(*) FROM case_manager_case_numbers').fetchone()[0], 0)
        self.assertEqual(len(self.numbers()), 1)
        self.assertEqual(repair(self.path)['changed_hearings'], 0)

    def test_saved_hearing_shared_ledger_pipeline_also_populates_case_details(self):
        # Exercise the actual shared callback used by manual/imported/SMS hearings,
        # isolated from route startup and all real runtime data.
        from backend import case_manager
        tree = ast.parse(Path(case_manager.__file__).read_text())
        register = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'register_case_manager_routes')
        function = next(node for node in register.body if isinstance(node, ast.FunctionDef) and node.name == 'sync_hearing_to_case_ledger')
        env = {**vars(case_manager), 'sync_hearing_case_numbers': sync_hearing_case_numbers,
               'row_dict': lambda row: dict(row) if row else {}, 'norm': lambda value: str(value or '').strip(),
               'now_iso': lambda: '2026-10-20T12:00:00', 'ensure_case_research_project': lambda conn, case_id: case_id}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<hearing-sync>', 'exec'), env)
        self.db.executescript("""CREATE TABLE research_projects(id INTEGER PRIMARY KEY,updated_at TEXT);
            INSERT INTO research_projects VALUES(1,'old');
            CREATE TABLE research_case_ledgers(id INTEGER PRIMARY KEY,project_id,title,content,happened_at,source_type,source_id,created_at,updated_at);""")
        self.db.execute("""INSERT INTO case_manager_hearings(id,case_id,title,case_no,court,created_at,updated_at)
                           VALUES (1,1,'匿名案件',?,'匿名中级法院','old','old')""", (self.hearing['case_no'],))
        env['sync_hearing_to_case_ledger'](self.db, 1)
        env['sync_hearing_to_case_ledger'](self.db, 1)
        self.assertEqual(self.numbers()[0]['number_type'], '二审')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM research_case_ledgers').fetchone()[0], 1)

    def test_type_follows_number_before_general_hearing_label(self):
        self.assertEqual(number_type('（2026）测试民终1号', '一审开庭'), '二审')
        self.assertEqual(number_type('（2026）测试执异1号'), '执行异议')
        self.assertEqual(number_type('编号1', '庭询谈话'), '')


if __name__ == '__main__':
    unittest.main()
