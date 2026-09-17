import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend import legal_knowledge as lk
from backend import main


class LegalKnowledgeModuleTests(unittest.TestCase):
    def make_conn(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(
            """
            CREATE TABLE articles (
              id INTEGER PRIMARY KEY, title TEXT, content TEXT, summary TEXT, domains TEXT
            );
            CREATE TABLE article_paragraphs (
              id INTEGER PRIMARY KEY, article_id INTEGER, paragraph_index INTEGER,
              text TEXT, char_start INTEGER, char_end INTEGER, heading TEXT
            );
            """
        )
        return conn

    def test_schema_is_idempotent_and_preserves_articles(self):
        conn = self.make_conn()
        conn.execute(
            "INSERT INTO articles VALUES (1,'原始资料','正文','摘要','[]')"
        )
        lk.ensure_schema(conn)
        lk.ensure_schema(conn)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0], 1)
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'knowledge_%'"
        ).fetchall()}
        self.assertIn("knowledge_extraction_exclusions", tables)
        self.assertIn("knowledge_categories", tables)
        self.assertIn("knowledge_issue_merge_suggestions", tables)
        self.assertIn("knowledge_organization_jobs", tables)
        self.assertIn("knowledge_audit_logs", tables)

    def test_ai_organization_assigns_categories_but_only_suggests_merges(self):
        conn = self.make_conn()
        lk.ensure_schema(conn)
        now = "2026-01-01T00:00:00"
        for title in ("案外人提出执行异议的期限", "案外人执行异议提出期限"):
            conn.execute(
                """INSERT INTO knowledge_issues
                   (title,normalized_title,domain,status,created_at,updated_at)
                   VALUES (?,?,?,'active',?,?)""",
                (title, lk.normalize_text(title), "执行异议", now, now),
            )
        issue_ids = [row[0] for row in conn.execute("SELECT id FROM knowledge_issues ORDER BY id")]
        taxonomy = [{
            "name": "异议程序", "description": "提出和审查程序",
            "children": [{"name": "提出期限", "description": "提出异议的时间要求"}],
        }]
        paths = lk.save_category_taxonomy(conn, "执行异议", taxonomy)
        assigned, suggested, warnings = lk.save_issue_organization_batch(
            conn,
            "执行异议",
            {
                "assignments": [
                    {"issue_id": issue_ids[0], "category_path": ["异议程序", "提出期限"], "confidence": .96},
                    {"issue_id": issue_ids[1], "category_path": ["异议程序", "提出期限"], "confidence": .94},
                ],
                "merge_groups": [{
                    "issue_ids": issue_ids, "recommended_title": "案外人异议的提出期限",
                    "reason": "对象、程序与核心问题相同", "confidence": .93,
                }],
            },
            paths,
            set(issue_ids),
            "test-model",
        )
        self.assertEqual((assigned, suggested, warnings), (2, 1, []))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM knowledge_issue_categories").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT status FROM knowledge_issues ORDER BY id").fetchall()[0][0], "active")
        self.assertEqual(
            conn.execute("SELECT status FROM knowledge_issue_merge_suggestions").fetchone()[0], "pending"
        )
        conn.execute("UPDATE knowledge_issue_merge_suggestions SET status='accepted'")
        lk.save_issue_organization_batch(
            conn,
            "执行异议",
            {
                "assignments": [],
                "merge_groups": [{
                    "issue_ids": issue_ids, "recommended_title": "案外人异议的提出期限",
                    "reason": "再次整理仍认为相似", "confidence": .94,
                }],
            },
            paths,
            set(issue_ids),
            "test-model",
        )
        self.assertEqual(
            conn.execute("SELECT status FROM knowledge_issue_merge_suggestions").fetchone()[0], "accepted"
        )

    def test_verified_citation_is_saved_and_fabricated_quote_is_rejected(self):
        conn = self.make_conn()
        lk.ensure_schema(conn)
        text = "案外人对执行标的享有足以排除强制执行的民事权益时，可以提起执行异议之诉。"
        conn.execute("INSERT INTO articles VALUES (1,'执行异议资料',?,'','[\"执行异议与复议\"]')", (text,))
        conn.execute(
            "INSERT INTO article_paragraphs VALUES (1,1,1,?,0,?, '')", (text, len(text))
        )
        job_id, _ = lk.create_extraction_job(conn, 1, force=True)
        payload = {
            "claims": [
                {
                    "issue_title": "案外人何时可以排除强制执行",
                    "statement": "案外人享有足以排除强制执行的民事权益时可以提起执行异议之诉。",
                    "claim_type": "rule",
                    "confidence": 0.9,
                    "evidence": [{"paragraph_index": 1, "stance": "supports", "quote": "享有足以排除强制执行的民事权益"}],
                },
                {
                    "issue_title": "虚构问题",
                    "statement": "这是一条没有任何原文依据的虚构法律结论。",
                    "evidence": [{"paragraph_index": 1, "stance": "supports", "quote": "原文中根本不存在的引文内容"}],
                },
            ]
        }
        count, warnings = lk.save_extraction_batch(conn, job_id, 1, payload, "test-model")
        self.assertEqual(count, 1)
        self.assertTrue(warnings)
        evidence = conn.execute("SELECT * FROM knowledge_claim_evidence").fetchall()
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["quote"], text)
        self.assertEqual(evidence[0]["verified"], 1)

    def test_model_json_tolerates_code_fence_but_rejects_truncation(self):
        self.assertEqual(lk.parse_model_json('```json\n{"claims": []}\n```')["claims"], [])
        with self.assertRaises(ValueError):
            lk.parse_model_json('{"claims": [')

    def test_batch_job_deduplicates_same_content_but_requeues_changed_content(self):
        conn = self.make_conn()
        lk.ensure_schema(conn)
        conn.execute("INSERT INTO articles VALUES (1,'合同资料','第一版正文内容足够长。','','[\"合同法\"]')")

        first_id, first_created = lk.create_extraction_job(conn, 1, trigger_type="library_batch")
        active_id, active_created = lk.create_extraction_job(conn, 1, trigger_type="library_batch")
        self.assertTrue(first_created)
        self.assertEqual((active_id, active_created), (first_id, False))

        conn.execute("UPDATE knowledge_extraction_jobs SET status='completed' WHERE id=?", (first_id,))
        completed_id, completed_created = lk.create_extraction_job(conn, 1, trigger_type="library_batch")
        self.assertEqual((completed_id, completed_created), (first_id, False))

        conn.execute("UPDATE articles SET content='第二版正文已经发生实质修改。' WHERE id=1")
        changed_id, changed_created = lk.create_extraction_job(conn, 1, trigger_type="library_batch")
        self.assertTrue(changed_created)
        self.assertNotEqual(changed_id, first_id)

    def test_persistently_excluded_article_is_not_a_batch_candidate(self):
        conn = self.make_conn()
        lk.ensure_schema(conn)
        conn.execute("INSERT INTO articles VALUES (1,'合同资料','可供提取的合同法律正文。','','[\"合同法\"]')")
        now = "2026-01-01T00:00:00"
        conn.execute(
            "INSERT INTO knowledge_extraction_exclusions VALUES (1,'用户跳过',?,?)", (now, now)
        )
        self.assertEqual(lk.knowledge_candidate_ids(conn), [])
        self.assertEqual(lk.knowledge_candidate_ids(conn, include_excluded=True), [1])

    def test_non_execution_article_uses_its_existing_professional_domain(self):
        conn = self.make_conn()
        lk.ensure_schema(conn)
        text = "公司股东不得滥用公司法人独立地位和股东有限责任损害公司债权人的利益。"
        conn.execute("INSERT INTO articles VALUES (1,'公司法资料',?,'','[\"公司法\"]')", (text,))
        conn.execute("INSERT INTO article_paragraphs VALUES (1,1,1,?,0,?, '')", (text, len(text)))
        job_id, _ = lk.create_extraction_job(conn, 1, force=True)
        payload = {"claims": [{
            "domain": "公司法",
            "issue_title": "股东滥用法人独立地位的责任",
            "statement": "股东不得滥用公司法人独立地位和有限责任损害公司债权人利益。",
            "evidence": [{"paragraph_index": 1, "stance": "supports", "quote": "不得滥用公司法人独立地位"}],
        }]}
        count, warnings = lk.save_extraction_batch(conn, job_id, 1, payload, "test-model")
        self.assertEqual((count, warnings), (1, []))
        issue = conn.execute("SELECT domain FROM knowledge_issues").fetchone()
        self.assertEqual(issue["domain"], "公司法")
        self.assertEqual(lk.knowledge_candidate_ids(conn, "公司法"), [1])

    def test_exact_100_percent_confidence_auto_approves_with_verified_evidence(self):
        conn = self.make_conn()
        lk.ensure_schema(conn)
        text = "当事人应当依照约定全面履行自己的义务，并遵循诚信原则。"
        conn.execute("INSERT INTO articles VALUES (1,'合同法资料',?,'','[\"合同法\"]')", (text,))
        conn.execute("INSERT INTO article_paragraphs VALUES (1,1,1,?,0,?, '')", (text, len(text)))
        job_id, _ = lk.create_extraction_job(conn, 1, force=True)
        payload = {"claims": [{
            "domain": "合同法",
            "issue_title": "合同义务如何履行",
            "statement": "当事人应当依照约定全面履行自己的合同义务。",
            "confidence": 1.0,
            "evidence": [{"paragraph_index": 1, "stance": "supports", "quote": "依照约定全面履行自己的义务"}],
        }]}
        count, warnings = lk.save_extraction_batch(conn, job_id, 1, payload, "test-model")
        self.assertEqual((count, warnings), (1, []))
        claim = conn.execute("SELECT review_status,reviewer_note FROM knowledge_claims").fetchone()
        self.assertEqual(claim["review_status"], "approved")
        self.assertIn("系统自动通过", claim["reviewer_note"])
        audit = conn.execute("SELECT action,actor FROM knowledge_audit_logs").fetchone()
        self.assertEqual((audit["action"], audit["actor"]), ("auto_approve_confidence", "system"))

    def test_provision_numbers_match_arabic_and_chinese_forms(self):
        self.assertEqual(main._legal_provision_numbers("公司法第100条原文是什么"), [100])
        self.assertEqual(main._legal_provision_numbers("公司法第一百零一条如何规定"), [101])
        self.assertEqual(
            main._legal_provision_locators("公司法第100条原文是什么"),
            ["第100条", "第一百条"],
        )

    def test_exact_provision_extraction_includes_list_items_only_until_next_article(self):
        content = """
        <p>第九十九条 前一条。</p>
        <p><strong>第一百条</strong> 本条首款：</p>
        <p>（一）第一项；</p><p>（二）第二项。</p>
        <p>第一百零一条 后一条。</p>
        """
        extracted = main._extract_provision_from_text(content, 100)
        self.assertIn("第一百条", extracted)
        self.assertIn("（一）第一项", extracted)
        self.assertIn("（二）第二项", extracted)
        self.assertNotIn("第一百零一条", extracted)

    def test_exact_provision_prefers_primary_law_over_commentary(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE articles (
              id INTEGER PRIMARY KEY, title TEXT, content TEXT, summary TEXT,
              source_url TEXT, source_filename TEXT
            );
            CREATE TABLE article_paragraphs (
              id INTEGER PRIMARY KEY, article_id INTEGER, paragraph_index INTEGER,
              text TEXT, char_start INTEGER, char_end INTEGER, heading TEXT
            );
            """
        )
        primary = "第九十九条 前条。\n\n第一百条\n\u3000准确原文。\n\n第一百零一条 后条。"
        commentary = "第一百条\n\u3000评论文章中的转述。\n\n第一百零一条 其他内容。"
        conn.execute("INSERT INTO articles VALUES (1,'中华人民共和国公司法',?,'','','')", (primary,))
        conn.execute("INSERT INTO articles VALUES (2,'公司法第一百条实务解读',?,'','','')", (commentary,))
        conn.execute(
            "INSERT INTO article_paragraphs VALUES (1,1,1,'第一百条 准确原文。',0,10,'第一百条')"
        )
        match = main._find_exact_provisions("公司法第100条原文是什么", conn)
        self.assertIsNotNone(match)
        self.assertEqual(match["id"], 1)
        self.assertIn("准确原文", match["provisions"][0]["text"])
        conn.close()


class LegalKnowledgeApiTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_db_path = main.DB_PATH
        main.DB_PATH = Path(self.tempdir.name) / "test.db"
        main.init_db()
        self.client = TestClient(main.app)
        self.article_text = "案外人对执行标的享有足以排除强制执行的民事权益时，可以提起执行异议之诉。"
        with main.get_db() as conn:
            cur = conn.execute(
                """INSERT INTO articles
                   (title,content,summary,domains,source_type,source_hash,created_at,tags)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    "执行异议测试资料", self.article_text, "执行异议之诉规则",
                    json.dumps(["执行异议与复议"], ensure_ascii=False), "file", "test-hash",
                    "2026-01-01T00:00:00", "[]",
                ),
            )
            self.article_id = cur.lastrowid
            main.rebuild_article_paragraphs(conn, self.article_id, self.article_text)
            job_id, _ = lk.create_extraction_job(conn, self.article_id, force=True)
            payload = {
                "claims": [{
                    "issue_title": "案外人何时可以排除强制执行",
                    "statement": "案外人享有足以排除强制执行的民事权益时可以提起执行异议之诉。",
                    "claim_type": "rule",
                    "confidence": 0.95,
                    "evidence": [{
                        "paragraph_index": 1, "stance": "supports",
                        "quote": "享有足以排除强制执行的民事权益",
                    }],
                }]
            }
            lk.save_extraction_batch(conn, job_id, self.article_id, payload, "test-model")
            conn.commit()
            self.claim_id = conn.execute("SELECT id FROM knowledge_claims").fetchone()[0]

    def tearDown(self):
        main.DB_PATH = self.old_db_path
        self.tempdir.cleanup()

    def test_only_approved_claims_enter_qa_context_and_content_change_invalidates(self):
        with main.get_db() as conn:
            context, _ = lk.approved_knowledge_context(conn, "案外人如何排除强制执行")
        self.assertEqual(context, "")

        response = self.client.post(
            f"/api/legal-knowledge/claims/{self.claim_id}/review",
            json={"action": "approve", "note": "人工核验通过"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        with main.get_db() as conn:
            context, citations = lk.approved_knowledge_context(conn, "案外人如何排除强制执行")
        self.assertIn("已审核知识", context)
        self.assertEqual(citations[0]["article_id"], self.article_id)

        response = self.client.put(
            f"/api/articles/{self.article_id}/content",
            json={"content": self.article_text + "\n\n正文发生更新。"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        with main.get_db() as conn:
            status = conn.execute("SELECT review_status FROM knowledge_claims WHERE id=?", (self.claim_id,)).fetchone()[0]
            context, _ = lk.approved_knowledge_context(conn, "案外人如何排除强制执行")
        self.assertEqual(status, "needs_review")
        self.assertEqual(context, "")

    def test_article_knowledge_includes_verified_source_location(self):
        response = self.client.get(f"/api/articles/{self.article_id}/knowledge")
        self.assertEqual(response.status_code, 200, response.text)
        claims = response.json()["claims"]
        self.assertEqual(len(claims), 1)
        evidence = claims[0]["evidence"]
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["article_id"], self.article_id)
        self.assertEqual(evidence[0]["paragraph_index"], 1)
        self.assertEqual(evidence[0]["char_start"], 0)
        self.assertIn("足以排除强制执行", evidence[0]["quote"])

    def test_offline_snapshot_excludes_content_over_800_kb_without_deleting_article(self):
        exact_limit = "a" * main.ARTICLE_OFFLINE_MAX_CONTENT_BYTES
        over_limit = exact_limit + "b"
        with main.get_db() as conn:
            included_id = conn.execute(
                """INSERT INTO articles
                   (title,content,summary,domains,source_type,source_hash,created_at,tags)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    "离线缓存边界文章", exact_limit, "", "[]", "file",
                    "offline-limit-included", "2026-01-03T00:00:00", "[]",
                ),
            ).lastrowid
            excluded_id = conn.execute(
                """INSERT INTO articles
                   (title,content,summary,domains,source_type,source_hash,created_at,tags)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    "超大正文文章", over_limit, "", "[]", "file",
                    "offline-limit-excluded", "2026-01-04T00:00:00", "[]",
                ),
            ).lastrowid
            conn.commit()

        response = self.client.get("/api/articles/offline-snapshot?limit=200")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        snapshot_ids = {article["id"] for article in payload["articles"]}
        self.assertIn(included_id, snapshot_ids)
        self.assertNotIn(excluded_id, snapshot_ids)
        self.assertEqual(payload["max_content_bytes"], 800 * 1024)
        self.assertGreaterEqual(payload["excluded_oversized"], 1)
        with main.get_db() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM articles WHERE id=?", (excluded_id,)).fetchone()[0],
                1,
            )

    def test_url_import_returns_fallback_summary_while_ai_runs_in_background(self):
        content = "\n\n".join([
            "融资租赁合同的所有权安排具有担保功能，应当结合交易结构判断其效力。",
            "当事人应当依法完成相应登记，以便在法律规定的范围内对抗善意第三人。",
            "人民法院应当结合租赁物性质、价值、租金构成以及合同权利义务进行实质审查。",
        ])
        fallback_summary = main.extract_summary(content)
        ai_summary = "## 裁判摘要\n" + "融资租赁中的所有权可以发挥担保功能，但应当完成法定公示。" * 2

        with patch.object(
            main,
            "fetch_webpage",
            return_value={"title": "后台摘要测试文章", "content": content, "author": "测试作者"},
        ), patch.object(
            main,
            "generate_ai_summary",
            new=AsyncMock(return_value=ai_summary),
        ) as generate_mock:
            response = self.client.post(
                "/api/submit/url",
                data={"url": "https://example.com/background-summary-test"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["summary"], fallback_summary)
        self.assertFalse(payload["ai_summary"])
        self.assertTrue(payload["ai_summary_pending"])
        generate_mock.assert_awaited_once()
        with main.get_db() as conn:
            stored_summary = conn.execute(
                "SELECT summary FROM articles WHERE id=?", (payload["id"],)
            ).fetchone()[0]
        self.assertEqual(stored_summary, ai_summary)

    def test_background_summary_does_not_overwrite_manual_edit(self):
        fallback_summary = "入库时的规则摘要"
        manual_summary = "用户已经手工修改的摘要"
        with main.get_db() as conn:
            conn.execute(
                "UPDATE articles SET summary=? WHERE id=?",
                (manual_summary, self.article_id),
            )
            conn.commit()

        generated_summary = "后台生成的 AI 摘要内容足够长，但不应覆盖用户的手工修改。"
        with patch.object(
            main,
            "generate_ai_summary",
            new=AsyncMock(return_value=generated_summary),
        ):
            asyncio.run(main._generate_and_store_ai_summary(
                self.article_id,
                "执行异议测试资料",
                self.article_text,
                fallback_summary,
            ))

        with main.get_db() as conn:
            stored_summary = conn.execute(
                "SELECT summary FROM articles WHERE id=?", (self.article_id,)
            ).fetchone()[0]
        self.assertEqual(stored_summary, manual_summary)

    def test_ai_summary_quality_check_rejects_repeated_markdown_noise(self):
        broken = (
            "## 核心结论\n建设工程竣工验收合格后，发包人主张质量问题应当举证。\n"
            + "\n".join(["1", "**", "`", "1", "”", "1"] * 12)
        )
        self.assertIsNone(main._clean_ai_summary(broken))

    def test_ai_summary_quality_check_accepts_normal_markdown(self):
        summary = """## 核心结论

建设工程竣工验收合格后，发包人仍可主张质量责任，但应对质量缺陷、损失及因果关系承担举证责任。

1. **验收证明力**：竣工验收合格对验收时的工程质量具有较强证明力。
2. **举证责任**：发包人应提交能够证明施工原因的有效证据。
3. **因果关系**：房屋已装修或使用时，还需排除第三人行为等其他原因。"""
        self.assertEqual(main._clean_ai_summary(summary), summary)

    def test_ai_summary_uses_current_purpose_model_through_shared_caller(self):
        summary = """短文的核心裁判规则应当根据权利义务与决定性理由准确提炼。

1. **适用条件**：当事人具备法定要件时，可以依法提出相应请求。
2. **法律后果**：法院应结合证据与具体事实判断请求能否成立。"""
        response = {
            "choices": [{
                "message": {"content": summary},
                "finish_reason": "stop",
            }],
        }
        with patch.object(
            main.ai_config_module,
            "effective_purpose_model",
            return_value="opencode:deepseek-flash",
        ), patch.object(
            main,
            "_call_ai_with_fallback",
            new=AsyncMock(return_value=(response, "opencode:deepseek-flash")),
        ) as call_mock:
            generated = asyncio.run(main.generate_ai_summary("短文标题", "这是用于生成摘要的法律文章正文。" * 20))

        self.assertEqual(generated, summary)
        self.assertEqual(call_mock.await_args.args[0], "opencode:deepseek-flash")
        self.assertEqual(call_mock.await_args.kwargs["max_tokens"], 1200)

    def test_ai_summary_quality_check_rejects_prompt_echo(self):
        leaked = """摘要
西部陆海新通道典型案例突出涉外法律适用与运输规则。

user
请为以下法律文章生成简洁、专业的 Markdown 摘要。
【文章标题】最高人民法院发布典型案例
【正文节选】人民法院依法审理各类案件，不断优化制度机制。"""
        self.assertIsNone(main._clean_ai_summary(leaked))

    def test_ai_summary_quality_check_rejects_truncated_list(self):
        truncated = (
            "最高人民法院发布典型案例，明确涉外合同的法律适用与运输责任规则。\n\n"
            "1. **准据法区分适用**：主合同与保证合同约定不同准据法时，依各自约定"
        )
        self.assertIsNone(main._clean_ai_summary(truncated))

    def test_summary_source_excerpt_keeps_each_case_in_long_collection(self):
        content = "发布说明\n" + "背景" * 1000
        for number in ("一", "二", "三", "四"):
            content += f"\n案例{number} 标题\n" + f"案例{number}核心裁判规则。" * 1000
        excerpt = main._summary_source_excerpt(content, max_chars=8000)
        for number in ("一", "二", "三", "四"):
            self.assertIn(f"案例{number}核心裁判规则", excerpt)

    def test_ai_summary_quality_check_accepts_single_rule_article(self):
        summary = (
            "本文回答了竣工验收后质量索赔的举证责任问题。\n\n"
            "1. **举证责任**：发包人应证明质量缺陷、施工原因与损失之间的因果关系。"
        )
        self.assertEqual(main._clean_ai_summary(summary), summary)

    def test_merge_and_unmerge_are_reversible_and_audited(self):
        with main.get_db() as conn:
            row = conn.execute("SELECT * FROM knowledge_claims WHERE id=?", (self.claim_id,)).fetchone()
            now = "2026-01-01T00:00:00"
            cur = conn.execute(
                """INSERT INTO knowledge_claims
                   (statement,normalized_statement,claim_type,review_status,created_at,updated_at)
                   VALUES (?,?,?,?,?,?)""",
                ("另一条执行异议结论用于合并测试。", lk.normalize_text("另一条执行异议结论用于合并测试。"), "rule", "pending", now, now),
            )
            target_id = cur.lastrowid
            issue_id = conn.execute("SELECT issue_id FROM knowledge_claim_issues WHERE claim_id=?", (self.claim_id,)).fetchone()[0]
            conn.execute("INSERT INTO knowledge_claim_issues VALUES (?,?,1)", (target_id, issue_id))
            conn.commit()

        merged = self.client.post(
            f"/api/legal-knowledge/claims/{self.claim_id}/merge", json={"target_id": target_id}
        )
        self.assertEqual(merged.status_code, 200, merged.text)
        self.assertEqual(merged.json()["claim"]["review_status"], "merged")
        unmerged = self.client.post(
            f"/api/legal-knowledge/claims/{self.claim_id}/merge", json={"undo": True}
        )
        self.assertEqual(unmerged.status_code, 200, unmerged.text)
        self.assertEqual(unmerged.json()["claim"]["review_status"], "pending")
        with main.get_db() as conn:
            actions = [row[0] for row in conn.execute(
                "SELECT action FROM knowledge_audit_logs WHERE object_type='claim' AND object_id=? ORDER BY id",
                (self.claim_id,),
            ).fetchall()]
        self.assertEqual(actions[-2:], ["merge", "unmerge"])

    def test_issue_merge_consolidates_exact_claims_and_undo_restores_links(self):
        with main.get_db() as conn:
            source_issue_id = conn.execute(
                "SELECT issue_id FROM knowledge_claim_issues WHERE claim_id=?", (self.claim_id,)
            ).fetchone()[0]
            source_claim = conn.execute(
                "SELECT * FROM knowledge_claims WHERE id=?", (self.claim_id,)
            ).fetchone()
            now = "2026-01-01T00:00:00"
            target_issue_id = conn.execute(
                """INSERT INTO knowledge_issues
                   (title,normalized_title,domain,status,created_at,updated_at)
                   VALUES (?,?,?,'active',?,?)""",
                (
                    "案外人排除执行的条件", lk.normalize_text("案外人排除执行的条件"),
                    "执行异议", now, now,
                ),
            ).lastrowid
            target_claim_id = conn.execute(
                """INSERT INTO knowledge_claims
                   (statement,normalized_statement,claim_type,review_status,created_at,updated_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    source_claim["statement"], source_claim["normalized_statement"], "rule",
                    "approved", now, now,
                ),
            ).lastrowid
            conn.execute(
                "INSERT INTO knowledge_claim_issues(claim_id,issue_id,is_primary) VALUES (?,?,1)",
                (target_claim_id, target_issue_id),
            )
            distinct_claim_id = conn.execute(
                """INSERT INTO knowledge_claims
                   (statement,normalized_statement,claim_type,review_status,created_at,updated_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    "案外人应当在法定期限内提出执行异议。",
                    lk.normalize_text("案外人应当在法定期限内提出执行异议。"),
                    "procedure", "pending", now, now,
                ),
            ).lastrowid
            conn.execute(
                "INSERT INTO knowledge_claim_issues(claim_id,issue_id,is_primary) VALUES (?,?,1)",
                (distinct_claim_id, source_issue_id),
            )
            conn.commit()

        merged = self.client.post(
            f"/api/legal-knowledge/issues/{source_issue_id}/merge",
            json={"target_id": target_issue_id},
        )
        self.assertEqual(merged.status_code, 200, merged.text)
        detail = self.client.get(f"/api/legal-knowledge/issues/{target_issue_id}").json()
        self.assertEqual({row["id"] for row in detail["claims"]}, {target_claim_id, distinct_claim_id})
        self.assertGreaterEqual(
            len(self.client.get(f"/api/legal-knowledge/claims/{target_claim_id}").json()["evidence"]),
            1,
        )
        all_claims = self.client.get(
            "/api/legal-knowledge/claims?status=all&domain=执行异议&limit=100"
        ).json()["claims"]
        self.assertNotIn(self.claim_id, {row["id"] for row in all_claims})
        with main.get_db() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT review_status FROM knowledge_claims WHERE id=?", (self.claim_id,)
                ).fetchone()[0],
                "merged",
            )
            self.assertTrue(conn.execute(
                "SELECT 1 FROM knowledge_claim_issues WHERE claim_id=? AND issue_id=?",
                (distinct_claim_id, target_issue_id),
            ).fetchone())

        undone = self.client.post(
            f"/api/legal-knowledge/issues/{source_issue_id}/merge", json={"undo": True}
        )
        self.assertEqual(undone.status_code, 200, undone.text)
        with main.get_db() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT review_status FROM knowledge_claims WHERE id=?", (self.claim_id,)
                ).fetchone()[0],
                "pending",
            )
            self.assertFalse(conn.execute(
                "SELECT 1 FROM knowledge_claim_issues WHERE claim_id=? AND issue_id=?",
                (distinct_claim_id, target_issue_id),
            ).fetchone())

    def test_cancel_stops_only_queued_extractions_and_keeps_running_one(self):
        with main.get_db() as conn:
            conn.execute(
                "UPDATE knowledge_extraction_jobs SET status='running' WHERE article_id=?",
                (self.article_id,),
            )
            conn.execute(
                """INSERT INTO knowledge_extraction_jobs
                   (article_id,content_hash,trigger_type,status,created_at,updated_at)
                   VALUES (?,?,?,?,?,?)""",
                (self.article_id, "another-version", "library_batch", "queued",
                 "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
            )
            conn.commit()

        response = self.client.post("/api/legal-knowledge/extractions/cancel")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["cancelled_count"], 1)
        self.assertEqual(response.json()["running_count"], 1)
        with main.get_db() as conn:
            statuses = [row[0] for row in conn.execute(
                "SELECT status FROM knowledge_extraction_jobs ORDER BY id"
            ).fetchall()]
        self.assertEqual(statuses, ["running", "cancelled"])

    def test_selected_running_article_can_be_stopped(self):
        with main.get_db() as conn:
            conn.execute(
                "UPDATE knowledge_extraction_jobs SET status='running' WHERE article_id=?",
                (self.article_id,),
            )
            conn.commit()
        response = self.client.post(
            "/api/legal-knowledge/extractions/stop", json={"article_ids": [self.article_id]}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["running_stopped"], 1)
        with main.get_db() as conn:
            status = conn.execute(
                "SELECT status FROM knowledge_extraction_jobs WHERE article_id=? ORDER BY id DESC LIMIT 1",
                (self.article_id,),
            ).fetchone()[0]
        self.assertEqual(status, "cancelled")

    def test_skipped_article_stays_out_of_batch_until_resumed(self):
        skipped = self.client.post(
            "/api/legal-knowledge/extractions/skip", json={"article_ids": [self.article_id]}
        )
        self.assertEqual(skipped.status_code, 200, skipped.text)
        batch = self.client.post(
            "/api/legal-knowledge/extractions/batch", json={"force": False, "domain": ""}
        )
        self.assertEqual(batch.status_code, 200, batch.text)
        self.assertEqual(batch.json()["candidate_count"], 0)

        resumed = self.client.post(
            "/api/legal-knowledge/extractions/resume", json={"article_ids": [self.article_id]}
        )
        self.assertEqual(resumed.status_code, 200, resumed.text)
        with main.get_db() as conn:
            self.assertEqual(lk.knowledge_candidate_ids(conn), [self.article_id])

    def test_category_filter_and_merge_suggestion_review(self):
        with main.get_db() as conn:
            issue_id = conn.execute("SELECT id FROM knowledge_issues").fetchone()[0]
            now = "2026-01-01T00:00:00"
            cur = conn.execute(
                """INSERT INTO knowledge_issues
                   (title,normalized_title,domain,status,created_at,updated_at)
                   VALUES (?,?,?,'active',?,?)""",
                (
                    "案外人执行异议的提出条件", lk.normalize_text("案外人执行异议的提出条件"),
                    "执行异议", now, now,
                ),
            )
            target_id = cur.lastrowid
            paths = lk.save_category_taxonomy(conn, "执行异议", [{
                "name": "异议程序", "children": [{"name": "提出与受理"}],
            }])
            category_id = paths[("异议程序", "提出与受理")]
            for value in (issue_id, target_id):
                conn.execute(
                    """INSERT INTO knowledge_issue_categories
                       (issue_id,category_id,confidence,assignment_source,reviewed,created_at,updated_at)
                       VALUES (?,?,.9,'ai',0,?,?)""", (value, category_id, now, now),
                )
            conn.execute(
                """INSERT INTO knowledge_issue_merge_suggestions
                   (source_issue_id,target_issue_id,recommended_title,similarity,reason,source,status,
                    model,created_at,updated_at)
                   VALUES (?,?,?,.9,'测试建议','ai','pending','test',?,?)""",
                (issue_id, target_id, "案外人执行异议的提出条件", now, now),
            )
            suggestion_id = conn.execute(
                "SELECT id FROM knowledge_issue_merge_suggestions"
            ).fetchone()[0]
            conn.commit()

        listing = self.client.get(
            f"/api/legal-knowledge/issues?domain=执行异议&category_id={category_id}"
        )
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertEqual(len(listing.json()["issues"]), 2)
        accepted = self.client.post(
            f"/api/legal-knowledge/merge-suggestions/{suggestion_id}/review",
            json={"action": "accept"},
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        with main.get_db() as conn:
            self.assertEqual(
                conn.execute("SELECT status FROM knowledge_issues WHERE id=?", (issue_id,)).fetchone()[0],
                "merged",
            )
            self.assertEqual(
                conn.execute(
                    "SELECT status FROM knowledge_issue_merge_suggestions WHERE id=?", (suggestion_id,)
                ).fetchone()[0],
                "accepted",
            )

    def test_knowledge_center_search_home_and_learning_schedule(self):
        pending_home = self.client.get("/api/legal-knowledge/home")
        self.assertEqual(pending_home.status_code, 200, pending_home.text)
        self.assertEqual(pending_home.json()["stats"]["approved"], 0)

        approved = self.client.post(
            f"/api/legal-knowledge/claims/{self.claim_id}/review",
            json={"action": "approve", "note": "已核验"},
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        search = self.client.get("/api/legal-knowledge/search?q=案外人排除强制执行")
        self.assertEqual(search.status_code, 200, search.text)
        self.assertEqual([item["id"] for item in search.json()["results"]], [self.claim_id])

        favorite = self.client.put(
            f"/api/legal-knowledge/claims/{self.claim_id}/personal-state",
            json={"is_favorite": True},
        )
        self.assertEqual(favorite.status_code, 200, favorite.text)
        home = self.client.get("/api/legal-knowledge/home")
        self.assertEqual(home.status_code, 200, home.text)
        self.assertEqual(home.json()["stats"]["approved"], 1)
        self.assertEqual(home.json()["favorites"][0]["id"], self.claim_id)

        review = self.client.get("/api/legal-knowledge/review/queue")
        self.assertEqual(review.status_code, 200, review.text)
        self.assertEqual(review.json()["cards"][0]["id"], self.claim_id)
        graded = self.client.post(
            f"/api/legal-knowledge/review/{self.claim_id}",
            json={"grade": "mastered"},
        )
        self.assertEqual(graded.status_code, 200, graded.text)
        self.assertEqual(graded.json()["learning"]["interval_days"], 7)

    def test_review_queue_accepts_multiple_domains(self):
        approved = self.client.post(
            f"/api/legal-knowledge/claims/{self.claim_id}/review",
            json={"action": "approve"},
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        now = "2026-01-01T00:00:00"
        with main.get_db() as conn:
            issue_cursor = conn.execute(
                """INSERT INTO knowledge_issues
                   (title,normalized_title,domain,status,created_at,updated_at)
                   VALUES (?,?,?,'active',?,?)""",
                ("股东责任范围", lk.normalize_text("股东责任范围"), "公司法", now, now),
            )
            issue_id = int(issue_cursor.lastrowid)
            claim_cursor = conn.execute(
                """INSERT INTO knowledge_claims
                   (statement,normalized_statement,claim_type,review_status,confidence,created_at,updated_at)
                   VALUES (?,?,?,'approved',?,?,?)""",
                (
                    "股东不得滥用公司法人独立地位损害债权人利益。",
                    lk.normalize_text("股东不得滥用公司法人独立地位损害债权人利益。"),
                    "rule", 0.95, now, now,
                ),
            )
            other_claim_id = int(claim_cursor.lastrowid)
            conn.execute(
                "INSERT INTO knowledge_claim_issues(claim_id,issue_id,is_primary) VALUES (?,?,1)",
                (other_claim_id, issue_id),
            )
            conn.execute(
                """INSERT INTO knowledge_claim_evidence
                   (claim_id,article_id,paragraph_index,stance,quote,source_hash,verified,created_at)
                   VALUES (?,?,?,?,?,?,1,?)""",
                (other_claim_id, self.article_id, 1, "supports", self.article_text, "test-hash", now),
            )
            conn.commit()

        execution_only = self.client.get(
            "/api/legal-knowledge/review/queue?domains=%E6%89%A7%E8%A1%8C%E5%BC%82%E8%AE%AE&limit=8"
        )
        self.assertEqual(execution_only.status_code, 200, execution_only.text)
        self.assertEqual([item["id"] for item in execution_only.json()["cards"]], [self.claim_id])

        multi_domain = self.client.get(
            "/api/legal-knowledge/review/queue?domains=%E5%85%AC%E5%8F%B8%E6%B3%95&domains=%E6%89%A7%E8%A1%8C%E5%BC%82%E8%AE%AE&limit=8"
        )
        self.assertEqual(multi_domain.status_code, 200, multi_domain.text)
        self.assertEqual(
            {item["id"] for item in multi_domain.json()["cards"]},
            {self.claim_id, other_claim_id},
        )
        self.assertEqual(multi_domain.json()["domains"], ["公司法", "执行异议"])

    def test_knowledge_center_add_to_case_is_idempotent(self):
        self.client.post(
            f"/api/legal-knowledge/claims/{self.claim_id}/review",
            json={"action": "approve", "note": "已核验"},
        )
        with main.get_db() as conn:
            now = "2026-01-01T00:00:00"
            cur = conn.execute(
                """INSERT INTO case_manager_cases
                   (title,case_type,memo,created_at,updated_at) VALUES (?,?,?,?,?)""",
                ("知识中心测试案件", "建设工程", "执行异议争点", now, now),
            )
            case_id = int(cur.lastrowid)
            conn.commit()

        first = self.client.post(
            f"/api/legal-knowledge/claims/{self.claim_id}/use",
            json={"action": "add_to_case", "case_id": case_id},
        )
        second = self.client.post(
            f"/api/legal-knowledge/claims/{self.claim_id}/use",
            json={"action": "add_to_case", "case_id": case_id},
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json()["memo_id"], second.json()["memo_id"])
        with main.get_db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM research_case_memo_entries").fetchone()[0], 1)

    def test_case_related_recommendations_keep_legal_context_separate(self):
        """案件类型相同的宽泛词不能把行政语境的结论混入执行案件。"""
        with main.get_db() as conn:
            article_text = "行政机关没有强制执行权时，应当申请人民法院强制执行。"
            cur = conn.execute(
                """INSERT INTO articles
                   (title,content,summary,domains,source_type,source_hash,created_at,tags)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    "行政强制执行测试资料", article_text, "行政机关申请法院执行",
                    json.dumps(["行政法"], ensure_ascii=False), "file", "admin-context-hash",
                    "2026-01-01T00:00:00", "[]",
                ),
            )
            article_id = cur.lastrowid
            main.rebuild_article_paragraphs(conn, article_id, article_text)
            job_id, _ = lk.create_extraction_job(conn, article_id, force=True)
            lk.save_extraction_batch(conn, job_id, article_id, {
                "claims": [{
                    "issue_title": "行政机关申请法院强制执行的条件",
                    "statement": "没有强制执行权的行政机关应当申请人民法院强制执行。",
                    "claim_type": "rule", "confidence": 0.95,
                    "evidence": [{"paragraph_index": 1, "stance": "supports", "quote": article_text}],
                }],
            }, "test-model")
            conn.execute(
                """INSERT INTO case_manager_cases
                   (title,case_type,memo,created_at,updated_at) VALUES (?,?,?,?,?)""",
                ("示七某与李四执行案", "强制执行", "申请恢复执行并拍卖案涉房产。", "2026-01-01", "2026-01-01"),
            )
            case_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            conn.commit()
            admin_claim_id = int(conn.execute(
                "SELECT c.id FROM knowledge_claims c JOIN knowledge_claim_issues ci ON ci.claim_id=c.id JOIN knowledge_issues i ON i.id=ci.issue_id WHERE i.title=?",
                ("行政机关申请法院强制执行的条件",),
            ).fetchone()[0])
        self.client.post(f"/api/legal-knowledge/claims/{self.claim_id}/review", json={"action": "approve"})
        self.client.post(f"/api/legal-knowledge/claims/{admin_claim_id}/review", json={"action": "approve"})
        response = self.client.get(f"/api/legal-knowledge/home?case_id={case_id}")
        self.assertEqual(response.status_code, 200, response.text)
        related = response.json()["case_related"]
        self.assertIn(self.claim_id, {item["id"] for item in related})
        self.assertNotIn(admin_claim_id, {item["id"] for item in related})
        self.assertTrue(all(item["case_match_score"] >= 22 for item in related))

    def test_starred_feature_is_not_exposed(self):
        detail = self.client.get(f"/api/articles/{self.article_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertNotIn("starred", detail.json())

        listing = self.client.get("/api/articles?page=1&page_size=5")
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertTrue(listing.json()["articles"])
        self.assertNotIn("starred", listing.json()["articles"][0])

        stats = self.client.get("/api/stats")
        self.assertEqual(stats.status_code, 200, stats.text)
        self.assertNotIn("starred_count", stats.json())

        openapi_paths = self.client.get("/openapi.json").json()["paths"]
        self.assertNotIn("/api/articles/{article_id}/starred", openapi_paths)
        self.assertNotIn("/api/articles/starred", openapi_paths)


if __name__ == "__main__":
    unittest.main()
