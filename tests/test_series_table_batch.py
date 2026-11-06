"""Atomic table editing checks use only anonymous temporary databases."""
import unittest
from tests import test_series_manager as fixtures


class SeriesTableBatchTests(unittest.TestCase):
    setUp = fixtures.SeriesManagerTests.setUp
    tearDown = fixtures.SeriesManagerTests.tearDown
    create_series = fixtures.SeriesManagerTests.create_series

    def test_transaction_rolls_back_earlier_cells_on_late_validation_failure(self):
        series = self.create_series()
        first, second = series['children'][:2]
        response = self.client.post(f"/api/case-manager/series/{series['id']}/cells/batch", json={'updates': [
            {'childId': first['id'], 'field': 'memo', 'value': 'must roll back'},
            {'childId': second['id'], 'field': 'display_name', 'value': ''},
        ]})
        self.assertEqual(response.status_code, 400, response.text)
        actual = self.client.get(f"/api/case-manager/series/{series['id']}").json()
        self.assertEqual(actual['children'][0].get('memo', ''), first.get('memo', ''))

    def test_value_and_format_are_saved_together_without_touching_identity(self):
        series = self.create_series()
        child = series['children'][0]
        response = self.client.post(f"/api/case-manager/series/{series['id']}/cells/batch", json={'updates': [
            {'childId': child['id'], 'field': 'memo', 'value': '00123\n匿名说明', 'format': {'runs': [{'start': 0, 'end': 5, 'bold': True}]}},
        ]})
        self.assertEqual(response.status_code, 200, response.text)
        actual = self.client.get(f"/api/case-manager/series/{series['id']}").json()['children'][0]
        self.assertEqual(actual['id'], child['id'])
        self.assertEqual(actual['memo'], '00123\n匿名说明')
        self.assertTrue(actual['cell_formats']['memo']['runs'][0]['bold'])

    def test_foreign_child_rejects_entire_batch(self):
        series = self.create_series()
        response = self.client.post(f"/api/case-manager/series/{series['id']}/cells/batch", json={'updates': [
            {'childId': 1, 'field': 'memo', 'value': 'wrong case'},
        ]})
        self.assertEqual(response.status_code, 404, response.text)

    def test_insert_copied_rows_has_fresh_id_and_atomic_undo_compatible_ids(self):
        series = self.create_series()
        first, second = series['children'][:2]
        response = self.client.post(f"/api/case-manager/series/{series['id']}/table/insert-copy", json={
            'axis': 'row', 'side': 'before', 'source_ids': [first['id']], 'target_id': second['id'],
        })
        self.assertEqual(response.status_code, 200, response.text)
        created = response.json()['ids'][0]
        self.assertNotIn(created, [first['id'], second['id']])
        actual = self.client.get(f"/api/case-manager/series/{series['id']}").json()['children']
        self.assertEqual([c['id'] for c in actual], [first['id'], created, second['id']])
        self.assertNotEqual(actual[1]['series_code'], first['series_code'])

    def test_insert_copied_column_gets_independent_key(self):
        series = self.create_series()
        response = self.client.post(f"/api/case-manager/series/{series['id']}/table/insert-copy", json={
            'axis': 'column', 'side': 'after', 'source_keys': ['display_name'], 'target_key': 'display_name',
        })
        self.assertEqual(response.status_code, 200, response.text)
        key = response.json()['keys'][0]
        actual = self.client.get(f"/api/case-manager/series/{series['id']}").json()
        self.assertEqual(actual['children'][0]['custom_values'][key], series['children'][0]['display_name'])

    def test_row_copy_uses_captured_values_after_source_changes(self):
        series = self.create_series()
        child, target = series['children'][:2]
        snapshot = {'rows': [{'id': child['id'], 'values': {'display_name': child['display_name'], 'memo': '复制时的内容'}, 'formats': {'memo': {'runs': [{'start': 0, 'end': 2, 'bold': True}]}}}]}
        changed = self.client.patch(f"/api/case-manager/series/{series['id']}/children/{child['id']}/cell", json={'field': 'display_name', 'value': '复制后改过的名字'})
        self.assertEqual(changed.status_code, 200, changed.text)
        result = self.client.post(f"/api/case-manager/series/{series['id']}/table/insert-copy", json={'axis': 'row', 'side': 'before', 'source_ids': [child['id']], 'target_id': target['id'], 'snapshot': snapshot})
        self.assertEqual(result.status_code, 200, result.text)
        data = self.client.get(f"/api/case-manager/series/{series['id']}").json()
        copy = next(item for item in data['children'] if item['id'] == result.json()['ids'][0])
        self.assertEqual(copy['display_name'], child['display_name'])
        self.assertEqual(copy['memo'], '复制时的内容')
        self.assertTrue(copy['cell_formats']['memo']['runs'][0]['bold'])

    def test_single_cell_opt_in_retains_utf16_format_ranges(self):
        series = self.create_series()
        child = series['children'][0]
        url = f"/api/case-manager/series/{series['id']}/children/{child['id']}/cell"
        self.client.post(f"/api/case-manager/series/{series['id']}/cells/batch", json={'updates': [{'childId': child['id'], 'field': 'memo', 'value': '😀甲乙', 'format': {'runs': [{'start': 2, 'end': 4, 'bold': True}]}}]})
        response = self.client.patch(url, json={'field': 'memo', 'value': '😀新甲乙', 'preserve_format': True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['cell_formats']['memo']['runs'], [{'start': 3, 'end': 5, 'bold': True}])

    def test_paste_expansion_undo_redo_is_one_transaction_and_keeps_ids(self):
        series = self.create_series()
        ids = [child['id'] for child in series['children']]
        columns = len(series['profile']['table_columns'])
        url = f"/api/case-manager/series/{series['id']}/table"
        result = self.client.post(url + '/paste', json={'row_ids': ids, 'keys': ['memo'], 'row': 1, 'column': 0, 'matrix': [['原位置值', '新增列值'], ['新行甲', '甲列值'], ['新行乙', '乙列值']]})
        self.assertEqual(result.status_code, 200, result.text)
        token, created = result.json()['undo_token'], result.json()['created_ids']
        self.assertEqual(len(created), 2)
        after = self.client.get(f"/api/case-manager/series/{series['id']}").json()
        self.assertEqual(len(after['profile']['table_columns']), columns + 1)
        self.assertEqual([row['id'] for row in after['children'] if row['source_status'] != 'deleted'], ids + created)
        undo = self.client.post(url + '/paste-replay', json={'token': token, 'direction': 'undo'})
        self.assertEqual(undo.status_code, 200, undo.text)
        before = self.client.get(f"/api/case-manager/series/{series['id']}").json()
        self.assertEqual(len(before['profile']['table_columns']), columns)
        self.assertEqual([row['id'] for row in before['children'] if row['source_status'] != 'deleted'], ids)
        self.assertEqual(before['children'][1].get('memo', ''), series['children'][1].get('memo', ''))
        redo = self.client.post(url + '/paste-replay', json={'token': token, 'direction': 'redo'})
        self.assertEqual(redo.status_code, 200, redo.text)
        redone = self.client.get(f"/api/case-manager/series/{series['id']}").json()
        self.assertEqual([row['id'] for row in redone['children'] if row['source_status'] != 'deleted'], ids + created)
        self.assertEqual(redone['children'][1]['memo'], '原位置值')
        self.assertEqual(len(redone['profile']['table_columns']), columns + 1)

    def test_paste_failure_rolls_back_new_rows_columns_and_earlier_writes(self):
        series = self.create_series()
        ids = [child['id'] for child in series['children']]
        before = self.client.get(f"/api/case-manager/series/{series['id']}").json()
        result = self.client.post(f"/api/case-manager/series/{series['id']}/table/paste", json={'row_ids': ids, 'keys': ['memo', 'display_name'], 'row': 0, 'column': 0, 'matrix': [['不应保存', '', '新列'], ['第二行', '名称二', '新列'], ['第三行', '名称三', '新列']]})
        self.assertEqual(result.status_code, 400, result.text)
        after = self.client.get(f"/api/case-manager/series/{series['id']}").json()
        self.assertEqual(after['profile']['table_columns'], before['profile']['table_columns'])
        self.assertEqual(after['children'], before['children'])

    def test_paste_undo_preserves_case_number_ids_and_filing_metadata(self):
        series = self.create_series()
        child = series['children'][0]
        base = f"/api/case-manager/series/{series['id']}"
        self.client.patch(f"{base}/children/{child['id']}/cell", json={'field': 'case_no', 'value': '示例案号甲\n示例案号乙'})
        with self.get_db() as conn:
            conn.execute("UPDATE case_manager_case_numbers SET first_filing_at='2026-01-02' WHERE case_id=?", (child['id'],))
            conn.commit()
            expected = [tuple(row) for row in conn.execute('SELECT * FROM case_manager_case_numbers WHERE case_id=? ORDER BY id', (child['id'],))]
        pasted = self.client.post(base + '/table/paste', json={'row_ids': [child['id']], 'keys': ['case_no'], 'row': 0, 'column': 0, 'matrix': [['修改后的案号']]})
        self.assertEqual(pasted.status_code, 200, pasted.text)
        restored = self.client.post(base + '/table/paste-replay', json={'token': pasted.json()['undo_token'], 'direction': 'undo'})
        self.assertEqual(restored.status_code, 200, restored.text)
        with self.get_db() as conn:
            actual = [tuple(row) for row in conn.execute('SELECT * FROM case_manager_case_numbers WHERE case_id=? ORDER BY id', (child['id'],))]
        self.assertEqual(actual, expected)

    def test_paste_undo_refuses_overwriting_a_later_edit(self):
        series = self.create_series()
        child = series['children'][0]
        base = f"/api/case-manager/series/{series['id']}"
        pasted = self.client.post(base + '/table/paste', json={'row_ids': [child['id']], 'keys': ['memo'], 'row': 0, 'column': 0, 'matrix': [['粘贴内容']]})
        self.assertEqual(pasted.status_code, 200, pasted.text)
        changed = self.client.patch(f"{base}/children/{child['id']}/cell", json={'field': 'memo', 'value': '后续编辑'})
        self.assertEqual(changed.status_code, 200, changed.text)
        response = self.client.post(base + '/table/paste-replay', json={'token': pasted.json()['undo_token'], 'direction': 'undo'})
        self.assertEqual(response.status_code, 409, response.text)
        actual = self.client.get(base).json()['children'][0]
        self.assertEqual(actual['memo'], '后续编辑')

    def test_stale_batch_expected_value_rolls_back_every_cell(self):
        series = self.create_series()
        first, second = series['children'][:2]
        result = self.client.post(f"/api/case-manager/series/{series['id']}/cells/batch", json={'updates': [{'childId': first['id'], 'field': 'memo', 'value': '不应写入'}, {'childId': second['id'], 'field': 'memo', 'value': '冲突值', 'expectedValue': '过期旧值'}]})
        self.assertEqual(result.status_code, 409, result.text)
        actual = self.client.get(f"/api/case-manager/series/{series['id']}").json()
        self.assertEqual(actual['children'][0].get('memo', ''), first.get('memo', ''))

    def test_view_metadata_survives_legacy_settings_updates_without_changing_values(self):
        series = self.create_series()
        base = f"/api/case-manager/series/{series['id']}"
        child = series['children'][0]
        settings = {'row_heights': {str(child['id']): 120}, 'conditional_rules': [{'key': 'memo', 'kind': 'empty', 'color': 'yellow'}], 'views': {'示例视图': {'columns': [{'key': 'memo', 'width': 200}], 'sorts': [{'key': 'memo', 'direction': 'desc'}], 'filters': {'memo': {'condition': {'kind': 'nonempty'}}}}}}
        response = self.client.put(base + '/columns', json={'columns': series['profile']['table_columns'], 'settings': settings})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.put(base + '/columns', json={'columns': series['profile']['table_columns'], 'settings': {'freeze_rows': 1}})
        self.assertEqual(response.status_code, 200, response.text)
        actual = self.client.get(base).json()
        self.assertEqual(actual['children'], series['children'])
        saved = actual['profile']['table_settings']
        self.assertEqual(saved['row_heights'][str(child['id'])], 120)
        self.assertEqual(saved['freeze_rows'], 1)
        self.assertEqual(saved['views']['示例视图']['filters']['memo']['condition']['kind'], 'nonempty')

    def test_optional_validation_checks_new_writes_and_rolls_back_whole_batch(self):
        series = self.create_series()
        base = f"/api/case-manager/series/{series['id']}"
        child = series['children'][0]
        columns = series['profile']['table_columns'] + [{'key': 'custom_exact', 'label': '金额示例', 'source': 'custom', 'field_type': 'text', 'validation': {'type': 'amount'}}]
        response = self.client.put(base + '/columns', json={'columns': columns})
        self.assertEqual(response.status_code, 200, response.text)
        value = '9007199254740993.01'
        response = self.client.post(base + '/cells/batch', json={'updates': [{'childId': child['id'], 'field': 'custom_exact', 'value': value}]})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post(base + '/cells/batch', json={'updates': [{'childId': child['id'], 'field': 'memo', 'value': '不能留存'}, {'childId': child['id'], 'field': 'custom_exact', 'value': '1e20'}]})
        self.assertEqual(response.status_code, 400, response.text)
        actual = self.client.get(base).json()['children'][0]
        self.assertEqual(actual['custom_values']['custom_exact'], value)
        self.assertEqual(actual.get('memo', ''), child.get('memo', ''))
        columns[-1]['validation'] = {'type': 'date'}
        response = self.client.put(base + '/columns', json={'columns': columns})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get(base).json()['children'][0]['custom_values']['custom_exact'], value)
        for candidate, status in [('2024-02-29', 200), ('2025-02-29', 400), ('2026-1-2', 400)]:
            response = self.client.patch(f"{base}/children/{child['id']}/cell", json={'field': 'custom_exact', 'value': candidate})
            self.assertEqual(response.status_code, status, response.text)

    def test_copy_insert_complete_undo_redo_preserves_column_values_and_keys(self):
        series = self.create_series()
        child = series['children'][0]
        base = f"/api/case-manager/series/{series['id']}"
        copied = self.client.post(base + '/table/insert-copy', json={'axis': 'column', 'side': 'after', 'source_keys': ['display_name'], 'target_key': 'display_name', 'record_history': True})
        self.assertEqual(copied.status_code, 200, copied.text)
        key, token = copied.json()['keys'][0], copied.json()['undo_token']
        self.assertTrue(token)
        self.assertEqual(self.client.post(base + '/table/paste-replay', json={'token': token, 'direction': 'undo'}).status_code, 200)
        before = self.client.get(base).json()
        self.assertNotIn(key, [column['key'] for column in before['profile']['table_columns']])
        self.assertNotIn(key, before['children'][0].get('custom_values', {}))
        self.assertEqual(self.client.post(base + '/table/paste-replay', json={'token': token, 'direction': 'redo'}).status_code, 200)
        after = self.client.get(base).json()
        self.assertEqual(after['children'][0]['custom_values'][key], child['display_name'])

    def test_deleted_column_restores_values_formats_including_trashed_children(self):
        series = self.create_series()
        base = f"/api/case-manager/series/{series['id']}"
        ids = [child['id'] for child in series['children']]
        columns = series['profile']['table_columns'] + [{'key': 'custom_delete', 'label': '示例', 'source': 'custom', 'field_type': 'text'}]
        self.client.put(base + '/columns', json={'columns': columns})
        self.client.post(base + '/cells/batch', json={'updates': [{'childId': child_id, 'field': 'custom_delete', 'value': '001', 'format': {'align': 'right'}} for child_id in ids]})
        self.client.delete(f"{base}/children/{ids[1]}")
        with self.get_db() as conn:
            before_values = [tuple(row) for row in conn.execute('SELECT * FROM case_manager_series_cell_values WHERE series_case_id=? ORDER BY id', (series['id'],))]
            before_formats = [tuple(row) for row in conn.execute('SELECT * FROM case_manager_series_cell_formats WHERE series_case_id=? ORDER BY id', (series['id'],))]
        result = self.client.post(base + '/table/delete', json={'axis': 'column', 'keys': ['custom_delete']})
        self.assertEqual(result.status_code, 200, result.text)
        undo = self.client.post(base + '/table/paste-replay', json={'token': result.json()['undo_token'], 'direction': 'undo'})
        self.assertEqual(undo.status_code, 200, undo.text)
        with self.get_db() as conn:
            self.assertEqual([tuple(row) for row in conn.execute('SELECT * FROM case_manager_series_cell_values WHERE series_case_id=? ORDER BY id', (series['id'],))], before_values)
            self.assertEqual([tuple(row) for row in conn.execute('SELECT * FROM case_manager_series_cell_formats WHERE series_case_id=? ORDER BY id', (series['id'],))], before_formats)

    def test_row_delete_undo_restores_prior_archived_state(self):
        series = self.create_series()
        child = series['children'][0]
        base = f"/api/case-manager/series/{series['id']}"
        with self.get_db() as conn:
            conn.execute("UPDATE case_manager_cases SET source_status='archived' WHERE id=?", (child['id'],))
            conn.commit()
        result = self.client.post(base + '/table/delete', json={'axis': 'row', 'ids': [child['id']]})
        self.assertEqual(result.status_code, 200, result.text)
        undo = self.client.post(base + '/table/paste-replay', json={'token': result.json()['undo_token'], 'direction': 'undo'})
        self.assertEqual(undo.status_code, 200, undo.text)
        actual = self.client.get(base).json()['children'][0]
        self.assertEqual(actual['id'], child['id'])
        self.assertEqual(actual['source_status'], 'archived')
