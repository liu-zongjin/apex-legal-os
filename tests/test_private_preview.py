import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent.parent

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod

builder=module('preview_builder','scripts/build_private_preview.py')
entry=module('preview_entry','scripts/distribution/preview_entry.py')

class PrivatePreviewTests(unittest.TestCase):
    def test_source_allowlist_never_includes_runtime_or_credentials(self):
        for path in ['legal_kb.db','uploads/case.docx','backend/local_ai_secrets.py','local_ai_prefs.json',
                     'frontend/manual-images/user.png','frontend/user-manual.md','backend/archive_templates/user.docx',
                     'backend/browser-profile/cookies.json','backend/data/private.py','backend/contract_templates/user.docx']:
            self.assertFalse(builder.allowed(path),path)
        for path in ['backend/main.py','frontend/app.js','frontend/ai-api-manager.html',
                     'frontend/mcp-manager.html','frontend/skill-manager.html','frontend/stella-brand.png']:
            self.assertTrue(builder.allowed(path),path)

    def test_runtime_isolated_and_inherited_credentials_removed(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'DEEPSEEK_API_KEY':'test-provider-credential',
                'QQ_MAIL_AUTH_CODE':'test-mail-credential','QCC_MCP_AUTHORIZATION':'test-mcp-credential','CODEX_HOME':'/old-private-skills'},clear=True):
            root=entry.configure(Path(directory))
            self.assertNotIn('DEEPSEEK_API_KEY',os.environ)
            self.assertNotIn('QQ_MAIL_AUTH_CODE',os.environ)
            self.assertNotIn('QCC_MCP_AUTHORIZATION',os.environ)
            self.assertEqual(Path(os.environ['LEGAL_KB_DB_PATH']),root/'legal_kb.db')
            self.assertEqual(os.environ['CODEX_HOME'],str(root/'skills-home'))
            self.assertEqual(os.environ['LEGAL_KB_HOST'],'127.0.0.1')

    def test_examples_are_idempotent_and_never_reinsert_deleted_articles(self):
        import sqlite3
        from backend import main
        with tempfile.TemporaryDirectory() as directory:
            database=Path(directory)/'examples.db'
            def db():
                conn=sqlite3.connect(database);conn.row_factory=sqlite3.Row;return conn
            with db() as conn:
                conn.executescript("""
                  CREATE TABLE app_preferences(preference_key TEXT PRIMARY KEY,value_json TEXT,updated_at TEXT);
                  CREATE TABLE articles(id INTEGER PRIMARY KEY,title TEXT,content TEXT,summary TEXT,domains TEXT,
                    source_type TEXT,source_hash TEXT UNIQUE,created_at TEXT,tags TEXT);
                  CREATE TABLE article_paragraphs(article_id INTEGER,paragraph_index INTEGER,text TEXT,
                    char_start INTEGER,char_end INTEGER,heading TEXT,created_at TEXT);
                """)
            self.assertTrue(entry.seed_preview_articles(db))
            self.assertFalse(entry.seed_preview_articles(db))
            with db() as conn:
                self.assertEqual(conn.execute('SELECT count(*) FROM articles').fetchone()[0],3)
                self.assertGreater(conn.execute('SELECT count(*) FROM article_paragraphs').fetchone()[0],3)
                conn.execute('DELETE FROM articles WHERE id=1')
            self.assertFalse(entry.seed_preview_articles(db))
            with db() as conn: self.assertEqual(conn.execute('SELECT count(*) FROM articles').fetchone()[0],2)

    def test_bundle_audit_rejects_private_files_but_allows_library_data(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Path(directory)
            dependency=app/'Contents/Resources/Server/_internal/cv2/data';dependency.mkdir(parents=True)
            (dependency/'__init__.py').write_text('# third-party public library')
            ca=app/'Contents/Resources/Server/_internal/certifi';ca.mkdir(parents=True)
            (ca/'cacert.pem').write_text('public trust-store')
            builder.audit_bundle(app)
            private=app/'legal_kb.db';private.touch()
            with self.assertRaises(RuntimeError): builder.audit_bundle(app)
            private.unlink()
            private=app/'local_ai_secrets.py';private.write_text('secret=True')
            with self.assertRaises(RuntimeError): builder.audit_bundle(app)

    def test_snapshot_reads_git_blobs_and_ignores_even_tracked_user_data(self):
        with tempfile.TemporaryDirectory() as directory:
            repo=Path(directory)/'repo';repo.mkdir()
            for path,text in {'backend/main.py':'# program source\n','backend/local_ai_secrets.py':'KEY="private"',
                'frontend/app.js':'// program source\n','uploads/private.txt':'private case',
                'scripts/distribution/preview_entry.py':'# isolated entry\n', 'scripts/distribution/preview-brand.css':'/* default brand */'}.items():
                p=repo/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
            subprocess.run(['git','init','-q'],cwd=repo,check=True)
            subprocess.run(['git','add','.'],cwd=repo,check=True)
            subprocess.run(['git','-c','user.name=Anonymous Test','-c','user.email=test@example.invalid','commit','-qm','fixture'],cwd=repo,check=True)
            (repo/'backend/main.py').write_text('# uncommitted private mutation\n')
            stage=Path(directory)/'stage';stage.mkdir()
            manifest=builder.isolated_source(repo,stage)
            self.assertEqual((stage/'backend/main.py').read_text(),'# program source\n')
            self.assertFalse((stage/'backend/local_ai_secrets.py').exists())
            self.assertFalse((stage/'uploads').exists())
            self.assertEqual(len(manifest),2)

if __name__=='__main__': unittest.main()
