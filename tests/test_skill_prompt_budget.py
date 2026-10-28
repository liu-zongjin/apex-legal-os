"""Anonymous regression coverage for persisted large Skills in AI chat."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
from backend import ai_context, skill_manager


class SkillPromptBudgetTests(unittest.TestCase):
    def test_basic_questions_do_not_read_a_task_skill(self):
        with patch.object(skill_manager, '_find_skill', side_effect=AssertionError('unrelated Skill was read')):
            for question in ('关于我你都知道什么', '你是什么模型？', '你对我了解多少'):
                self.assertEqual(skill_manager.load_skill_instruction('persisted-skill', question), '')

    def test_complete_core_is_retained_without_recursive_documents(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);core=root/'SKILL.md'
            text='workflow requirements\n'*1100+'FINAL_MANDATORY_RULE'
            core.write_text(text)
            (root/'references').mkdir();(root/'references'/'notes.md').write_text('UNREQUESTED_REFERENCE')
            (root/'assets').mkdir();(root/'assets'/'source.py').write_text('UNREQUESTED_SOURCE')
            with patch.object(skill_manager,'_find_skill',return_value=(core,{'source':'personal','name':'fixture'})):
                prompt=skill_manager.load_skill_instruction('fixture','画出案件时间轴')
        self.assertIn(text,prompt)
        self.assertNotIn('UNREQUESTED_REFERENCE',prompt);self.assertNotIn('UNREQUESTED_SOURCE',prompt)
        token=ai_context.CURRENT.set({'budget':ai_context.model_budget('deepseek-flash'),'items':[]})
        try:ai_context.guard_messages([{'content':prompt}],8000,model='deepseek-flash')
        finally:ai_context.CURRENT.reset(token)

    def test_oversized_core_is_rejected_without_silent_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            core=Path(directory)/'SKILL.md';core.write_text('规则'*10000)
            with patch.object(skill_manager,'_find_skill',return_value=(core,{'source':'personal'})):
                with self.assertRaises(HTTPException) as error:
                    skill_manager.load_skill_instruction('fixture','生成关系图')
        self.assertEqual(error.exception.status_code,413)

    def test_official_budget_and_deployment_override_are_separate_from_gateways(self):
        with patch.dict(os.environ,{'STELLA_AI_INPUT_BUDGETS':'{}'}):
            self.assertEqual(ai_context.model_budget('deepseek-flash'),800000)
            self.assertEqual(ai_context.model_budget('opencode:deepseek-flash'),24000)
            self.assertEqual(ai_context.model_budget('unknown'),24000)
        with patch.dict(os.environ,{'STELLA_AI_INPUT_BUDGETS':'{"deepseek-flash":12000}'}):
            self.assertEqual(ai_context.model_budget('deepseek-flash'),12000)
