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
    def test_messages_are_injected_only_into_public_snapshot_and_derive_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            stage=Path(directory);(stage/'frontend').mkdir()
            page=stage/'frontend/index.html';page.write_text('<html><head></head><body></body></html>')
            builder.configure_public_messages(stage,'https://stella-admin.pages.dev/v1/events')
            text=page.read_text()
            self.assertIn('https://stella-admin.pages.dev/v1/messages',text)
            self.assertIn('apex-system-messages.js',text)
            self.assertNotIn('stella-system-messages', (ROOT/'frontend/index.html').read_text())
            for invalid in ['http://example.test/v1/events','https://example.test/other','https://name@example.test/v1/events']:
                with self.assertRaises(ValueError):builder.configure_public_messages(stage,invalid)

    def test_source_allowlist_never_includes_runtime_or_credentials(self):
        for path in ['legal_kb.db','uploads/case.docx','backend/local_ai_secrets.py','local_ai_prefs.json',
                     'frontend/manual-images/user.png','backend/personal_center.py','frontend/personal-center.html','backend/archive_templates/user.docx',
                     'backend/browser-profile/cookies.json','backend/data/private.py','backend/contract_templates/user.docx']:
            self.assertFalse(builder.allowed(path),path)
        for path in ['backend/main.py','frontend/app.js','frontend/ai-api-manager.html',
                     'frontend/mcp-manager.html','frontend/skill-manager.html','frontend/stella-brand.png','frontend/user-manual.md']:
            self.assertTrue(builder.allowed(path),path)

    def test_public_snapshot_removes_real_team_and_client_defaults(self):
        replacements = builder.public_replacements(ROOT)
        self.assertGreater(len(replacements), 15)
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            builder.isolated_source(ROOT, stage)
            for path in stage.rglob('*'):
                if path.is_file() and path.suffix in builder.TEXT_SUFFIXES:
                    text = path.read_text()
                    for private in replacements:
                        self.assertNotIn(private, text, str(path.relative_to(stage)))
                    if path.suffix == '.py':
                        compile(text, str(path), 'exec')

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

    def test_public_personal_finance_is_removed_without_changing_private_source(self):
        private = (ROOT/'backend/main.py').read_text()
        public = builder.public_source_text('backend/main.py', private, {})
        self.assertIn('register_personal_center_routes(app, get_db, FRONTEND_DIR)', private)
        self.assertNotIn('from .personal_center import', public)
        self.assertNotIn('from .feishu_family_finance_sync import', public)
        app = builder.public_source_text('frontend/app.js', (ROOT/'frontend/app.js').read_text(), {})
        self.assertNotIn("{ id: 'personal_center', title:", app)
        self.assertNotIn('id="settings-section-personal-center"', builder.public_source_text('frontend/index.html', (ROOT/'frontend/index.html').read_text(), {}))

class PublicUpdateTests(unittest.TestCase):
    def test_update_configuration_is_separate_and_rejects_bad_endpoints(self):
        import base64
        key=base64.b64encode(bytes(32)).decode()
        info=builder.public_bundle_info('1.0.1','2026101901',key,'https://metrics.example.test/v1/events')
        self.assertEqual(info['LSMinimumSystemVersion'],'12.0')
        self.assertEqual(info['CFBundleIdentifier'],'com.stella.public.native')
        self.assertFalse(info['SUAutomaticallyUpdate'])
        self.assertTrue(info['SUVerifyUpdateBeforeExtraction'])
        for url in ('http://metrics.example.test/v1/events','https://metrics.example.test/private','https://metrics.example.test/v1/events?key=secret'):
            with self.assertRaises(ValueError):builder.public_bundle_info('1.0.1','1',key,url)
        with self.assertRaises(ValueError):builder.public_bundle_info('1.0.1','0',key,'https://metrics.example.test/v1/events')

    def test_upgrade_backup_preserves_database_and_leaves_uploads_untouched(self):
        import sqlite3,json
        with tempfile.TemporaryDirectory() as directory:
            runtime=Path(directory)
            uploads=runtime/'uploads';uploads.mkdir();(uploads/'example.txt').write_text('anonymous fixture')
            with sqlite3.connect(runtime/'legal_kb.db') as db:
                db.execute('CREATE TABLE example(value TEXT)')
                db.execute("INSERT INTO example VALUES('preserved')")
            marker=entry.backup_for_build(runtime,'2026101901')
            backups=list((runtime/'data/history_backups').glob('*.db'))
            self.assertEqual(len(backups),1)
            with sqlite3.connect(backups[0]) as db:self.assertEqual(db.execute('SELECT value FROM example').fetchone()[0],'preserved')
            marker.write_text(json.dumps({'build':'2026101901'}))
            entry.backup_for_build(runtime,'2026101901')
            self.assertEqual(len(list((runtime/'data/history_backups').glob('*.db'))),1)
            entry.backup_for_build(runtime,'2026101902')
            self.assertEqual(len(list((runtime/'data/history_backups').glob('*.db'))),2)
            self.assertEqual((uploads/'example.txt').read_text(),'anonymous fixture')

    def test_feed_generation_retains_published_urls_for_older_builds(self):
        import base64,plistlib,zipfile
        import xml.etree.ElementTree as ET
        release=module('prepare_public_update','scripts/distribution/prepare_update.py')
        key=base64.b64encode(bytes(32)).decode()
        with tempfile.TemporaryDirectory() as directory:
            archives=Path(directory)
            for number in ('1','2'):
                info=builder.public_bundle_info('1.0.'+number,number,key,'https://metrics.example.test/v1/events')
                with zipfile.ZipFile(archives/('Stella-'+number+'.zip'),'w') as archive:
                    archive.writestr('Stella.app/Contents/Info.plist',plistlib.dumps(info))
            old_url=release.DOWNLOAD_ROOT+'v1.0.1-1/Stella-1.zip'
            old_item='<item><sparkle:version>1</sparkle:version><enclosure url="'+old_url+'" sparkle:edSignature="existing" /></item>'
            prefix='<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle"><channel>'
            (archives/'appcast.xml').write_text(prefix+old_item+'</channel></rss>')
            notes=archives/'notes.md';notes.write_text('anonymous fixture')
            def generate(command, **kwargs):
                if str(command[0]).endswith('generate_appcast'):
                    # Upstream generation can rewrite old URLs with the new prefix.
                    rewritten=old_item.replace('v1.0.1-1','v1.0.2-2')
                    new_item='<item><sparkle:version>2</sparkle:version><enclosure url="'+release.DOWNLOAD_ROOT+'v1.0.2-2/Stella-2.zip" length="'+str((archives/'Stella-2.zip').stat().st_size)+'" sparkle:edSignature="new" /></item>'
                    (archives/'appcast.xml').write_text(prefix+new_item+rewritten+'</channel></rss>')
            with patch.object(release,'tools',return_value=Path('/verified-sdk')), patch.object(release,'public_key',return_value=key), patch.object(release.subprocess,'run',side_effect=generate):
                plan=release.prepare(archives,archives/'Stella-2.zip',notes)
            items=ET.parse(archives/'appcast.xml').getroot().findall('./channel/item')
            self.assertEqual(items[1].find('enclosure').get('url'),old_url)
            self.assertEqual(set(plan['upload_to_release']),{'Stella-2.zip'})

if __name__=='__main__': unittest.main()
