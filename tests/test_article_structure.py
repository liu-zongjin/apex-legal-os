from backend.article_structure import classify_article_block
from bs4 import BeautifulSoup

from backend.main import (
    _extract_weixin_html,
    _merge_pdf_page_text,
    _split_article_paragraphs,
    normalize_content,
    text_to_article_html,
)


def test_conservative_structure_classification():
    assert classify_article_block("第一章 总则") == "body-heading"
    assert classify_article_block("第二节 受理") == "body-heading-secondary"
    assert classify_article_block("裁判要旨") == "body-label-heading"
    assert classify_article_block("（2021）最高法民申5326号") == "body-document-meta"
    assert classify_article_block("一、二审法院据此认定存在垫付") == ""
    assert classify_article_block("（一）大型基础设施、公用事业等关系社会公共利益的项目；") == "body-list-item"
    assert classify_article_block("(1)对象广泛性。正文说明") == "body-list-item"
    assert classify_article_block("一、合同效力") == "body-heading"
    assert classify_article_block("（一）合同效力") == "body-list-item"
    assert classify_article_block("（一）合同效力", explicit_heading=True) == "body-heading-secondary"


def test_plain_text_html_uses_list_and_meta_classes():
    html = text_to_article_html(
        "第一章 总则\n（2021）最高法民申5326号\n（一）申请人基本情况；\n一、合同效力"
    )
    assert '<p class="body-heading">第一章 总则</p>' in html
    assert '<p class="body-document-meta">（2021）最高法民申5326号</p>' in html
    assert '<p class="body-list-item">（一）申请人基本情况；</p>' in html
    assert '<p class="body-heading">一、合同效力</p>' in html


def test_paragraph_index_does_not_use_list_item_as_heading_context():
    content = """
    <p class="body-heading">第一章 总则</p>
    <p>第一条 本法适用于相关活动。</p>
    <p class="body-list-item">（一）大型基础设施项目；</p>
    <p>前款项目应当依法办理审批手续。</p>
    """
    paragraphs = _split_article_paragraphs(content)
    assert paragraphs[-1]["heading"] == "第一章 总则"
    assert any(item["text"].startswith("（一）") for item in paragraphs)


def test_normalizer_preserves_source_boundaries_and_repairs_punctuation_fragment():
    raw = "一、二审法院据此认定\n，建工公司具有诉讼主体资格。\n\n公司公司治理规则"
    normalized = normalize_content(raw)
    assert "一、二审法院据此认定，建工公司具有诉讼主体资格。" in normalized
    assert "公司公司治理规则" in normalized


def test_pdf_line_merge_respects_structural_and_list_boundaries():
    merged, _ = _merge_pdf_page_text(
        "第一章 总则\n第一条 本法适用于相关活动。\n（一）第一类项目；\n（二）第二类项目。"
    )
    paragraphs = merged.split("\n\n")
    assert paragraphs[0] == "第一章 总则"
    assert paragraphs[1].startswith("第一条")
    assert paragraphs[2].startswith("（一）")
    assert paragraphs[3].startswith("（二）")


def test_weixin_bold_emphasis_is_not_automatically_a_heading():
    soup = BeautifulSoup(
        "<div>"
        "<section><strong>一、二审法院据此认定</strong><span>，该合同合法有效。</span></section>"
        "<p><strong>（一）大型基础设施、公用事业项目；</strong></p>"
        "<section><strong>一、合同效力</strong></section>"
        "</div>",
        "html.parser",
    )
    html = _extract_weixin_html(soup.div)
    assert "一、二审法院据此认定，该合同合法有效。" in html
    assert '<p class="body-list-item">（一）大型基础设施、公用事业项目；</p>' in html
    assert '<p class="body-heading">一、合同效力</p>' in html
