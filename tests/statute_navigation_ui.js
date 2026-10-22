/* Anonymous DOM fixtures; never opens the live knowledge database. */
const fs = require('fs');
const assert = require('assert/strict');
const { chromium } = require('playwright');
const source = fs.readFileSync('frontend/app.js', 'utf8');
(async () => {
  const browser = await chromium.launch({headless:true, channel:'chrome'});
  try {
    const page = await browser.newPage();
    await page.setContent('<div id="tab-detail-body-test"><p>依照第七百三十五条处理。</p><p id="correct"><strong>第七百三十五条</strong> 融资租赁合同定义。</p><p id="wrong">第七百五十八条 其他规定。</p></div><div id="detail-body"><p id="legacy"><b>第七百三十五条</b> 融资租赁合同定义。</p></div>');
    await page.addScriptTag({content: source.slice(source.indexOf('function cnArticleNumberToInt('), source.indexOf('/**', source.indexOf('function cnArticleNumberToInt('))) + source.slice(source.indexOf('function scrollTabBodyToOffset('), source.indexOf('function highlightAndScrollInArticleTab(')) + source.slice(source.indexOf('function scrollBodyToOffset('), source.indexOf('/**', source.indexOf('function scrollBodyToOffset('))) });
    await page.evaluate(() => { window.$ = id => document.getElementById(id); });
    for (const quote of ['《中华人民共和国民法典》第735条', '第七百三十五条 融资租赁合同定义。', '第735条']) {
      const id = await page.evaluate(quote => {
        document.querySelectorAll('.citation-target-highlight').forEach(el => el.classList.remove('citation-target-highlight'));
        scrollTabBodyToOffset('test', 1000, quote);
        return document.querySelector('.citation-target-highlight')?.id;
      }, quote);
      assert.equal(id, 'correct', quote);
    }
    assert.equal(await page.evaluate(() => {
      scrollBodyToOffset(1, '《中华人民共和国民法典》第735条');
      return document.querySelector('#detail-body .citation-target-highlight')?.id;
    }), 'legacy');
    assert.equal(await page.evaluate(() => findCitationQuoteNode(document.getElementById('detail-body'), '融资租赁合同定义。')?.id), 'legacy');
    assert.equal(await page.evaluate(() => findCitationQuoteNode(document.getElementById('detail-body'), '第736条')), null);
    assert.equal(await page.evaluate(() => {
      document.querySelector('#legacy').classList.remove('citation-target-highlight');
      scrollBodyToOffset(1, '第736条');
      return document.querySelector('#detail-body .citation-target-highlight');
    }), null);
    console.log('Statute navigation: Chinese/Arabic labels, inline markup, stale offsets, both readers and ordinary quotes passed');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exit(1);});
