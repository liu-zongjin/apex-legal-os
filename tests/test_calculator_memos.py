from contextlib import closing
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.calculator_memos import TITLES, add_schema, create_router
from backend.case_ai import database_schema, focused_snapshot, run_query
from backend.database import connect_database


def test_calculator_memos_persist_as_case_scoped_evidence(tmp_path):
    def db():
        return connect_database(tmp_path / "anonymous.db")

    with closing(db()) as conn, conn:
        conn.executescript("""
            CREATE TABLE case_manager_cases (id INTEGER PRIMARY KEY, title TEXT, source_status TEXT);
            CREATE TABLE research_projects (id INTEGER PRIMARY KEY, case_id INTEGER, updated_at TEXT);
            CREATE TABLE research_case_memo_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER REFERENCES research_projects(id), title TEXT,
                content TEXT, created_at TEXT, updated_at TEXT
            );
            INSERT INTO case_manager_cases VALUES (1, '匿名案件甲', 'active'), (2, '匿名案件乙', 'active');
            INSERT INTO research_projects VALUES (3, 1, ''), (4, 2, '');
            INSERT INTO research_case_memo_entries VALUES (1, 4, '另一案件备忘录', '其他案件资料', '', '');
        """)
        add_schema(conn)

    app = FastAPI()
    app.include_router(create_router(db, lambda conn, case_id: case_id + 2))
    client = TestClient(app)
    memo_ids = []
    for calculation_type, title in TITLES.items():
        payload = {
            "requestId": str(uuid4()), "type": calculation_type,
            "parameters": {"amount": 100000},
            "details": f"{title}\n明细 1000 元\n合计 101000 元",
        }
        route = "/api/case-research/cases/1/calculator-memos"
        created = client.post(route, json=payload)
        assert created.status_code == 200, created.text
        memo_id = created.json()["id"]
        memo_ids.append(memo_id)
        assert client.post(route, json=payload).json() == {"id": memo_id, "existing": True}
        assert client.post(route, json={**payload, "details": "不同结果"}).status_code == 409
        snapshot = client.get(f"/api/calculator-memos/{memo_id}").json()
        assert snapshot["type"] == calculation_type
        assert snapshot["details"] == payload["details"]

    with closing(db()) as conn:
        # Case AI reads the same persisted memo text through its scoped query path.
        scoped, schema, _ = focused_snapshot(conn, database_schema(conn), 1)
        with closing(scoped):
            result = run_query(scoped, schema, """
                SELECT m.title, m.content FROM research_case_memo_entries m
                JOIN research_projects p ON p.id=m.project_id ORDER BY m.id
            """)
        assert [row["title"] for row in result["rows"]] == list(TITLES.values())
        assert all("合计 101000 元" in row["content"] for row in result["rows"])

    with closing(db()) as conn, conn:
        conn.execute("DELETE FROM research_case_memo_entries WHERE id=?", (memo_ids[0],))
        assert not conn.execute("SELECT 1 FROM calculator_memo_snapshots WHERE memo_id=?",
                                (memo_ids[0],)).fetchone()
    assert client.get(f"/api/calculator-memos/{memo_ids[0]}").status_code == 404
