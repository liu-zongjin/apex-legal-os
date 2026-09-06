import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "docs" / "architecture" / "shared-capabilities.json"


class SharedCapabilityRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(REGISTRY.read_text(encoding="utf-8"))

    def test_capability_ids_are_unique(self):
        ids = [item["id"] for item in self.payload["capabilities"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_explicit_paths_exist(self):
        for item in self.payload["capabilities"]:
            for key in ("source", "consumers", "tests"):
                for value in item[key]:
                    if "*" not in value:
                        self.assertTrue((ROOT / value).exists(), f"{item['id']}: {value}")

    def test_shared_capabilities_document_compatibility(self):
        for item in self.payload["capabilities"]:
            self.assertTrue(item.get("compatibility"), item["id"])


if __name__ == "__main__":
    unittest.main()

