"""Document wording backed by the same cause catalog as the form picker."""
from functools import lru_cache

import json
from pathlib import Path


@lru_cache(maxsize=1)
def _catalog_names(frontend_dir: Path) -> frozenset:
    data = json.loads((frontend_dir / "apex-cause-catalog.json").read_text(encoding="utf-8"))
    return frozenset(
        node["label"] for node in data["nodes"]
        if node["category"] != "criminal" or node.get("entry")
    )


def document_cause_label(value: str, frontend_dir: Path) -> str:
    label = (value or "").strip()
    if not label or label.endswith(("纠纷", "争议", "罪")):
        return label
    if label in _catalog_names(frontend_dir):
        return label
    return f"{label}纠纷"
