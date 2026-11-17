"""Subcase audit regressions, using the existing isolated anonymous database."""
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.series_manager import register_series_manager_routes

from tests import test_series_manager as series_fixtures


class SeriesAuditTests(unittest.TestCase):
    setUp = series_fixtures.SeriesManagerTests.setUp
    tearDown = series_fixtures.SeriesManagerTests.tearDown
    create_series = series_fixtures.SeriesManagerTests.create_series

    def sparse_codes(self):
        series = self.create_series()
        child = series['children'][0]
        response = self.client.put(
            f"/api/case-manager/series/{series['id']}/children/{child['id']}",
            json={'series_code': '003'},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return series

    def test_auto_code_skips_manual_codes_and_deleted_reservations(self):
        series = self.sparse_codes()
        base = f"/api/case-manager/series/{series['id']}/children"
        first = self.client.post(base, json={'display_name': '匿名新增子案'})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()['series_code'], '004')
        self.assertEqual(self.client.delete(f"{base}/{first.json()['id']}").status_code, 200)
        second = self.client.post(base, json={'display_name': '匿名再次新增'})
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()['series_code'], '005')

    def test_multi_row_insert_skips_code_collisions_atomically(self):
        series = self.sparse_codes()
        result = self.client.post(
            f"/api/case-manager/series/{series['id']}/children/insert",
            json={'position': 1, 'count': 2},
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual([item['series_code'] for item in result.json()['items']], ['004', '005'])
        children = self.client.get(f"/api/case-manager/series/{series['id']}").json()['children']
        self.assertEqual([item['series_code'] for item in children], ['003', '004', '005', '002'])

    def test_repeated_series_delete_preserves_child_restore_status(self):
        series = self.create_series()
        child = series['children'][0]
        root = f"/api/case-manager/series/{series['id']}"
        response = self.client.post(root + '/children/bulk', json={
            'child_ids': [child['id']], 'operation': 'archive', 'payload': {},
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.delete(f"{root}/children/{child['id']}").status_code, 200)
        for _ in range(2):
            self.assertEqual(self.client.delete(root).status_code, 200)
        with self.get_db() as conn:
            row = conn.execute('SELECT source_status,pre_delete_status FROM case_manager_cases WHERE id=?', (child['id'],)).fetchone()
            self.assertEqual(tuple(row), ('deleted', 'archived'))
            parent = conn.execute('SELECT pre_delete_status FROM case_manager_cases WHERE id=?', (series['id'],)).fetchone()
            self.assertEqual(parent[0], 'active')

    def test_bulk_lifecycle_runs_calendar_hooks_after_commit_and_unpins(self):
        events = []
        def record(case_id, action):
            with self.get_db() as conn:
                row = conn.execute('SELECT source_status,pinned FROM case_manager_cases WHERE id=?', (case_id,)).fetchone()
                events.append((case_id, action, row['source_status'], row['pinned']))
        app = FastAPI()
        register_series_manager_routes(app, self.get_db, calendar_hooks={
            'clear_case_calendar_items': lambda case_id: record(case_id, 'clear'),
            'sync_case_calendar_items_if_enabled': lambda case_id: record(case_id, 'sync'),
        })
        self.client = TestClient(app)
        series = self.create_series()
        child_id = series['children'][0]['id']
        root = f"/api/case-manager/series/{series['id']}/children"
        with self.get_db() as conn:
            conn.execute('UPDATE case_manager_cases SET pinned=1 WHERE id=?', (child_id,))
        for action in ['archive', 'restore', 'delete']:
            response = self.client.post(root + '/bulk', json={'child_ids': [child_id], 'operation': action, 'payload': {}})
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(events, [
            (child_id, 'clear', 'archived', 0), (child_id, 'sync', 'active', 0), (child_id, 'clear', 'deleted', 0),
        ])
        self.assertEqual(self.client.delete(f'{root}/{child_id}').status_code, 200)
        self.assertEqual(events[-1], (child_id, 'clear', 'deleted', 0))
        rejected = self.client.post(root + '/bulk', json={'child_ids': [1], 'operation': 'archive', 'payload': {}})
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(len(events), 4)

    def test_series_lifecycle_calendar_hooks_follow_committed_scope(self):
        events = []
        def record(case_id):
            with self.get_db() as conn:
                events.append((case_id, conn.execute('SELECT source_status FROM case_manager_cases WHERE id=?', (case_id,)).fetchone()[0]))
        app = FastAPI()
        register_series_manager_routes(app, self.get_db, calendar_hooks={
            'clear_case_calendar_items': record,
            'sync_case_calendar_items_if_enabled': record,
        })
        self.client = TestClient(app)
        series = self.create_series()
        ids = [series['id'], *[child['id'] for child in series['children']]]
        root = f"/api/case-manager/series/{series['id']}"
        self.assertEqual(self.client.post(root + '/archive', json={'force': True}).status_code, 200)
        self.assertEqual(events, [(case_id, 'archived') for case_id in ids])
        self.assertEqual(self.client.post(root + '/restore').status_code, 200)
        self.assertEqual(events[-1], (series['id'], 'active'))
        events.clear()
        self.assertEqual(self.client.delete(root).status_code, 200)
        self.assertEqual(events, [(case_id, 'deleted') for case_id in ids])
        self.assertEqual(self.client.delete(root).status_code, 200)
        self.assertEqual(len(events), len(ids))


if __name__ == '__main__':
    unittest.main()
