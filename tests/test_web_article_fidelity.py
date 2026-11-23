"""Import regression fixtures reconstructed from the reported WeChat layout."""

from pathlib import Path
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup

from tests.test_weixin_image_import import scope, requests
from backend.web_article_html import extract_web_article_html

FIXTURE = Path(__file__).parent / "fixtures/weixin-article-fidelity.html"
URL = "https://mp.weixin.qq.com/s/anonymous"


def import_fixture(url=URL, html=None):
    text = FIXTURE.read_text() if html is None else html
    response = Mock(text=text, content=text.encode(), headers={"content-type": "text/html"},
                    apparent_encoding="utf-8", url=url)
    with patch.object(requests, "get", return_value=response):
        return scope["fetch_webpage"](url)


def test_wechat_import_preserves_structure_and_visual_styles():
    article = import_fixture()
    root = BeautifulSoup(article["content"], "html.parser").select_one(".body-web-import")
    assert article["title"] == "匿名公司回购实务笔记"
    entries = root.select(".body-web-toc-entry")
    assert len(entries) == 6
    assert entries[2].get_text() == "三交易条款的效力与履行"
    assert "color:#104f85" in entries[2].strong["style"]
    assert "border:1px solid #afccef" in entries[0].find_parent(class_="body-web-toc")["style"]
    main, sub = root.h2, root.h3
    assert "background:#ecf5ff" in main.parent["style"] and "display:flex" in main["style"]
    assert main.span.get_text() == "一"
    assert "border-left:3px solid #2869b8" in sub.parent["style"]
    assert len(root.find_all("h2")) == 6
    assert root.ol["start"] == "3" and root.ol.find("li", value="6").ul
    assert root.blockquote.p.get_text() == "同一术语在全文应保持一致。"
    assert root.figure.figcaption and root.img["src"] == "https://mp.weixin.qq.com/sample.png"
    assert root.img["width"] == "180" and root.table.th["colspan"] == "2"
    assert root.select_one('[href="#web-source-1"]') and root.select_one('[data-web-anchor="web-source-1"]')
    assert root.select_one('[href="https://mp.weixin.qq.com/s/reference"]')
    assert "核对合同约定与履行条件。重点审查价款" in scope["html_to_processing_text"](article["content"])
    assert "推荐内容" not in root.get_text()
    assert root.select_one("p strong").get_text() == "目录"
    assert root.select_one("p br")


def test_general_web_uses_same_safe_html_and_preserves_repeated_content():
    article = import_fixture("https://example.com/news/article", """
    <title>参考手册</title>
    <main><header>站点导航</header><article><h1>参考手册</h1>
    <nav aria-label="Table of contents"><ol start="2">
    <li><a href="#second">Application</a></li><li><a href="#third">Scope</a></li>
    </ol></nav>
    <h2 id="second">Application</h2><p>This part explains <em>how</em> to apply the policy.</p>
    <p>This sentence is repeated deliberately.</p><p>This sentence is repeated deliberately.</p>
    <h2 id="third">Scope</h2><p>Additional context.</p></article></main>
    """)
    content = BeautifulSoup(article["content"], "html.parser")
    assert content.h1.get_text() == "参考手册"
    assert content.em.get_text() == "how"
    assert len(content.select(".body-web-toc li.body-web-toc-entry a")) == 2
    assert content.get_text().count("This sentence is repeated deliberately.") == 2
    assert "站点导航" not in content.get_text()


def test_import_only_reemits_allowed_markup_urls_and_styles():
    source = BeautifulSoup("""
    <article><p style="color:rgb(15, 32, 51);background:url(https://example.invalid/pixel);
      position:fixed;z-index:90;margin:-100px;line-height:1.8" onclick="ignored">
      <strong>正常内容</strong><custom><b>也是正文</b></custom>
      <a href="javascript:ignored">无效链接</a>
      <img src="data:image/svg+xml;base64,AAAA">
      <img src="../image.png" onerror="ignored"><iframe src="/frame"></iframe>
      <span hidden>隐藏文字</span><span style="display:none!important">隐藏文字</span>
      <svg><text>装饰图</text></svg><style>样式表</style>
      </p></article>
    """, "html.parser")
    doc = BeautifulSoup(extract_web_article_html(source.article, "https://example.com/docs/page"), "html.parser")
    assert doc.p["style"] == "color:rgb(15, 32, 51);line-height:1.8"
    assert doc.b.get_text() == "也是正文"
    assert len(doc.find_all("img")) == 1 and doc.img["src"] == "https://example.com/image.png"
    assert "href" not in doc.a.attrs and "onclick" not in doc.p.attrs and "onerror" not in doc.img.attrs
    assert not doc.find(["iframe", "svg", "style", "custom"])
    assert "隐藏文字" not in doc.get_text()
