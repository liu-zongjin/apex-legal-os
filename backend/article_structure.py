"""Conservative structure classification for imported Chinese legal articles.

The importer receives content from Word/PDF, browser ``innerText`` and highly
variable web HTML.  This module intentionally prefers a missed decorative
heading over turning a sentence or a statutory list item into a heading.
"""

from __future__ import annotations

import re


CN_NUM = r"一二三四五六七八九十百千零〇两\d"

META_PREFIX_RE = re.compile(
    r"^(?:发布时间|发布日期|来源|文章来源|作者|编辑|责任编辑|字号|浏览次数|点击数|阅读量)\s*[：:]"
)
CASE_NUMBER_RE = re.compile(
    r"^[（(]\d{4}[）)]\s*[^。！？]{0,50}(?:法|民|刑|行|执|商|知|赔|仲)[^。！？]{0,20}号$"
)
DATE_META_RE = re.compile(
    r"^[（(][^）)]{0,100}(?:通过|修正|修订|公布|施行|发布|批准)[^）)]{0,100}[）)]$"
)
STRUCTURAL_RE = re.compile(
    rf"^第[{CN_NUM}]+(?:分编|编|章|节|部分)(?:[\s\u3000　]*[^，；。！？]{{0,60}})?$"
)
ARTICLE_RE = re.compile(rf"^第[{CN_NUM}]+条(?:\s|　|$)")
PAREN_ENUM_RE = re.compile(rf"^[（(][{CN_NUM}]{{1,3}}[）)]")
DECIMAL_ENUM_RE = re.compile(r"^\d{1,3}(?:[.．、)）]|\.\d+)")
MAJOR_ENUM_RE = re.compile(rf"^[{CN_NUM}]+[、.．]\s*")

# “一、二审”中的顿号是并列词语的一部分，不是一级编号。
COMPOUND_EXPRESSION_RE = re.compile(
    rf"^[{CN_NUM}]{{1,3}}、[{CN_NUM}]{{1,3}}(?:审|次|项|条|款|人|个|级|类|方|部分|阶段|年度|月份|方面)"
)

LABELS = {
    "摘要", "内容提要", "关键词", "关键字", "前言", "引言", "序言", "编者按", "结语", "结论", "总结",
    "作者简介",
    "裁判要旨", "法院观点", "本院认为", "基本案情", "裁判理由", "裁判结果",
    "典型意义", "争议焦点", "案件焦点", "检察履职情况", "律师提示", "实务要点",
    "相关法条", "法条链接", "案例索引", "参考文献", "致谢",
}


def normalize_structure_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    text = text.replace("\xa0", " ").replace("\u3000", " ")
    return re.sub(r"\s+", " ", text).strip()


def _label_text(text: str) -> str:
    return text.strip("【】[] ").rstrip("：:").replace(" ", "")


def is_sentence_like(text: str) -> bool:
    """Whether a block reads like a sentence/list item instead of a title."""
    return bool(re.search(r"[，,；;。！？?!]", text))


def classify_article_block(
    value: str,
    *,
    source_tag: str = "",
    explicit_heading: bool = False,
    bold: bool = False,
) -> str:
    """Return a semantic body class, or ``""`` for an ordinary paragraph."""
    text = normalize_structure_text(value)
    if not text:
        return ""

    compact = re.sub(r"\s+", "", text)
    tag = (source_tag or "").lower()
    explicit = explicit_heading or tag in {"h1", "h2", "h3", "h4", "h5", "h6"}

    if META_PREFIX_RE.match(text) and len(text) <= 80:
        return "body-meta-line"
    if CASE_NUMBER_RE.match(compact) or DATE_META_RE.match(compact):
        return "body-document-meta"
    if re.match(r"^(?:中华人民共和国)?(?:最高人民法院|最高人民检察院|.+人民法院|.+人民检察院)$", compact) \
            or re.match(r"^(?:民事|刑事|行政)?(?:判决书|裁定书|决定书|调解书)$", compact):
        return "body-document-meta"

    label = _label_text(text)
    if label in LABELS:
        return "body-label-heading"
    if re.match(r"^【(?:关键词|关键字|要旨|裁判要旨|基本案情|裁判理由|裁判结果|典型意义|争议焦点|法院观点|律师提示|实务要点|相关法条|法条链接|案例索引)】", text):
        return "body-label-heading"

    if compact in {"目录", "目次"}:
        return "body-toc-heading"
    if STRUCTURAL_RE.match(text):
        return "body-heading" if re.match(rf"^第[{CN_NUM}]+(?:分编|编|章|部分)", text) else "body-heading-secondary"

    if re.match(r"^案例[一二三四五六七八九十百千\d]+.{4,80}(?:案|案例|纠纷|争议)$", text):
        return "body-heading-secondary"
    if re.match(r"^\d{1,3}[.．、]\s*.{4,145}(?:案|纠纷案|争议案)$", text):
        return "body-heading-secondary"

    # Statutory articles and fixed expressions are paragraphs, not headings.
    if ARTICLE_RE.match(text) or COMPOUND_EXPRESSION_RE.match(compact):
        return ""

    terminal_or_internal_punctuation = is_sentence_like(text)
    parenthesized = bool(PAREN_ENUM_RE.match(text))
    decimal = bool(DECIMAL_ENUM_RE.match(text))
    major = bool(MAJOR_ENUM_RE.match(text))

    # Parenthesized numbering is overwhelmingly a list item in statutes and
    # judgments.  Only an explicitly styled, short noun phrase may be a heading.
    if parenthesized or decimal:
        if explicit and len(text) <= 45 and not terminal_or_internal_punctuation:
            return "body-heading-secondary"
        return "body-list-item"

    if major:
        # 一级提纲标题常用逗号连接两个并列分句，例如“二、审查趋严，明确
        # 替代路径”。逗号在这里是标题内部的分隔符，不应像句号、分号或
        # 句末问叹号一样直接把整行降为正文；固定并列表达已在上方排除。
        if len(text) <= 50 and not re.search(r"[；;。！？?!]", text):
            return "body-heading"
        return ""

    # An actual HTML heading/bold line can carry a non-numbered title, but a
    # complete sentence remains body text even when the source made it bold.
    if explicit and len(text) <= 80 and not terminal_or_internal_punctuation:
        return "body-heading-secondary" if tag in {"h4", "h5", "h6"} else "body-heading"
    if bold and len(text) <= 45 and not terminal_or_internal_punctuation:
        return "body-heading"

    # 无编号的短名词短语也可能是网页小标题，但必须以稳定的标题中心词结尾。
    if (4 <= len(text) <= 28 and not terminal_or_internal_punctuation
            and re.search(
                r"(?:问题|规则|标准|条件|情形|关系|效力|责任|权利|义务|观点|要点|分析|认定|处理|程序|范围|主体|意见|建议|方法|路径|方案|意义|背景|焦点|争议|概述|解读|说明)$",
                text,
            )):
        return "body-heading-secondary"

    # Short field labels such as “审理法院：” are useful navigation labels.
    if len(text) <= 20 and re.match(r"^[\u4e00-\u9fffA-Za-z]{2,12}[：:]$", text):
        return "body-label-heading"
    return ""


def is_heading_class(class_name: str) -> bool:
    return class_name in {"body-heading", "body-heading-secondary", "body-label-heading"}
