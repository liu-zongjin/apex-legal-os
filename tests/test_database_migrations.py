import sqlite3
import unittest

from backend.migrations import migrate_database


class DatabaseMigrationTests(unittest.TestCase):
    def test_migrations_are_repeat_safe_and_back_up_existing_database(self):
        with self.subTest("temporary database"):
            import tempfile
            from pathlib import Path
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                database = root / "apex.db"
                with sqlite3.connect(database) as connection:
                    connection.execute("CREATE TABLE existing_record (id INTEGER PRIMARY KEY)")
                    connection.execute("INSERT INTO existing_record VALUES (1)")
                backup_root = root / "backups"
                self.assertEqual(migrate_database(database, backup_root), list(range(1, 31)))
                self.assertEqual(migrate_database(database, backup_root), [])
                with sqlite3.connect(database) as connection:
                    self.assertEqual(connection.execute("SELECT count(*) FROM existing_record").fetchone()[0], 1)
                    self.assertEqual(connection.execute("SELECT version FROM schema_migrations").fetchall(), [(i,) for i in range(1, 31)])
                    self.assertIsNotNone(connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='case_archive_saves'"
                    ).fetchone())
                self.assertEqual(len(list(backup_root.glob("*.db"))), 1)

    def test_history_case_assignment_keeps_existing_conversations(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "history.db"
            backups = root / "backups"
            with sqlite3.connect(database) as connection:
                connection.executescript("""
                    CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT,applied_at TEXT);
                    CREATE TABLE ai_ask_conversations(id INTEGER PRIMARY KEY,history_key TEXT,context_json TEXT);
                    INSERT INTO ai_ask_conversations VALUES(1,'ask_history_fixture','null');
                    CREATE TABLE memory_versions(id INTEGER PRIMARY KEY,memory_id INTEGER,content TEXT,version INTEGER,changed_at TEXT);
                    INSERT INTO memory_versions VALUES(1,2,'匿名历史内容',3,'2026-11-20');
                """)
                connection.executemany("INSERT INTO schema_migrations VALUES (?,'old','2026-11-20')",
                                       [(i,) for i in range(1, 28)])
            self.assertEqual(migrate_database(database, backups), [28, 29, 30])
            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute(
                    "SELECT history_key,context_json,filed_case_id FROM ai_ask_conversations"
                ).fetchone(), ("ask_history_fixture", "null", None))
                self.assertEqual(connection.execute(
                    "SELECT content,version,status FROM memory_versions WHERE memory_id=2"
                ).fetchone(), ("匿名历史内容", 3, ""))
            with sqlite3.connect(next(backups.glob("*-before-v30-*.db"))) as connection:
                self.assertEqual(connection.execute("SELECT * FROM ai_ask_conversations").fetchone(),
                                 (1, "ask_history_fixture", "null"))

    def test_default_update_backup_location_is_history_backups(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "legal_kb.db"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE existing_record (id INTEGER PRIMARY KEY)")

            self.assertEqual(migrate_database(database), list(range(1, 31)))

            with sqlite3.connect(database) as connection:
                indexes = {row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )}
            # A baseline-only database does not have optional scheduler tables;
            # the migration remains safely repeatable in that shape.
            self.assertNotIn("idx_authority_watch_due", indexes)

            backups = list((root / "data" / "history_backups").glob("*.db"))
            self.assertEqual(len(backups), 1)
            self.assertFalse((root / "data" / "schema_backups").exists())

    def test_existing_memory_settings_gain_revision_without_losing_data(self):
        import tempfile
        from pathlib import Path
        from backend.user_memory import snapshot
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / 'legacy.db'
            with sqlite3.connect(database) as connection:
                connection.executescript("""
                    CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT,applied_at TEXT);
                    CREATE TABLE user_memory_settings(id INTEGER PRIMARY KEY,enabled INTEGER,auto_save INTEGER);
                    INSERT INTO user_memory_settings VALUES(1,0,1);
                    CREATE TABLE user_memories(id INTEGER PRIMARY KEY,content TEXT,source TEXT,created_at TEXT,updated_at TEXT);
                    INSERT INTO user_memories VALUES(1,'匿名偏好','manual','2026-10-12','2026-10-12');
                """)
                connection.executemany("INSERT INTO schema_migrations VALUES (?,'old','2026-10-12')",[(i,) for i in range(1,19)])
            self.assertEqual(migrate_database(database,root / 'backups'),[19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30])
            self.assertEqual(migrate_database(database,root / 'backups'),[])
            state = snapshot(lambda:sqlite3.connect(database))
            self.assertFalse(state['enabled'])
            self.assertTrue(state['auto_save'])
            self.assertEqual(state['revision'],0)
            self.assertEqual(state['items'][0]['content'],'匿名偏好')
            self.assertEqual(len(list((root / 'backups').glob('*.db'))),1)

    def test_upgrade_consolidates_historical_domain_suggestions(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "apex.db"
            with sqlite3.connect(database) as connection:
                connection.executescript("""
                    CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT,applied_at TEXT);
                    CREATE TABLE articles(id INTEGER PRIMARY KEY);
                    CREATE TABLE domain_taxonomy(id INTEGER PRIMARY KEY,name TEXT,parent_id INTEGER);
                    CREATE TABLE domain_suggestions(id INTEGER PRIMARY KEY,name TEXT,parent_id INTEGER,
                        article_id INTEGER,keywords_json TEXT DEFAULT '[]',status TEXT DEFAULT 'pending',created_at TEXT);
                    CREATE TABLE domain_suggestion_articles(suggestion_id INTEGER,article_id INTEGER,
                        PRIMARY KEY(suggestion_id,article_id));
                    INSERT INTO articles(id) VALUES (1),(2);
                    INSERT INTO domain_suggestions(id,name,article_id,created_at) VALUES
                        (1,'举证责任分配',1,'2026-01-01'),
                        (2,'民事诉讼举证责任分配与高度盖然性证明标准',2,'2026-01-01');
                    INSERT INTO domain_suggestion_articles VALUES (1,1),(2,2);
                """)
                connection.executemany("INSERT INTO schema_migrations VALUES (?,'old','2026-01-01')",
                                       [(i,) for i in range(1, 14)])
            self.assertEqual(migrate_database(database, Path(directory) / "backups"), [14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30])
            with sqlite3.connect(database) as connection:
                row = connection.execute("""SELECT s.name,COUNT(e.article_id) FROM domain_suggestions s
                    JOIN domain_suggestion_articles e ON e.suggestion_id=s.id
                    WHERE s.name='民事诉讼' GROUP BY s.id""").fetchone()
                self.assertEqual(row, ("民事诉讼", 2))
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM domain_suggestions WHERE status='pending' AND name<>'民事诉讼'"
                ).fetchone()[0], 2)


    def test_representative_history_upgrade_preserves_old_rows_and_saves_new_details(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from backend.document_generators import create_router, save_document_history

        for partial in (False, True):
            with self.subTest(partial=partial), TemporaryDirectory() as directory:
                root = Path(directory)
                database = root / "legal_kb.db"
                self.assertEqual(migrate_database(database), list(range(1, 31)))

                def connect():
                    return sqlite3.connect(database)

                with connect() as db:
                    db.execute("DELETE FROM schema_migrations WHERE version=30")
                    db.execute("ALTER TABLE document_history RENAME TO fresh_document_history")
                    db.execute("""CREATE TABLE document_history AS SELECT id,doc_type,court,clients,
                        lawyers,parties,case_type,stages,case_number,date,lawyer_contacts,created_at
                        FROM fresh_document_history""")
                    db.execute("DROP TABLE fresh_document_history")
                    db.execute("""INSERT INTO document_history (id,doc_type,clients,date,created_at)
                        VALUES (1,'rep_identity_cert','["匿名旧委托人"]','2026-01-01','2026-01-01')""")
                    if partial:
                        db.execute("ALTER TABLE document_history ADD COLUMN rep_name TEXT DEFAULT ''")
                        db.execute("UPDATE document_history SET rep_name='匿名既有代表' WHERE id=1")
                self.assertEqual(migrate_database(database), [30])
                self.assertEqual(migrate_database(database), [])
                with connect() as db:
                    self.assertEqual(db.execute(
                        "SELECT rep_name,rep_title FROM document_history WHERE id=1"
                    ).fetchone(), ("匿名既有代表" if partial else "", ""))

        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "legal_kb.db"
            migrate_database(database)

            def get_db():
                return sqlite3.connect(database)

            app = FastAPI()
            app.include_router(create_router(get_db, frontend_dir=root))
            client = TestClient(app)
            prefix = "/api/rep-identity-cert"
            save_document_history("rep_identity_cert", {"clients": ["匿名旧委托人"]}, get_db=get_db)
            self.assertEqual(client.get(prefix + "/history").json()["history"][0]["repName"], "")
            payload = {
                "clientName": "匿名新委托人", "repName": "匿名新代表",
                "repTitle": "匿名职务", "date": "2026-01-02",
            }
            generated = client.post(prefix + "/generate", json=payload)
            self.assertEqual(generated.status_code, 200, generated.text[:100] if not generated.is_success else "")
            self.assertTrue(generated.content.startswith(b"PK"))
            history = client.get(prefix + "/history").json()["history"]
            self.assertEqual([row["repName"] for row in history], ["匿名新代表", ""])
            self.assertEqual(history[0]["repTitle"], "匿名职务")
            manual = {**payload, "clients": ["匿名手动委托人"], "repTitle": "匿名另一职务"}
            self.assertEqual(client.post(prefix + "/save-history", json=manual).status_code, 200)
            self.assertEqual(client.get(prefix + "/history").json()["history"][0]["repTitle"], "匿名另一职务")


if __name__ == "__main__":
    unittest.main()
