"""Knowledge extraction and organization queue for one application runtime."""

from __future__ import annotations

import asyncio
import datetime
import json
import sqlite3
from typing import Callable, List, Optional

from fastapi import HTTPException

from .knowledge_issue_merges import _repair_legacy_knowledge_issue_merges
from .knowledge_relations import (
    LONG_ARTICLE_CHARS as RELATION_LONG_ARTICLE_CHARS,
    scan_article_rules as scan_article_relation_rules,
)
from .legal_knowledge import (
    add_heuristic_issue_suggestions,
    article_knowledge_domains,
    article_processing_text as knowledge_article_text,
    create_extraction_job,
    knowledge_category_rows,
    parse_model_json,
    save_category_taxonomy,
    save_extraction_batch,
    save_issue_organization_batch,
    split_paragraph_batches,
)


def _knowledge_extraction_prompt(article: dict, paragraphs: list[dict]) -> list[dict]:
    paragraph_text = "\n\n".join(
        f"[段落 {item['paragraph_index']}] {item.get('heading') or ''}\n{item.get('text') or ''}"
        for item in paragraphs
    )
    schema = {
        "claims": [{
            "domain": "必须从文章专业领域中选择最匹配的一项；没有专业领域则填综合法律",
            "issue_title": "一个明确、可复用的法律问题",
            "statement": "仅依据原文得出的单一规则或观点",
            "claim_type": "rule|exception|procedure|risk|practice",
            "conditions": "原文明示的适用事实条件，没有则为空字符串",
            "exceptions": "原文明示的例外，没有则为空字符串",
            "procedural_stage": "原文明示的程序阶段，没有则为空字符串",
            "jurisdiction": "原文明示的地域，没有则为空字符串",
            "court_level": "原文明示的法院层级，没有则为空字符串",
            "authority_type": "法律/司法解释/案例/会议纪要/文章/其他；无法判断则为空",
            "authority_level": "原文明示的效力层级，没有则为空字符串",
            "valid_from": "原文明示的生效日期，没有则为空字符串",
            "valid_to": "原文明示的失效日期，没有则为空字符串",
            "confidence": 0.0,
            "evidence": [{
                "paragraph_index": 1,
                "stance": "supports|opposes|limits|background",
                "quote": "必须从该段逐字连续复制不少于8个字",
            }],
        }]
    }
    return [
        {
            "role": "system",
            "content": (
                "你是严谨的中国法律知识整理员。只从给定段落提取与文章所属专业领域直接相关、"
                "可复用的中国法律知识。专业领域只能选择文章已有分类之一；文章没有分类时使用综合法律。"
                "不得使用模型记忆，不得补写原文没有的"
                "时间、地域、层级或适用条件。支持观点、反对观点、例外和限制必须拆成不同结论，"
                "不得揉成统一结论。每条结论必须至少有一项逐字引文；无直接依据就不要输出。"
                "只返回JSON对象，不要代码块或解释。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"【文章】{article.get('title') or ''}\n"
                f"【来源类型】{article.get('source_type') or ''}\n\n"
                f"【文章专业领域】{json.dumps(article_knowledge_domains(article), ensure_ascii=False)}\n\n"
                f"【可引用段落】\n{paragraph_text}\n\n"
                f"请严格按以下结构返回：\n{json.dumps(schema, ensure_ascii=False)}"
            ),
        },
    ]


def _knowledge_taxonomy_prompt(domain: str, issues: list[dict]) -> list[dict]:
    sample = "\n".join(f"#{item['id']} {item['title']}" for item in issues)
    schema = {
        "categories": [{
            "name": "主题大类",
            "description": "本类边界",
            "children": [{"name": "细分子类", "description": "与相邻子类的区别"}],
        }]
    }
    return [
        {
            "role": "system",
            "content": (
                "你是中国法律知识分类架构师。你的任务只是在一个既定法律领域内建立稳定、"
                "可复用的主题层级，不判断结论对错。分类必须互相区分、名称简短、能覆盖给定问题。"
                "只返回完整JSON对象，不要代码块或解释。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"法律领域：{domain}\n\n现有法律问题样本：\n{sample}\n\n"
                "请建立5至12个主题大类，每个大类包含2至10个细分子类。"
                "不得把具体案件名、法条号或单个问题直接作为分类名。分类总深度固定为两级。\n"
                f"严格按此结构返回：{json.dumps(schema, ensure_ascii=False)}"
            ),
        },
    ]


def _knowledge_assignment_prompt(
    domain: str, taxonomy: list[dict], issues: list[dict]
) -> list[dict]:
    issue_text = "\n".join(f"#{item['id']} {item['title']}" for item in issues)
    schema = {
        "assignments": [{
            "issue_id": 1,
            "category_path": ["主题大类", "细分子类"],
            "confidence": 0.0,
        }],
        "merge_groups": [{
            "issue_ids": [1, 2],
            "recommended_title": "建议保留的规范问题名称",
            "reason": "为什么疑似相同；若只是相关、上下位、一般与例外或正反观点则不要输出",
            "confidence": 0.0,
        }],
    }
    return [
        {
            "role": "system",
            "content": (
                "你是谨慎的中国法律知识整理员。为每个法律问题选择且只选择一个最具体的分类路径。"
                "你还可以提出疑似重复问题组，但必须严格：只有适用对象、法律关系、程序阶段和核心请求"
                "实质相同才可建议；一般规则与例外、正反观点、程序与实体、相邻但不同的问题绝不能合并。"
                "你只提出建议，系统不会自动合并。只返回完整JSON对象。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"法律领域：{domain}\n\n可选分类：\n"
                f"{json.dumps(taxonomy, ensure_ascii=False)}\n\n待整理问题：\n{issue_text}\n\n"
                f"严格按此结构返回：{json.dumps(schema, ensure_ascii=False)}"
            ),
        },
    ]


class KnowledgeJobs:
    def __init__(
        self,
        get_db: Callable[[], sqlite3.Connection],
        *,
        default_model: Callable[[], str],
        fallback_model: Callable[[], str],
        call_ai: Callable,
        rebuild_article_paragraphs: Callable,
    ):
        self.get_db = get_db
        self.default_model = default_model
        self.fallback_model = fallback_model
        self.call_ai = call_ai
        self.rebuild_article_paragraphs = rebuild_article_paragraphs
        self._task: Optional[asyncio.Task] = None
        self._wake_signal: Optional[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = None

    def notify(self) -> None:
        signal = self._wake_signal
        if signal is None:
            return  # Startup drains already-persisted jobs.
        loop, event = signal
        try:
            loop.call_soon_threadsafe(event.set)
        except RuntimeError:
            if not loop.is_closed():
                raise

    def _start_worker(self) -> None:
        if self._task is None or self._task.done():
            # Python 3.8 binds asyncio.Event to the loop at construction.
            event = asyncio.Event()
            self._wake_signal = (asyncio.get_running_loop(), event)
            self._task = asyncio.create_task(self._run(event))
        self.notify()

    def enqueue(self, article_id: int, trigger_type: str, force: bool = False) -> tuple[int, bool]:
        with self.get_db() as conn:
            try:
                job_id, created = create_extraction_job(
                    conn, article_id, trigger_type=trigger_type, model=self.default_model(), force=force
                )
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            conn.commit()
        self.notify()
        return job_id, created

    async def _run_extraction(self, job_id: int) -> None:
        with self.get_db() as conn:
            job = conn.execute("SELECT * FROM knowledge_extraction_jobs WHERE id=?", (job_id,)).fetchone()
            if not job or job["status"] not in {"queued", "running"}:
                return
            article = conn.execute("SELECT * FROM articles WHERE id=?", (job["article_id"],)).fetchone()
            if not article:
                conn.execute(
                    "UPDATE knowledge_extraction_jobs SET status='failed',error='文章不存在',completed_at=?,updated_at=? WHERE id=?",
                    (datetime.datetime.now().isoformat(), datetime.datetime.now().isoformat(), job_id),
                )
                conn.commit()
                return
            paragraphs = conn.execute(
                "SELECT * FROM article_paragraphs WHERE article_id=? ORDER BY paragraph_index", (article["id"],)
            ).fetchall()
            if not paragraphs:
                self.rebuild_article_paragraphs(conn, article["id"], article["content"] or "")
                paragraphs = conn.execute(
                    "SELECT * FROM article_paragraphs WHERE article_id=? ORDER BY paragraph_index", (article["id"],)
                ).fetchall()
            batches = split_paragraph_batches(paragraphs, 18000)
            now = datetime.datetime.now().isoformat()
            conn.execute(
                """UPDATE knowledge_extraction_jobs SET status='running',started_at=COALESCE(started_at,?),
               total_batches=?,error='',updated_at=? WHERE id=?""",
                (now, len(batches), now, job_id),
            )
            # 旧的未审核提取结果不再与新一轮结果混用；保留记录供审计查看。
            conn.execute(
                """UPDATE knowledge_claims SET review_status='rejected',reviewer_note='已由新一轮提取替代',updated_at=?
               WHERE review_status='pending' AND id IN (
                 SELECT DISTINCT c.id FROM knowledge_claims c
                 JOIN knowledge_claim_evidence e ON e.claim_id=c.id
                 WHERE e.article_id=? AND c.extraction_job_id<>?
               )""",
                (now, article["id"], job_id),
            )
            existing_extracted = conn.execute(
                "SELECT COUNT(*) FROM knowledge_claims WHERE extraction_job_id=?", (job_id,)
            ).fetchone()[0]
            conn.commit()
            article_dict = dict(article)

        warnings: list[str] = []
        extracted = int(existing_extracted or 0)
        actual_model = self.default_model()
        try:
            for batch_index, batch in enumerate(batches, 1):
                messages = _knowledge_extraction_prompt(article_dict, batch)
                answer, _reasoning, actual_model = await self.call_ai(
                    self.default_model(), messages, temperature=0.1, max_tokens=4000,
                    continuation_tokens=2000, max_continuations=1,
                )
                try:
                    data = parse_model_json(answer)
                except (ValueError, json.JSONDecodeError) as first_error:
                    # 结构化输出偶尔会在长批次中被截断；只重试当前批次一次，
                    # 不重复已经成功保存的其他批次。
                    repair_messages = messages + [
                        {"role": "assistant", "content": answer},
                        {
                            "role": "user",
                            "content": (
                                "上一份JSON无法解析（可能被截断或缺少逗号）。请重新从本批段落生成一份完整、"
                                "合法的JSON对象；减少结论数量以确保闭合，不要解释，不要使用代码块。"
                            ),
                        },
                    ]
                    repaired, _repair_reasoning, actual_model = await self.call_ai(
                        actual_model, repair_messages, temperature=0.0, max_tokens=5000,
                        continuation_tokens=1000, max_continuations=0,
                    )
                    try:
                        data = parse_model_json(repaired)
                        warnings.append(f"第{batch_index}批首次JSON无效，已自动重试：{first_error}")
                    except (ValueError, json.JSONDecodeError) as repair_error:
                        # 默认模型连续两次无法形成闭合 JSON 时，改用现有备用模型只处理当前批次。
                        # 这不改变日常模型选择，也不会重复已经成功保存的批次。
                        fallback_messages = messages + [{
                            "role": "user",
                            "content": (
                                "默认模型连续两次未能返回合法JSON。请只保留本批最重要且证据完整的结论，"
                                "最多输出6条，严格返回一个闭合的JSON对象，不要解释或使用代码块。"
                            ),
                        }]
                        fallback_answer, _fallback_reasoning, actual_model = await self.call_ai(
                            self.fallback_model(), fallback_messages, temperature=0.0, max_tokens=5000,
                            continuation_tokens=1000, max_continuations=0,
                        )
                        data = parse_model_json(fallback_answer)
                        warnings.append(
                            f"第{batch_index}批默认模型两次JSON无效，已切换备用模型："
                            f"{first_error}；{repair_error}"
                        )
                with self.get_db() as conn:
                    count, batch_warnings = save_extraction_batch(
                        conn, job_id, int(article_dict["id"]), data, actual_model
                    )
                    extracted += count
                    warnings.extend(batch_warnings)
                    conn.execute(
                        """UPDATE knowledge_extraction_jobs SET processed_batches=?,extracted_claims=?,
                       warnings_json=?,model=?,updated_at=? WHERE id=?""",
                        (
                            batch_index, extracted, json.dumps(warnings[-200:], ensure_ascii=False), actual_model,
                            datetime.datetime.now().isoformat(), job_id,
                        ),
                    )
                    conn.commit()
            with self.get_db() as conn:
                now = datetime.datetime.now().isoformat()
                conn.execute(
                    """UPDATE knowledge_extraction_jobs SET status='completed',processed_batches=total_batches,
                   extracted_claims=?,warnings_json=?,model=?,completed_at=?,updated_at=? WHERE id=?""",
                    (extracted, json.dumps(warnings[-200:], ensure_ascii=False), actual_model, now, now, job_id),
                )
                # Reuse the newly verified evidence as relationship candidates.  This
                # is local work and never causes a second model call.
                scan_article_relation_rules(conn, int(article_dict["id"]))
                conn.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            with self.get_db() as conn:
                now = datetime.datetime.now().isoformat()
                conn.execute(
                    """UPDATE knowledge_claims SET review_status='rejected',
                   reviewer_note='提取任务未完整完成，等待重新提取',updated_at=?
                   WHERE extraction_job_id=? AND review_status='pending'""",
                    (now, job_id),
                )
                conn.execute(
                    """UPDATE knowledge_extraction_jobs SET status='failed',error=?,warnings_json=?,
                   completed_at=?,updated_at=? WHERE id=?""",
                    (str(exc)[:1200], json.dumps(warnings[-200:], ensure_ascii=False), now, now, job_id),
                )
                conn.commit()

    async def _call_json(self, messages: list[dict], max_tokens: int = 5000) -> tuple[dict, str]:
        answer, _reasoning, actual_model = await self.call_ai(
            self.default_model(), messages, temperature=0.0, max_tokens=max_tokens,
            continuation_tokens=1200, max_continuations=1,
        )
        try:
            return parse_model_json(answer), actual_model
        except (ValueError, json.JSONDecodeError):
            repair = messages + [
                {"role": "assistant", "content": answer},
                {"role": "user", "content": "上一份JSON不完整。请减少内容并重新返回一个合法闭合的JSON对象，不要解释。"},
            ]
            fixed, _reasoning, actual_model = await self.call_ai(
                actual_model, repair, temperature=0.0, max_tokens=max_tokens,
                continuation_tokens=800, max_continuations=0,
            )
            return parse_model_json(fixed), actual_model


    async def _run_organization(self, job_id: int) -> None:
        warnings: list[str] = []
        actual_model = self.default_model()
        try:
            with self.get_db() as conn:
                job = conn.execute(
                    "SELECT * FROM knowledge_organization_jobs WHERE id=?", (job_id,)
                ).fetchone()
                if not job or job["status"] not in {"queued", "running"}:
                    return
                domain = job["domain"]
                issues = [dict(row) for row in conn.execute(
                    """SELECT id,title FROM knowledge_issues
                   WHERE domain=? AND status='active' ORDER BY title,id""", (domain,)
                ).fetchall()]
                if not issues:
                    raise ValueError("当前领域没有可整理的法律问题")
                batches = [issues[index:index + 60] for index in range(0, len(issues), 60)]
                now = datetime.datetime.now().isoformat()
                conn.execute(
                    """UPDATE knowledge_organization_jobs SET status='running',started_at=COALESCE(started_at,?),
                   total_issues=?,total_batches=?,error='',updated_at=? WHERE id=?""",
                    (now, len(issues), len(batches), now, job_id),
                )
                conn.commit()

            with self.get_db() as conn:
                existing_categories = knowledge_category_rows(conn, domain)
            if existing_categories:
                majors = [item for item in existing_categories if not item["parent_id"]]
                taxonomy = [{
                    "name": major["name"],
                    "description": major.get("description") or "",
                    "children": [
                        {"name": child["name"], "description": child.get("description") or ""}
                        for child in existing_categories if child["parent_id"] == major["id"]
                    ],
                } for major in majors]
                category_paths = {}
                for major in majors:
                    category_paths[(major["name"], "")] = int(major["id"])
                    for child in existing_categories:
                        if child["parent_id"] == major["id"]:
                            category_paths[(major["name"], child["name"])] = int(child["id"])
            else:
                # Spread the sample across the alphabetically sorted domain instead of only using newest records.
                stride = max(1, len(issues) // 180)
                sample = issues[::stride][:180]
                taxonomy_data, actual_model = await self._call_json(
                    _knowledge_taxonomy_prompt(domain, sample), max_tokens=4500
                )
                taxonomy = taxonomy_data.get("categories") or []
                if not isinstance(taxonomy, list) or not taxonomy:
                    raise ValueError("AI未形成可用的分类结构")
                with self.get_db() as conn:
                    category_paths = save_category_taxonomy(conn, domain, taxonomy, "ai")
                    conn.commit()
            if not category_paths:
                raise ValueError("分类结构为空")

            assigned_total = 0
            suggested_total = 0
            for batch_index, batch in enumerate(batches, 1):
                data, actual_model = await self._call_json(
                    _knowledge_assignment_prompt(domain, taxonomy, batch), max_tokens=6000
                )
                with self.get_db() as conn:
                    assigned, suggested, batch_warnings = save_issue_organization_batch(
                        conn, domain, data, category_paths,
                        {int(item["id"]) for item in batch}, actual_model,
                    )
                    assigned_total += assigned
                    suggested_total += suggested
                    warnings.extend(batch_warnings)
                    conn.execute(
                        """UPDATE knowledge_organization_jobs SET processed_batches=?,assigned_issues=?,
                       suggestion_count=?,warnings_json=?,model=?,updated_at=? WHERE id=?""",
                        (
                            batch_index, assigned_total, suggested_total,
                            json.dumps(warnings[-100:], ensure_ascii=False), actual_model,
                            datetime.datetime.now().isoformat(), job_id,
                        ),
                    )
                    conn.commit()
            with self.get_db() as conn:
                suggested_total += add_heuristic_issue_suggestions(conn, domain)
                now = datetime.datetime.now().isoformat()
                conn.execute(
                    """UPDATE knowledge_organization_jobs SET status='completed',processed_batches=total_batches,
                   assigned_issues=?,suggestion_count=?,warnings_json=?,model=?,completed_at=?,updated_at=?
                   WHERE id=?""",
                    (
                        assigned_total, suggested_total, json.dumps(warnings[-100:], ensure_ascii=False),
                        actual_model, now, now, job_id,
                    ),
                )
                conn.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            with self.get_db() as conn:
                now = datetime.datetime.now().isoformat()
                conn.execute(
                    """UPDATE knowledge_organization_jobs SET status='failed',error=?,warnings_json=?,
                   completed_at=?,updated_at=? WHERE id=?""",
                    (str(exc)[:1200], json.dumps(warnings[-100:], ensure_ascii=False), now, now, job_id),
                )
                conn.commit()


    async def _run(self, event: asyncio.Event) -> None:
        while True:
            await event.wait()
            event.clear()
            while True:
                with self.get_db() as conn:
                    organization_job = conn.execute(
                        "SELECT id FROM knowledge_organization_jobs WHERE status='queued' ORDER BY id LIMIT 1"
                    ).fetchone()
                    queued_jobs = conn.execute(
                        """SELECT j.id,j.content_hash,a.content,s.ai_authorized_hash
                       FROM knowledge_extraction_jobs j
                       JOIN articles a ON a.id=j.article_id
                       LEFT JOIN article_relation_state s ON s.article_id=j.article_id
                       WHERE j.status='queued' ORDER BY j.id"""
                    ).fetchall()
                    extraction_job = next(
                        (
                            row for row in queued_jobs
                            if len(knowledge_article_text(row["content"] or "")) < RELATION_LONG_ARTICLE_CHARS
                            or (row["ai_authorized_hash"] or "") == row["content_hash"]
                        ),
                        None,
                    )
                if organization_job:
                    await self._run_organization(int(organization_job["id"]))
                    continue
                if not extraction_job:
                    break
                await self._run_extraction(int(extraction_job["id"]))

    async def stop_selected(self, article_ids: List[int], exclude: bool) -> dict:
        """Stop selected queued/running articles and optionally persist an exclusion."""
        selected = sorted({int(value) for value in article_ids if int(value) > 0})
        worker_was_active = bool(self._task and not self._task.done())
        if not selected:
            raise HTTPException(status_code=400, detail="请至少选择一篇文章")
        placeholders = ",".join("?" for _ in selected)
        with self.get_db() as conn:
            existing = {
                int(row[0]) for row in conn.execute(
                    f"SELECT id FROM articles WHERE id IN ({placeholders})", selected
                ).fetchall()
            }
            missing = [article_id for article_id in selected if article_id not in existing]
            if missing:
                raise HTTPException(status_code=404, detail=f"文章不存在：{missing[0]}")
            now = datetime.datetime.now().isoformat()
            if exclude:
                conn.executemany(
                    """INSERT INTO knowledge_extraction_exclusions(article_id,reason,created_at,updated_at)
                   VALUES (?,'用户选择跳过AI提取',?,?)
                   ON CONFLICT(article_id) DO UPDATE SET reason=excluded.reason,updated_at=excluded.updated_at""",
                    [(article_id, now, now) for article_id in selected],
                )
            queued_count = int(conn.execute(
                f"SELECT COUNT(*) FROM knowledge_extraction_jobs WHERE status='queued' AND article_id IN ({placeholders})",
                selected,
            ).fetchone()[0])
            running_rows = conn.execute(
                f"SELECT id,article_id FROM knowledge_extraction_jobs WHERE status='running' AND article_id IN ({placeholders})",
                selected,
            ).fetchall()
            conn.execute(
                f"""UPDATE knowledge_extraction_jobs SET status='cancelled',
                error=?,completed_at=?,updated_at=?
                WHERE status='queued' AND article_id IN ({placeholders})""",
                ("用户选择跳过本文" if exclude else "用户停止了本文处理", now, now, *selected),
            )
            if running_rows:
                running_job_ids = [int(row["id"]) for row in running_rows]
                running_placeholders = ",".join("?" for _ in running_job_ids)
                conn.execute(
                    f"UPDATE knowledge_extraction_jobs SET status='cancelling',error='正在停止AI提取',updated_at=? WHERE id IN ({running_placeholders})",
                    (now, *running_job_ids),
                )
            conn.commit()

        # The worker is serial, so cancelling it interrupts the one active model request.
        # A fresh worker then continues with the next queued article.
        if running_rows and worker_was_active:
            try:
                await self.stop()
            except Exception:
                pass
        with self.get_db() as conn:
            now = datetime.datetime.now().isoformat()
            conn.execute(
                f"""UPDATE knowledge_extraction_jobs SET status='cancelled',
                error=?,completed_at=?,updated_at=?
                WHERE status='cancelling' AND article_id IN ({placeholders})""",
                ("用户选择跳过本文" if exclude else "用户停止了本文处理", now, now, *selected),
            )
            conn.execute(
                f"""UPDATE knowledge_claims SET review_status='rejected',
                reviewer_note='提取被用户中止，未完成的结果不进入知识库',updated_at=?
                WHERE review_status='pending' AND extraction_job_id IN (
                    SELECT id FROM knowledge_extraction_jobs
                    WHERE status='cancelled' AND article_id IN ({placeholders})
                )""",
                (now, *selected),
            )
            conn.commit()
        if running_rows and worker_was_active:
            self._start_worker()
        return {
            "success": True,
            "selected_count": len(selected),
            "queued_stopped": queued_count,
            "running_stopped": len(running_rows),
            "excluded": exclude,
        }

    async def start(self) -> None:
        with self.get_db() as conn:
            marker = 'knowledge-issue-merges-v1'
            if not conn.execute('SELECT 1 FROM case_manager_maintenance WHERE key=?', (marker,)).fetchone():
                _repair_legacy_knowledge_issue_merges(conn)
                conn.execute('INSERT OR IGNORE INTO case_manager_maintenance(key) VALUES(?)', (marker,))
            # 上次退出时正在运行的任务恢复到队列；结果表有批次内去重保护。
            conn.execute(
                """UPDATE knowledge_organization_jobs SET status='queued',started_at=NULL,
               error=CASE WHEN error='' THEN '服务重启后自动恢复' ELSE error END,
               updated_at=? WHERE status='running'""",
                (datetime.datetime.now().isoformat(),),
            )
            conn.execute(
                """UPDATE knowledge_extraction_jobs SET status='queued',started_at=NULL,
               error=CASE WHEN error='' THEN '服务重启后自动恢复' ELSE error END,
               updated_at=? WHERE status='running'""",
                (datetime.datetime.now().isoformat(),),
            )
            conn.execute(
                """UPDATE knowledge_extraction_jobs SET status='cancelled',
               error='用户停止了本文处理',completed_at=?,updated_at=? WHERE status='cancelling'""",
                (datetime.datetime.now().isoformat(), datetime.datetime.now().isoformat()),
            )
            conn.commit()
        self._start_worker()

    async def stop(self) -> None:
        self._wake_signal = None
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
