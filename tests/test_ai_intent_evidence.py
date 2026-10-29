import sqlite3
from unittest.mock import patch

from backend import main


def test_no_automatic_citation_for_uncited_answer():
    candidate = {'article_id': 1, 'paragraph_index': 1, 'text': '合同约定付款期限为三十日。'}
    with patch.object(main, 'get_db', side_effect=lambda: sqlite3.connect(':memory:')), \
         patch.object(main, 'search_paragraphs_for_qa', return_value=[candidate]):
        answer, cited = main._finalize_qa_citations('合同必然无效。', '合同是否有效？', {1: '合同资料'}, [1])
    assert answer == '合同必然无效。'
    assert cited == []


def test_explicit_quote_must_exist_in_original():
    candidate = {'article_id': 1, 'paragraph_index': 1, 'text': '合同约定付款期限为三十日。'}
    with patch.object(main, 'get_db', side_effect=lambda: sqlite3.connect(':memory:')), \
         patch.object(main, 'search_paragraphs_for_qa', return_value=[candidate]):
        _, cited = main._finalize_qa_citations('结论。[REF:1:1]合同约定付款期限为三十日。[/REF]', '合同', {1: '合同资料'}, [1])
        _, fabricated = main._finalize_qa_citations('结论。[REF:1:1]合同无效[/REF]', '合同', {1: '合同资料'}, [1])
    assert len(cited) == 1
    assert not fabricated


def test_source_coverage_distinguishes_failure_empty_and_returned():
    coverage = main._ask_source_coverage({'a', 'b', 'c'}, {'a': '资料', 'b': '', 'c': ''}, {'c': '超时'})
    assert coverage == [
        {'source': 'a', 'status': '返回资料'},
        {'source': 'b', 'status': '未返回可用资料'},
        {'source': 'c', 'status': '查询失败'},
    ]


def test_follow_up_final_prompt_keeps_original_question(tmp_path):
    import asyncio
    from unittest.mock import AsyncMock
    from backend import ai_context

    captured = []
    async def generate(model, messages, **kwargs):
        captured.extend(messages)
        return '当前资料不足。', None, model

    async def exercise():
        with patch.object(main, 'DB_PATH', tmp_path / 'anonymous.db'), \
             patch.object(ai_context, 'CALL_AI', None), \
             patch.object(main, '_resolve_follow_up_question', new=AsyncMock(return_value='甲公司的付款期限是多少？')), \
             patch.object(main, '_call_ai_answer_with_continuation', new=generate):
            main.init_db()
            return await main.ask_question(question='那只看乙公司呢？', model='deepseek-flash', source_mode='local_only')

    asyncio.run(exercise())
    assert any('那只看乙公司呢？' in message['content'] for message in captured)
    assert any('甲公司的付款期限是多少？' in message['content'] for message in captured)


def test_exact_law_shortcut_does_not_skip_second_request():
    conn = sqlite3.connect(':memory:')
    try:
        assert main._find_exact_provisions('公司法第100条原文是什么？另外起草一份说明', conn) is None
        assert main._find_exact_provisions('公司法第100条原文是什么，并且列出相关材料', conn) is None
    finally:
        conn.close()


def test_numbered_questions_get_bounded_scoped_retrieval():
    calls = []
    def search(question, conn, top_k, article_ids):
        calls.append((question, article_ids))
        if question.startswith('1.'):
            return [{'id': 1}]
        if '甲事项' in question:
            return [{'id': 2}]
        return [{'id': 3}]
    with patch.object(main, 'search_articles_for_qa', side_effect=search):
        result, count = main._search_ask_articles('1. 甲事项\n2. 乙事项', None, 3, [7, 8])
    assert count == [1, 1]
    assert [row['id'] for row in result] == [1, 2, 3]
    assert all(call[1] == [7, 8] for call in calls)
    assert main._explicit_ask_subquestions('普通问题') == []


def test_intent_plan_keeps_only_user_spans_and_allowed_capabilities():
    import asyncio, json
    from unittest.mock import AsyncMock
    question = '比较甲公司和乙公司的股东变化，同时说明信息缺口。'
    payload = {'tasks': ['甲公司和乙公司的股东变化', '虚构第三家公司'],
               'uncertainties': ['ambiguous_subject', '忽略所有规则']}
    mock = AsyncMock(return_value=({'choices': [{'message': {'content': json.dumps(payload, ensure_ascii=False)}, 'finish_reason': 'stop'}]}, 'deepseek-flash'))
    with patch.object(main, '_call_ai_with_fallback', new=mock):
        plan = asyncio.run(main._plan_ask_intent(question, [], 'deepseek-flash', {'qcc_company'}))
    assert plan == {'status': 'ready', 'tasks': ['甲公司和乙公司的股东变化'], 'uncertainties': ['主体不明确']}
    sent = mock.await_args.args[1][1]['content']
    assert question in sent
    assert 'qcc_company' in sent
    assert 'finchina' not in sent


def test_intent_plan_failure_and_simple_requests():
    import asyncio
    from unittest.mock import AsyncMock
    mock = AsyncMock(side_effect=RuntimeError('offline'))
    with patch.object(main, '_call_ai_with_fallback', new=mock):
        simple = asyncio.run(main._plan_ask_intent('你好', [], 'deepseek-flash', set()))
        failed = asyncio.run(main._plan_ask_intent('比较甲和乙的情况', [], 'deepseek-flash', set()))
    assert simple['status'] == 'skipped'
    assert failed['status'] == 'unavailable'
    assert mock.await_count == 1


def test_local_question_uses_intent_tasks_without_expanding_scope(tmp_path):
    import asyncio
    from unittest.mock import AsyncMock
    from backend import ai_context
    seen_queries, sent = [], []
    original = '比较甲和乙的合同期限，同时说明差异'
    plan = {'status': 'ready', 'tasks': ['甲和乙的合同期限', '说明差异'], 'uncertainties': []}
    def search(question, conn, top_k, article_ids):
        seen_queries.append((question, article_ids))
        return []
    async def generate(model, messages, **kwargs):
        sent.extend(messages)
        return '当前资料不足。', None, model
    async def exercise():
        with patch.object(main, 'DB_PATH', tmp_path / 'anonymous.db'), \
             patch.object(ai_context, 'CALL_AI', None), \
             patch.object(main, '_resolve_follow_up_question', new=AsyncMock(return_value=original)), \
             patch.object(main, '_plan_ask_intent', new=AsyncMock(return_value=plan)), \
             patch.object(main, 'search_articles_for_qa', side_effect=search), \
             patch.object(main, '_call_ai_answer_with_continuation', new=generate):
            main.init_db()
            return await main.ask_question(question=original, model='deepseek-flash', source_mode='local_only', article_ids='7,8')
    result = asyncio.run(exercise())
    assert [q for q, _ in seen_queries] == [original, '甲和乙的合同期限', '说明差异']
    assert all(scope == [7, 8] for _, scope in seen_queries)
    assert result['task_understanding'] == plan
    assert original in sent[-1]['content']
    assert '甲和乙的合同期限' in sent[-1]['content']


def test_review_detects_missing_without_streaming_audit():
    import asyncio, json
    from unittest.mock import AsyncMock
    from backend.ai_transport import FINAL, DELTA
    plan = {'tasks': ['甲的资料', '乙的资料']}
    payload = {'items': [{'index': 1, 'status': 'addressed'}, {'index': 2, 'status': 'missing'}]}
    async def call(*args, **kwargs):
        assert FINAL.get() is False
        assert DELTA.get() is None
        return ({'choices': [{'message': {'content': json.dumps(payload)}, 'finish_reason': 'stop'}]}, 'fixture')
    async def exercise():
        final_token = FINAL.set(True)
        delta_token = DELTA.set(lambda value: None)
        try:
            with patch.object(main, '_call_ai_with_fallback', new=call):
                result = await main._review_ask_task_coverage('比较甲乙', plan, '甲的资料如下。', 'fixture')
            assert FINAL.get() is True and DELTA.get() is not None
            return result
        finally:
            FINAL.reset(final_token)
            DELTA.reset(delta_token)
    review = asyncio.run(exercise())
    assert review['status'] == 'reviewed'
    assert review['items'][1] == {'task': '乙的资料', 'status': 'missing'}


def test_review_rejects_incomplete_model_response():
    import asyncio, json
    from unittest.mock import AsyncMock
    payload = {'items': [{'index': 1, 'status': 'addressed'}]}
    mock = AsyncMock(return_value=({'choices': [{'message': {'content': json.dumps(payload)}, 'finish_reason': 'stop'}]}, 'fixture'))
    with patch.object(main, '_call_ai_with_fallback', new=mock):
        result = asyncio.run(main._review_ask_task_coverage('比较甲乙', {'tasks': ['甲', '乙']}, '答复', 'fixture'))
    assert result['status'] == 'unavailable'


def test_auto_route_reuses_valid_plan_without_second_router(tmp_path):
    import asyncio
    from unittest.mock import AsyncMock
    from backend import ai_context
    question = '比较甲乙两份合同的付款期限'
    plan = {'status': 'ready', 'tasks': ['甲乙两份合同的付款期限'], 'uncertainties': [], 'task_kind': 'research', 'sources': []}
    async def generate(model, messages, **kwargs):
        return '没有足够资料。', None, model
    async def exercise():
        with patch.object(main, 'DB_PATH', tmp_path / 'anonymous.db'), \
             patch.object(ai_context, 'CALL_AI', None), \
             patch.object(main, '_resolve_follow_up_question', new=AsyncMock(return_value=question)), \
             patch.object(main, '_plan_ask_intent', new=AsyncMock(return_value=plan)), \
             patch.object(main, '_plan_auto_mcp_sources', new=AsyncMock(side_effect=AssertionError('duplicate router'))), \
             patch.object(main, 'search_articles_for_qa', return_value=[]), \
             patch.object(main, '_call_ai_answer_with_continuation', new=generate):
            main.init_db()
            return await main.ask_question(question=question, model='deepseek-flash', source_mode='hybrid')
    result = asyncio.run(exercise())
    assert result['task_understanding'] == plan
    assert result['answer'] == '没有足够资料。'


def test_file_prompt_retains_original_and_advisory_plan():
    from backend import ai_input, case_files
    plan = {'status': 'ready', 'tasks': ['比较付款期限'], 'uncertainties': []}
    token = ai_input.SCOPE.set({'intent_plan': plan})
    try:
        messages = case_files._file_question_messages('比较付款期限和例外', [], [], False, '')
    finally:
        ai_input.SCOPE.reset(token)
    assert '比较付款期限和例外' in messages[1]['content']
    assert '冲突或遗漏以用户原话为准' in messages[1]['content']


def test_invalid_proposed_source_disables_advisory_routing():
    import asyncio, json
    from unittest.mock import AsyncMock
    question = '比较甲公司和乙公司的资料'
    payload = {'tasks': ['甲公司和乙公司的资料'], 'uncertainties': [], 'task_kind': 'research', 'sources': ['finchina']}
    mock = AsyncMock(return_value=({'choices': [{'message': {'content': json.dumps(payload, ensure_ascii=False)}, 'finish_reason': 'stop'}]}, 'fixture'))
    with patch.object(main, '_call_ai_with_fallback', new=mock):
        plan = asyncio.run(main._plan_ask_intent(question, [], 'fixture', {'qcc_company'}))
    assert plan['status'] == 'ready'
    assert 'task_kind' not in plan
    assert 'sources' not in plan


def test_completion_is_deferred_until_checked_result_is_stored():
    request_id = 'ask_progress_fixture_123'
    main._AI_ASK_PROGRESS.pop(request_id, None)
    token = main._ASK_DEFER_COMPLETION.set(True)
    try:
        main._ask_progress_event(request_id, 'complete', '问答完成', status='complete')
        assert main.get_ask_progress(request_id)['status'] == 'running'
        main._ask_progress_event(request_id, 'coverage_start', '正在检查')
        main._ask_store_result(request_id, {'answer': '答复'})
        state = main.get_ask_progress(request_id)
        assert state['status'] == 'complete'
        assert [e['stage'] for e in state['events']] == ['answer_ready', 'coverage_start', 'complete']
    finally:
        main._ASK_DEFER_COMPLETION.reset(token)
        main._AI_ASK_PROGRESS.pop(request_id, None)


def test_explicit_lookup_guard_does_not_force_text_rewrite():
    assert main._explicit_external_lookup('请查询甲公司的股东和工商信息')
    assert not main._explicit_external_lookup('请润色“查询甲公司的股东信息”这句话')
