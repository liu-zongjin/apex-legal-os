import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import ai_config


class AiModelMigrationTests(unittest.TestCase):
    def test_v4_flash_preferences_migrate_to_v4_1_flash(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            preferences_path = Path(temporary_directory) / "local_ai_prefs.json"
            preferences_path.write_text(json.dumps({
                "default_model": "opencode:deepseek-v4-flash",
                "hidden_models": ["deepseek-v4-flash"],
                "purpose_models": {"summary": "opencode:deepseek-v4-flash"},
            }), encoding="utf-8")
            with patch.object(ai_config, "AI_PREFS_PATH", preferences_path):
                preferences = ai_config.load_ai_prefs()

        self.assertEqual(preferences["default_model"], "opencode:deepseek-flash")
        self.assertEqual(preferences["hidden_models"], ["deepseek-flash"])
        self.assertEqual(preferences["purpose_models"]["summary"], "opencode:deepseek-flash")

    def test_catalog_uses_the_v4_1_flash_gateway_model(self):
        official_models = dict(ai_config.ask_models("deepseek"))
        self.assertEqual(official_models["deepseek-flash"], "DeepSeek V4.1 Flash 1017")
        models = dict(ai_config.ask_models("opencode"))
        self.assertEqual(models["opencode:deepseek-flash"], "OpenCode Go·DeepSeek V4.1 Flash")
        self.assertNotIn("opencode:deepseek-v4-flash", models)


if __name__ == "__main__":
    unittest.main()
