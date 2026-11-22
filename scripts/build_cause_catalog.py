"""Build the Stella cause catalog from the user's Markdown compilation."""
import argparse
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import re

CIVIL_URL = "https://www.court.gov.cn/zixun/xiangqing/484231.html"
NUMERALS = "一二三四五六七八九十百"


def civil_parts(label):
    """Split the final bracket group, leaving parentheses within names intact."""
    # This compilation uses enumeration commas both inside names and between entries.
    match = re.fullmatch(r"(.+?)（((?:[^（）]|（[^（）]*）)+)）", label)
    if not match:
        return label, []
    parent, group = match.groups()
    if "；" in group:
        children = group.split("；")
    else:
        children = re.split(r"(?<=纠纷)、|(?<=判决)、(?!裁定)|(?<=裁决)、|(?<=诉讼)、(?!仲裁)|(?<=之诉)、|、(?=申请)", group)
    return parent, children


def parse(source):
    nodes = []
    stack = []
    category = None

    def add(level, label, line, ordinal=None):
        del stack[level - 1:]
        assert len(stack) == level - 1, (line, label)
        node = dict(category=category, level=level, label=label, line=line,
                    parent=stack[-1]["id"] if stack else None)
        if ordinal:
            node["ordinal"] = ordinal
        key = json.dumps([category, *[p["label"] for p in stack], label], ensure_ascii=False)
        node["id"] = category + "-" + hashlib.sha256(key.encode()).hexdigest()[:20]
        stack.append(node)
        nodes.append(node)
        return node

    for line, raw in enumerate(source.splitlines(), 1):
        if raw.startswith(("# 一、民事", "# 二、行政", "# 三、刑事")):
            category = {"一": "civil", "二": "administrative", "三": "criminal"}[raw[2]]
            stack.clear()
        elif raw.startswith("# 四、"):
            break
        elif not category:
            continue
        elif raw.startswith("## "):
            label = re.sub(rf"^第[{NUMERALS}]+(?:部分|章)\s+|^一级案由：", "", raw[3:])
            add(1, label, line)
        elif raw.startswith("### "):
            label = re.sub(rf"^[{NUMERALS}]+、|^（[{NUMERALS}]+）|^第[{NUMERALS}]+节\s+", "", raw[4:])
            add(2, label, line)
        elif raw.startswith("- "):
            label = raw[2:].rstrip("。")
            if category == "criminal":
                add(2 if len(stack) < 2 or stack[1].get("entry") else 3, label, line)["entry"] = True
                continue
            item = re.fullmatch(r"\*\*(\d+)\.\*\* (.+)", label)
            if not item:
                raise ValueError(f"Unexpected item on line {line}")
            ordinal, label = item.groups()
            name, children = civil_parts(label) if category == "civil" else (label, [])
            add(3, name, line, int(ordinal))
            for child in children:
                add(4, child, line)
    return nodes


def validate(nodes):
    expected_counts = {
        ("civil", 1): 12, ("civil", 2): 59, ("civil", 3): 514, ("civil", 4): 470,
        ("administrative", 1): 1, ("administrative", 2): 22, ("administrative", 3): 140,
    }
    counts = Counter((node["category"], node["level"]) for node in nodes)
    assert all(counts[key] == value for key, value in expected_counts.items()), counts
    assert sum(bool(node.get("entry")) for node in nodes) == 483
    assert len({node["id"] for node in nodes}) == len(nodes), "Duplicate catalog ID"
    for category, expected in (("civil", 514), ("administrative", 140)):
        numbers = [n["ordinal"] for n in nodes if n["category"] == category and "ordinal" in n]
        assert numbers == list(range(1, expected + 1)), (category, numbers)


def official_fourth_levels(document):
    text = html.unescape(re.sub(r"<[^>]+>", "", document))
    civil = text[text.index("1.生命权、身体权、健康权纠纷"):text.rindex("514.执行分配方案异议之诉")]
    number = None
    entries = {}
    for line in civil.splitlines():
        line = line.strip()
        if match := re.fullmatch(r"(\d+)\.(.+)", line):
            number = int(match[1])
            entries[number] = [match[2]]
        elif match := re.fullmatch(r"（\d+）(.+)", line):
            entries[number].append(match[1])
    entries[514] = ["执行分配方案异议之诉"]
    assert list(entries) == list(range(1, 515))
    assert sum(len(row) - 1 for row in entries.values()) == 470
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--civil-html", type=Path, help="Local snapshot of the linked Supreme People's Court publication")
    parser.add_argument("--output", type=Path, default=Path("frontend/apex-cause-catalog.json"))
    args = parser.parse_args()
    raw = args.source.read_bytes()
    nodes = parse(raw.decode("utf-8-sig"))
    validate(nodes)
    counts = Counter(f'{n["category"]}:{n["level"]}' for n in nodes)
    issues = []
    if args.civil_html:
        official = official_fourth_levels(args.civil_html.read_text(encoding="utf-8"))
        children = {}
        for node in nodes:
            if node["category"] == "civil" and node["level"] == 4:
                children.setdefault(node["parent"], []).append(node["label"])
        for node in nodes:
            if node["category"] != "civil" or node["level"] != 3:
                continue
            uploaded = [node["label"], *children.get(node["id"], [])]
            published = official[node["ordinal"]]
            if uploaded != published:
                issues.append(dict(category="civil", line=node["line"], ordinal=node["ordinal"],
                                   uploaded=uploaded, published=published, url=CIVIL_URL))
    result = dict(source=dict(filename=args.source.name, asOf="2026-11-22",
                              sha256=hashlib.sha256(raw).hexdigest(), status="compilation",
                              references={"civil": [CIVIL_URL],
                                          "administrative": ["https://www.court.gov.cn/fabu/xiangqing/282681.html"],
                                          "criminal": ["https://www.court.gov.cn/fabu/xiangqing/288171.html",
                                                       "https://www.court.gov.cn/fabu/xiangqing/424452.html"]}),
                  counts=dict(counts),
                  civilReview=dict(status="compared" if args.civil_html else "pending", differences=issues),
                  reviewNotes=[
                      "行政目录按汇编列举范围收录，个案表述、开放类别及专门案由另按原文核对。",
                      "刑事罪名已核对收录计数，逐项法条对应和版本须按两高规范复核。",
                      "司法赔偿为独立体系，原汇编仅列来源，目录未收录。"
                  ])
    header = json.dumps(result, ensure_ascii=False, indent=2)
    rows = ",\n".join("    " + json.dumps(node, ensure_ascii=False) for node in nodes)
    output = header[:-2] + ',\n  "nodes": [\n' + rows + "\n  ]\n}\n"
    args.output.write_text(output, encoding="utf-8")
    print(dict(counts), f"{len(issues)} civil rows differ from the publication")


if __name__ == "__main__":
    main()
