import copy
import sqlite3
import unittest

from backend.ai_strategy import (
    DEFAULT_STRATEGY,
    active_strategy,
    activate_as_new_version,
    classify_question,
    create_and_activate,
    ensure_schema,
    list_versions,
    simulate,
    validate_config,
)


class AIStrategyTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        ensure_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_default_strategy_and_classification(self):
        active = active_strategy(self.conn)
        self.assertEqual(active["version_label"], "系统默认 v1.0")
        result = classify_question("请检索相关裁判案例并列出裁判要旨", active["config"])
        self.assertTrue(result["case_intent"])
        self.assertIn("案例", result["case_hits"])
        self.assertEqual(result["route"], "案例任务")

    def test_validation_blocks_code_and_invalid_budget(self):
        config = copy.deepcopy(DEFAULT_STRATEGY)
        config["generation"]["additional_instruction"] = "执行 os.system('x')"
        config["retrieval"]["case_per_article_limit"] = 20000
        config["retrieval"]["case_total_budget"] = 10000
        result = validate_config(config)
        self.assertFalse(result["valid"])
        paths = {item["path"] for item in result["errors"]}
        self.assertIn("generation.additional_instruction", paths)
        self.assertIn("retrieval.case_per_article_limit", paths)

    def test_save_is_immediate_and_has_optimistic_lock(self):
        original = active_strategy(self.conn)
        config = copy.deepcopy(original["config"])
        config["classification"]["case_keywords"].append("争议焦点")
        saved = create_and_activate(self.conn, config, "补充案例关键词", original["id"])
        self.assertTrue(saved["valid"])
        self.assertEqual(active_strategy(self.conn)["id"], saved["strategy"]["id"])
        with self.assertRaises(ValueError):
            create_and_activate(self.conn, config, "过期页面保存", original["id"])

    def test_restore_creates_new_version(self):
        system = active_strategy(self.conn)
        config = copy.deepcopy(system["config"])
        config["retrieval"]["ordinary_top_k"] = 12
        custom = create_and_activate(self.conn, config, "减少召回", system["id"])["strategy"]
        restored = activate_as_new_version(self.conn, system["id"])["strategy"]
        self.assertGreater(restored["id"], custom["id"])
        self.assertEqual(restored["config"]["retrieval"]["ordinary_top_k"], DEFAULT_STRATEGY["retrieval"]["ordinary_top_k"])
        self.assertEqual(len(list_versions(self.conn)), 3)

    def test_simulation_never_performs_external_calls(self):
        result = simulate("查询某公司开票信息和失信记录", copy.deepcopy(DEFAULT_STRATEGY))
        self.assertFalse(result["external_calls_performed"])
        self.assertTrue({"qcc_company", "qcc_risk"}.issubset(result["proposed_mcp_sources"]))

    def test_locked_security_cannot_be_overridden(self):
        config = copy.deepcopy(DEFAULT_STRATEGY)
        config["locked_security"]["never_fabricate_source_text"] = False
        result = validate_config(config)
        self.assertTrue(result["valid"])
        self.assertTrue(result["normalized_config"]["locked_security"]["never_fabricate_source_text"])


if __name__ == "__main__":
    unittest.main()
