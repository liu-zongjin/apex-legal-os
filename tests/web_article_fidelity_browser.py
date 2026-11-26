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


def verify_case_collection(page, article):
    body_html = """<title>匿名典型案例汇编</title><div id="js_content">
      <h2>点击上方“蓝字”关注我们</h2>
      <section>
        <p style="font-size:24px;text-align:center"><strong>一、合同履行中应兼顾当事人的合理预期，争议应当依据实际交易情况作出判断——甲公司与乙公司买卖合同纠纷案</strong></p>
        <p>（匿名典型案例一）</p><h3>【基本案情】</h3><p>甲乙双方签订买卖合同，并按合同约定交付货物。后双方就结算发生争议。</p>
        <h3>【裁判结果】</h3><p>裁判结果说明。</p><h3>【典型意义】</h3><p>典型意义说明。</p>
      </section>
      <section>
        <h2 style="font-size:24px;text-align:center">二、某投资公司与某科技公司</h2>
        <h2 style="font-size:24px;text-align:center">决议纠纷案</h2>
        <p>（匿名典型案例二）</p><h3>【基本案情】</h3><p>公司股东就决议效力发生争议。</p>
        <h3>【裁判结果】</h3><p>裁判结果说明。</p><h2>【一审案号】匿名法院（2025）示例1号</h2>
      </section>
      <section>
        <p style="font-size:24px;text-align:center"><strong>三、某公司与某股东<br>股东资格确认纠纷案</strong></p>
        <h3>【基本案情】</h3><p>双方就股东资格发生争议，并依约申请解决。</p>
        <h3>【裁判结果】</h3><p>裁判结果说明。</p>
      </section>
      <h2>来源：示例公众号</h2>
    </div>"""
    article.update(import_fixture(html=body_html))
    page.reload()
    page.evaluate("openArticleInTab(1, '匿名典型案例汇编')")
    web = page.locator(".tab-article-body-text .body-web-import").first
    web.get_by_text("【基本案情】", exact=True).first.wait_for()
    toc = page.locator(".sidebar-toc-link")
    labels = toc.all_text_contents()
    assert len(labels) == 3, labels
    assert labels[0].strip() == "一、合同履行中应兼顾当事人的合理预期，争议应当依据实际交易情况作出判断——甲公司与乙公司买卖合同纠纷案"
    assert labels[1].strip() == "二、某投资公司与某科技公司决议纠纷案"
    assert labels[2].strip() == "三、某公司与某股东股东资格确认纠纷案"
    assert toc.locator("xpath=self::*[contains(@class, 'level-1')]").count() == 3
    toc.nth(1).click()
    assert web.locator(".body-toc-target-flash").inner_text() == "二、某投资公司与某科技公司"
    assert web.get_by_text("【基本案情】", exact=True).count() == 3
    assert web.get_by_text("来源：示例公众号", exact=True).count() == 1
    regular = page.evaluate("""() => renderBodyContentWithToc(
      '<div class="body-web-import"><h2>点击上方“蓝字”关注我们</h2><h2>引言</h2>'
      + '<p>介绍正文。</p><h3>方法</h3><p>方法正文。</p><h2>来源：示例公众号</h2></div>'
    ).toc""")
    assert [(item["text"], item["level"]) for item in regular] == [("引言", 1), ("方法", 2)]


def verify_search_result_opening(page, article):
    filler = '<p>此段在屏幕外，用来验证只滚动文章正文。</p>' * 45
    article.update(title="匿名财产查询", content=(
        '<div class="body-web-import"><p>第一处测试钱包命中。</p>' + filler
        + '<h2>第二处<strong>测试钱包</strong>命中</h2>' + filler + '</div>'
    ))
    snippets = [{"text": "第一处测试钱包命中。", "offset": 3},
                {"text": "第二处测试钱包命中", "offset": len("第一处测试钱包命中。") + 45 * len("此段在屏幕外，用来验证只滚动文章正文。") + 3}]
    result = {**article, "content_snippets": snippets}
    page.evaluate("""result => {
      goToMainView();
      state.q = '测试钱包';
      state.fuzzy = true;
      state.searchScope = 'content';
      renderArticles([result]);
    }""", result)
    card = page.locator(".article-card[data-article-id='1']")
    card.locator(".card-content-snippet").nth(1).click()
    matching = page.locator(".tab-article-body-text .citation-target-highlight")
    assert matching.inner_text() == "第二处测试钱包命中"
    assert page.locator("#detail-modal.open").count() == 0
    assert page.locator(".tab-article-body").first.evaluate("el => el.scrollTop") > 0
    assert page.evaluate("window.scrollY") == 0

    result["content_snippets"] = []
    result["search_match"] = {"field": "content", "label": "正文", "offset": 0, "text": "第一处测试钱包命中。"}
    page.evaluate("result => { goToMainView(); renderArticles([result]); }", result)
    card.locator("[data-search-evidence]").click()
    assert matching.inner_text() == "第一处测试钱包命中。"
    assert page.locator("#detail-modal.open").count() == 0

    page.evaluate("result => { goToMainView(); renderArticles([result]); }", result)
    card.get_by_text("匿名财产查询", exact=True).click()
    page.locator(".tab-article-body-text").get_by_text("第一处测试钱包命中。").wait_for()
    assert page.locator("#detail-modal.open").count() == 0
    assert matching.count() == 0


def verify_url_import_progress(page):
    page.evaluate(r"""() => {
      const original = window.fetch;
      window.urlImportRequests = 0;
      window.fetch = (url, options) => {
        if (url !== '/api/submit/url') return original(url, options);
        window.urlImportRequests++;
        if (options.headers.Accept !== 'application/x-ndjson') throw Error('missing progress negotiation');
        const stream = new ReadableStream({start(controller) { window.urlImportController = controller; }});
        return Promise.resolve(new Response(stream, {headers: {'Content-Type': 'application/x-ndjson'}}));
      };
      window.emitImport = (event, done = false) => {
        const line = new TextEncoder().encode(JSON.stringify(event) + '\n');
        const at = Math.floor(line.length / 2);
        urlImportController.enqueue(line.slice(0, at));
        urlImportController.enqueue(line.slice(at));
        if (done) urlImportController.close();
      };
      openSubmitModal();
    }""")
    page.locator("#url-input").fill("https://example.com/anonymous")
    page.locator("#btn-submit-url").click()
    status = page.locator("#submit-progress .summary-glow-text")
    status.wait_for()
    page.wait_for_function("window.urlImportRequests === 1")
    assert status.inner_text() == "正在提交网页链接…"
    page.evaluate("submitUrl(); closeSubmitModal(); openSubmitModal();")
    assert page.evaluate("window.urlImportRequests") == 1
    for phase, expected in [
        ("wechat", "正在读取公众号页面并提取正文…"),
        ("wechat_fallback", "正在用备用方式读取公众号正文…"),
        ("check_content", "正在检查提取到的正文…"),
        ("prepare", "正在生成初步摘要并判定专业领域…"),
        ("save", "正在保存到知识库…"),
    ]:
        page.evaluate("phase => emitImport({phase})", phase)
        page.wait_for_function("text => document.querySelector('#submit-progress .summary-glow-text')?.textContent === text", arg=expected)
    page.evaluate("emitImport({result:{success:true,title:'匿名结果',domains:[],summary:'摘要',ai_summary_pending:true}}, true)")
    result = page.locator("#submit-result")
    result.get_by_text("收录成功", exact=False).wait_for()
    assert "AI 摘要已安排在后台生成" in result.inner_text()
    assert page.locator("#submit-progress .summary-generation-glow").count() == 0


def run(browser, screenshots, baseline, baseline_frontend):
    article = dict(import_fixture(), id=1, source_type="url", source_url=URL, tags=[],
                   domains=[], summary="", created_at="2026-01-01")
    context = browser.new_context(viewport={"width": 1600, "height": 900}, service_workers="block",
                                  reduced_motion="reduce")
    context.add_init_script("localStorage.setItem('stella.welcome.dismissed.v1', '1')")
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
        if path in {"/api/notes/1", "/api/domains"}:
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
    verify_case_collection(page, article)
    verify_search_result_opening(page, article)
    if baseline and screenshots:
        article["content"] = baseline.read_text()
        if baseline_frontend:
            frontend = baseline_frontend
        page.reload()
        page.evaluate("openArticleInTab(1, '匿名公司回购实务笔记')")
        body.get_by_text("目录", exact=True).first.wait_for()
        page.screenshot(path=screenshots / "reader-before.png")
    verify_url_import_progress(page)
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
