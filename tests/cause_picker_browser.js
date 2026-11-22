/* Run against a local Stella server backed by an empty test database. */
const assert = require('node:assert/strict');
const { chromium, webkit } = require(process.env.STELLA_PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.STELLA_CAUSE_TEST_ORIGIN;
assert.match(origin || '', /^http:\/\/127\.0\.0\.1:\d+$/);

async function check(engine) {
  const chrome = process.env.STELLA_CHROME_EXECUTABLE;
  const browser = await engine.launch(chrome && engine === chromium ? { executablePath: chrome } : {});
  try {
    const page = await browser.newPage({ serviceWorkers: 'block', viewport: { width: 1280, height: 860 } });
    page.setDefaultTimeout(8000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const popup = page.locator('#apex-cause-picker');
    const search = popup.getByRole('searchbox');
    const input = page.locator('#caseTypeInput');
    const pick = label => popup.locator('.apex-cause-option').filter({ hasText: label }).first();
    const open = async field => {
      await field.click();
      await popup.waitFor({ state: 'visible' });
    };

    await page.goto(origin + '/business-approval-generator');
    await open(input);
    await popup.getByRole('button', { name: '民事', exact: true }).click();
    await popup.getByRole('button', { name: '展开物权纠纷', exact: true }).click();
    await popup.getByRole('button', { name: '展开所有权纠纷', exact: true }).click();
    await popup.getByRole('button', { name: '展开建筑物区分所有权纠纷', exact: true }).click();
    assert.match(await popup.locator('nav').innerText(), /物权纠纷[\s\S]*所有权纠纷[\s\S]*建筑物区分所有权纠纷/);
    const tree = popup.locator('.apex-cause-tree');
    async function labelStart(name) {
      return tree.getByRole('button', { name, exact: true }).evaluate(button =>
        button.getBoundingClientRect().left + parseFloat(getComputedStyle(button).paddingLeft));
    }
    const starts = await Promise.all(['物权纠纷', '所有权纠纷', '建筑物区分所有权纠纷', '车位纠纷'].map(labelStart));
    const steps = starts.slice(1).map((left, index) => left - starts[index]);
    assert.ok(steps[0] > 0 && steps.every(step => Math.abs(step - steps[0]) < 0.5), steps);
    assert.ok(Math.abs(await labelStart('业主撤销权纠纷') - starts[2]) < 0.5);
    assert.equal(await tree.locator('.apex-cause-children').count(), 3);
    assert.equal(await popup.locator('nav [aria-current="location"]').innerText(), '建筑物区分所有权纠纷');
    assert.match(await popup.evaluate(el => getComputedStyle(el).backdropFilter), /blur/);
    if (process.env.STELLA_CAUSE_SCREENSHOT && engine === chromium) {
      await popup.screenshot({ path: process.env.STELLA_CAUSE_SCREENSHOT });
    }
    await popup.getByRole('button', { name: '收起建筑物区分所有权纠纷', exact: true }).click();
    assert.equal(await pick('车位纠纷').count(), 0);
    await search.fill('所有权 车位');
    assert.match(await pick('车位纠纷').innerText(), /物权纠纷 › 所有权纠纷 › 建筑物区分所有权纠纷/);
    assert.equal(await input.inputValue(), '');
    assert.equal(await popup.locator('.apex-cause-tree').count(), 0);
    await search.press('ArrowDown');
    await page.keyboard.press('Enter');
    assert.equal(await input.inputValue(), '车位纠纷');
    await popup.waitFor({ state: 'hidden' });
    await open(input);
    assert.match(await popup.locator('.apex-cause-list').innerText(), /最近使用/);
    await popup.getByRole('button', { name: '清除案由', exact: true }).click();
    assert.equal(await input.inputValue(), '');

    for (const route of ['power-attorney-generator', 'suohan-generator', 'document-bundle-generator']) {
      await page.goto(origin + '/' + route);
      await open(input);
      await popup.getByRole('button', { name: '刑事罪名', exact: true }).click();
      await search.fill('盗窃罪');
      assert.match(await pick('盗窃罪').innerText(), /刑事罪名 › 侵犯财产罪/);
      await pick('盗窃罪').click();
      assert.equal(await input.inputValue(), '盗窃罪');
      assert.equal(await page.evaluate(() => ApexCausePicker.documentLabel('盗窃罪')), '盗窃罪');
    }
    await page.goto(origin + '/suohan-generator');
    await open(input);
    const custom = '本地测试自定义案由（' + engine.name() + ' ' + Date.now() + '）';
    await search.fill(custom);
    const customSaved = page.waitForResponse(response =>
      response.url().endsWith('/api/suohan/options') && response.request().method() === 'POST');
    await popup.getByRole('button', { name: /使用当前输入/ }).click();
    assert.ok((await customSaved).ok());
    assert.equal(await input.inputValue(), custom);
    const customOptions = await page.request.get(origin + '/api/suohan/options?type=caseType');
    assert.ok((await customOptions.json()).caseType.some(item => item.name === custom));

    await page.goto(origin + '/document-bundle-generator');
    await page.reload();
    await open(input);
    await popup.getByText('最近使用', { exact: true }).waitFor();
    assert.match(await popup.locator('.apex-cause-list').innerText(), /最近使用[\s\S]*盗窃罪/);
    await search.fill('行政许可 建设工程');
    await pick('建设工程规划许可').click();
    assert.equal(await input.inputValue(), '建设工程规划许可');
    assert.equal(await page.evaluate(() => ApexCausePicker.documentLabel('建设工程规划许可')), '建设工程规划许可');

    // Verify the real case panel saves the selected text to the isolated database.
    const fixtureTitle = '案由回归测试（' + engine.name() + '）';
    const created = await page.request.post(origin + '/api/case-manager/cases', {
      data: { title: fixtureTitle, case_type: '旧系统自定义事由', parties: [{ name: '示例委托人', party_group: 'client' }] }
    });
    assert.ok(created.ok(), await created.text());
    const record = await created.json();
    const id = record.id || record.case_id;
    assert.ok(id, JSON.stringify(record));
    await page.goto(origin + '/?workspace=cases');
    const cases = page.frameLocator('iframe[src*="case-manager"][src*="workspace_id="]');
    const caseInput = cases.locator('[name="case_type"]');
    await page.waitForFunction(() => [...document.querySelectorAll('iframe[src*="workspace_id="]')]
      .some(frame => typeof frame.contentWindow.openDetail === 'function'));
    const frame = page.frames().find(frame => frame.url().includes('/case-manager?workspace_id=') ||
      (frame.url().includes('/case-manager?') && frame.url().includes('workspace_id=')));
    assert.ok(frame);
    await cases.locator(`[data-stella-case-id="${id}"]`).waitFor();
    await frame.evaluate(async id => {
      await openDetail('cases', id);
      await editCaseSection('basic');
    }, id);
    assert.equal(await caseInput.inputValue(), '旧系统自定义事由');
    const linkedPopup = cases.locator('#apex-cause-picker');
    await caseInput.click();
    await linkedPopup.getByRole('searchbox').fill('商品房 销售');
    await linkedPopup.getByRole('button', { name: /^商品房销售合同纠纷/ }).first().click();
    assert.equal(await caseInput.inputValue(), '商品房销售合同纠纷');
    await frame.evaluate(() => saveCaseSection('basic'));
    await frame.evaluate(async id => {
      await openDetail('cases', id);
      await editCaseSection('basic');
    }, id);
    assert.equal(await caseInput.inputValue(), '商品房销售合同纠纷');
    await frame.evaluate(() => { closeEditor(); openNewSeries(); });
    await cases.locator('#seriesFormCaseType').click();
    await linkedPopup.getByRole('searchbox').fill('买卖合同纠纷');
    await linkedPopup.getByRole('button', { name: /^买卖合同纠纷/ }).first().click();
    await cases.locator('#seriesFormTitle').fill('案由系列回归 ' + engine.name() + ' ' + Date.now());
    await frame.evaluate(() => createSeriesFromForm());
    assert.equal(await frame.evaluate(() => state.seriesWorkspace.case_type), '买卖合同纠纷');
    await frame.evaluate(async () => {
      await switchSeriesWorkspaceTab('public');
      openSeriesPublicFieldEditor('case_type');
    });
    await cases.locator('#seriesPublicCaseType').click();
    await linkedPopup.getByRole('searchbox').fill('商品房销售合同纠纷');
    await linkedPopup.getByRole('button', { name: /^商品房销售合同纠纷/ }).first().click();
    await frame.evaluate(() => saveSeriesPublicField('case_type'));
    assert.equal(await frame.evaluate(() => state.seriesWorkspace.case_type), '商品房销售合同纠纷');

    await frame.evaluate(async () => {
      await switchSeriesWorkspaceTab('children');
      await openSeriesChildEditor();
    });
    const childCause = cases.locator('#childFormType');
    assert.equal(await childCause.inputValue(), '商品房销售合同纠纷');
    await childCause.click();
    await linkedPopup.getByRole('searchbox').fill('使用权 出让');
    await linkedPopup.getByRole('button', { name: /建设用地使用权出让合同纠纷/ }).first().click();
    await cases.locator('#childFormName').fill('示例子案');
    await frame.evaluate(() => saveSeriesChild(0));
    const child = await frame.evaluate(() => state.seriesWorkspace.children[0]);
    assert.equal(child.case_type, '建设用地使用权出让合同纠纷');
    await frame.evaluate(() => toggleSeriesTableEditMode());
    await cases.locator('td[data-series-column-key="case_type"]').getByRole('button', { name: '选择案由' }).click();
    await linkedPopup.getByRole('searchbox').fill('民间借贷');
    await linkedPopup.getByRole('button', { name: /^民间借贷纠纷/ }).first().click();
    await frame.waitForFunction(() => state.seriesWorkspace.children[0]?.case_type === '民间借贷纠纷');

    await page.route('**/api/automated-filing/jobs/latest', route => route.fulfill({
      json: { job: { id: 'browser-fixture', status: 'review_ready', materials: [],
        facts: { case_type: '民事一审', cause: '原立案案由',
          court_cause_candidates: [{ label: '示例法院候选（虚构）', verified_for_current_court: 'true' }]
        }
      } }
    }));
    await page.goto(origin + '/automation-filing');
    const filing = page.locator('#cause');
    await open(filing);
    assert.equal(await popup.getByRole('button', { name: '刑事罪名', exact: true }).count(), 0);
    await pick('示例法院候选').click();
    assert.equal(await filing.inputValue(), '示例法院候选（虚构）');

    await page.setViewportSize({ width: 390, height: 590 });
    await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' });
    await page.goto(origin + '/business-approval-generator');
    await page.evaluate(() => {
      document.documentElement.dataset.theme = 'dark';
      document.body.classList.add('dark-mode');
    });
    await open(input);
    await popup.getByRole('button', { name: '民事', exact: true }).click();
    await popup.getByRole('button', { name: '常用优先', exact: true }).click();
    const personalityBranches = popup.getByRole('button', { name: '展开人格权纠纷', exact: true });
    await personalityBranches.first().click();
    await personalityBranches.first().click();
    await popup.getByRole('button', { name: '展开隐私权、个人信息保护纠纷', exact: true }).click();
    const bounds = await popup.boundingBox();
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 390);
    assert.ok(bounds.y >= 0 && bounds.y + bounds.height <= 590);
    const parentNames = tree.getByRole('button', { name: '人格权纠纷', exact: true });
    const offsets = await parentNames.evaluateAll(buttons => buttons.map(button => button.getBoundingClientRect().left));
    assert.equal(offsets.length, 2);
    assert.equal(offsets[1] - offsets[0], 20);
    assert.equal(await popup.evaluate(el => getComputedStyle(el).getPropertyValue('--apex-surface-solid').trim()), '#191f2a');
    if (process.env.STELLA_CAUSE_DARK_SCREENSHOT && engine === chromium) {
      await popup.screenshot({ path: process.env.STELLA_CAUSE_DARK_SCREENSHOT });
    }
    if (engine === chromium) {
      const cdp = await page.context().newCDPSession(page);
      await cdp.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-transparency', value: 'reduce' }] });
      assert.equal(await popup.evaluate(el => getComputedStyle(el).backdropFilter), 'none');
      await cdp.detach();
    }
    await popup.getByRole('button', { name: '刑事罪名', exact: true }).click();
    await search.fill('盗窃罪');
    await pick('盗窃罪').click();
    assert.equal(await input.inputValue(), '盗窃罪');
    assert.deepEqual(errors, []);
    console.log(engine.name() + ' cause picker passed');
  } finally {
    await browser.close();
  }
}

(async () => {
  for (const engine of [chromium, webkit]) await check(engine);
})().catch(error => { console.error(error); process.exitCode = 1; });
