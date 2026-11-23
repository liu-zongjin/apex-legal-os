"""Exercise imported article fidelity in the shipped Stella reader and editor.

Run from the repository root with python -m tests.web_article_fidelity_browser.
"""

import argparse
import asyncio
import json
import mimetypes
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from tests.test_web_article_fidelity import FIXTURE, import_fixture, URL

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
ORIGIN = "http://127.0.0.1:17882"


async def verify_dynamic_wechat_import(launch):
    from backend import main

    async def launch_fixture(chromium):
        browser = await chromium.launch(**launch)
        new_context = browser.new_context

        async def local_context(**options):
            context = await new_context(**options)

            async def respond(route):
                if route.request.url == URL:
                    # Simulate WeChat showing its initially hidden article after load.
                    html = FIXTURE.read_text().replace("display:none;font-size", "font-size")
                    await route.fulfill(content_type="text/html; charset=utf-8", body=html)
                else:
                    await route.abort()

            await context.route("**/*", respond)
            return context

        browser.new_context = local_context
        return browser

    with patch.object(main, "_launch_weixin_browser", new=launch_fixture):
        result = await main.fetch_weixin_article_async(URL)
    assert result["title"] == "匿名公司回购实务笔记"
    assert result["directory_rows"] == [["材料", "交易合同"]]
    assert result["content"].count("body-web-toc-entry") == 6
    assert "border-left:3px solid #2869b8" in result["content"]
    assert "font-size:15px;line-height:1.9" in result["content"]


def run(browser, screenshots, baseline, baseline_frontend):
    article = dict(import_fixture(), id=1, source_type="url", source_url=URL, tags=[],
                   domains=[], summary="", created_at="2026-01-01")
    context = browser.new_context(viewport={"width": 1600, "height": 900}, service_workers="block",
                                  reduced_motion="reduce")
    page = context.new_page()
    saves = []
    frontend = FRONTEND

    def route_request(route):
        path = route.request.url[len(ORIGIN):].split("?")[0]
        if path == "/" or path.startswith("/static/"):
            target = frontend / ("index.html" if path == "/" else path[len("/static/"):])
            if target.is_file():
                return route.fulfill(path=target, content_type=mimetypes.guess_type(target)[0])
            return route.fulfill(status=404, body="")
        data = {}
        if path == "/api/articles/1":
            data = article
        if path == "/api/notes/1":
            data = []
        if path == "/api/articles/1/editor":
            data = json.loads(route.request.post_data)
            assert data["base_content"] == article["content"]
            article.update(title=data["title"], content=data["content"])
            saves.append(article["content"])
        return route.fulfill(json=data)

    page.route(ORIGIN + "/**", route_request)
    page.route("**/*", lambda route: route.fallback() if route.request.url.startswith(ORIGIN) else route.abort())
    page.goto(ORIGIN)
    page.evaluate("openArticleInTab(1, '匿名公司回购实务笔记')")
    body = page.locator(".tab-article-body-text").first
    web = body.locator(".body-web-import")
    web.locator("h2").first.wait_for()
    assert web.evaluate("""root => {
        const outer = root.firstElementChild;
        const inner = outer.firstElementChild;
        const width = root.getBoundingClientRect().width;
        return width > 680
            && Math.abs(outer.getBoundingClientRect().width - width) <= 1
            && Math.abs(inner.getBoundingClientRect().width - width) <= 1
            && root.querySelector('figure').getBoundingClientRect().width === 240;
    }"""), "reader must fill its paper without widening the figure"
    entries = web.locator(".body-web-toc-entry")
    assert entries.count() == 6
    assert entries.nth(2).locator("strong").evaluate("(el) => getComputedStyle(el).color") == "rgb(16, 79, 133)"
    assert web.locator(".body-web-toc").evaluate("(el) => getComputedStyle(el).borderTopWidth") == "1px"
    assert web.locator("h2").first.evaluate("(el) => getComputedStyle(el.parentElement).backgroundColor") == "rgb(236, 245, 255)"
    assert web.locator("h3").evaluate("(el) => getComputedStyle(el.parentElement).borderLeftWidth") == "3px"
    assert body.locator("p:has(br)").first.evaluate("(el) => [getComputedStyle(el).textIndent,getComputedStyle(el).marginBottom]") == ["0px", "24px"]
    sidebar = page.locator(".sidebar-toc-link")
    assert sidebar.count() == 7
    assert sum("交易条款的效力与履行" in label for label in sidebar.all_text_contents()) == 1
    assert page.evaluate("(html) => renderBodyContentWithToc(html).toc.map(x => x.level)", article["content"]) == [1, 2, 1, 1, 1, 1, 1]
    if screenshots:
        page.screenshot(path=screenshots / "reader-after.png")

    entries.nth(2).get_by_role("link").click()
    flash = web.locator("h2.body-toc-target-flash")
    assert "交易条款的效力与履行" in flash.inner_text()
    web.get_by_role("link", name="查看条款小节").click()
    assert web.locator('[data-web-anchor="web-source-1"].body-toc-target-flash').count() == 1
    page.evaluate("document.body.classList.add('dark-mode')")
    assert web.evaluate("(el) => getComputedStyle(el).backgroundColor") == "rgb(255, 255, 255)"
    page.set_viewport_size({"width": 430, "height": 760})
    assert web.evaluate("(el) => el.scrollWidth <= el.clientWidth + 1")
    page.set_viewport_size({"width": 1440, "height": 900})
    page.evaluate("document.body.classList.remove('dark-mode')")

    page.evaluate("article => enableEditBody(article)", article)
    editor = page.locator("#body-editor .body-web-import")
    editor.locator("h3").wait_for()
    assert editor.evaluate("(el) => el.firstElementChild.style.maxWidth") == "680px"
    assert editor.locator(".body-web-reader-column").count() == 0
    assert editor.locator("ol").get_attribute("start") == "3"
    assert editor.locator("ol").get_attribute("type") == "A"
    assert editor.locator(".body-web-toc-entry a").count() == 0
    editor.locator("p").last.evaluate("(el) => el.append('补记。')")
    assert page.evaluate("saveBody()")
    assert len(saves) == 1 and "补记。" in saves[0] and 'data-article-toc-target' not in saves[0]
    assert "680px" in saves[0] and "body-web-reader-column" not in saves[0]
    page.reload()
    page.evaluate("openArticleInTab(1, '匿名公司回购实务笔记')")
    assert web.locator(".body-web-toc-entry").count() == 6
    assert web.locator("tr").count() == 2

    # Existing flattened imports retain text and suppress matching TOC rows.
    legacy = ('<p>目录</p><p>一第一章议题</p><p class="body-heading">二第二章议题</p>'
              '<p>三第三章议题</p><p>· · ·</p><p class="body-heading">第一章议题</p><p>正文一。</p>'
              '<p class="body-heading">第二章议题</p><p>正文二。</p><p class="body-heading">第三章议题</p><p>正文三。</p>')
    old = page.evaluate("(html) => renderBodyContentWithToc(html, true)", legacy)
    assert len(old["toc"]) == 3 and old["html"].count('body-web-toc-entry') == 3
    cleaned = page.evaluate("""() => sanitizeBodyHtml(`<div class="body-web-import">
      <custom><p style="position:fixed;background:url(https://example.invalid/pixel);color:blue">保留</p>
      <script>忽略</script><img onerror="ignored" src="invalid:source"><b>后续内容</b></custom>
      <a href="https://example.invalid" onclick="ignored">链接</a></div>`)""")
    assert "position" not in cleaned and "example.invalid/pixel" not in cleaned
    assert "忽略" not in cleaned and "onerror" not in cleaned and "onclick" not in cleaned
    assert "color:blue" in cleaned and "后续内容" in cleaned
    if baseline and screenshots:
        article["content"] = baseline.read_text()
        if baseline_frontend:
            frontend = baseline_frontend
        page.reload()
        page.evaluate("openArticleInTab(1, '匿名公司回购实务笔记')")
        body.get_by_text("目录", exact=True).first.wait_for()
        page.screenshot(path=screenshots / "reader-before.png")
    context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", choices=["chromium", "webkit"], default="chromium")
    parser.add_argument("--executable")
    parser.add_argument("--screenshots", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--baseline-frontend", type=Path)
    args = parser.parse_args()
    launch = {"executable_path": args.executable} if args.executable else {}
    if args.browser == "chromium":
        asyncio.run(verify_dynamic_wechat_import(launch))
    with sync_playwright() as playwright:
        browser = getattr(playwright, args.browser).launch(**launch)
        run(browser, args.screenshots, args.baseline, args.baseline_frontend)
        print(f"{args.browser}: web import reader, editor round trip, and compatibility passed")
