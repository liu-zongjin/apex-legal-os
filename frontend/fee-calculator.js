/* 诉讼仲裁费计算器：收费表及来源集中维护于本文件。 */
(function () {
  'use strict';

  const VERIFIED_ON = '2026-08-25';
  const SOURCES = {
    court: { title: '《诉讼费用交纳办法》（最高人民法院）', url: 'https://www.court.gov.cn/jianshe/xiangqing/5092.html', effective: '国务院令第481号' },
    gzac: { title: '广州仲裁委员会：2025年1月1日起收案仲裁收费标准', url: 'https://www.gziac.cn/newzcfss1', effective: '2025-01-01起' },
    gzacFinance: { title: '广州仲裁委员会：2025年1月1日起普通金融案件收费标准', url: 'https://www.gziac.cn/calculateFinance', effective: '2025-01-01起' },
    fszc: { title: '佛山仲裁委员会：费用计算', url: 'https://www.fszc.gov.cn/zcsf/fyjs/', effective: '官网现行页面' },
    fszcProcess: { title: '佛山仲裁委员会：案件处理费', url: 'https://www.fszc.gov.cn/zcsf/ajclf/index.html', effective: '官网现行页面' },
    scia: { title: '深圳国际仲裁院仲裁规则（2019年施行，2025年修正）', url: 'https://www.sciajm.org.cn/sz/arbitration/international-jiangmen/rule/scia-rules-2025.html', effective: '2025年修正' },
    sciaFinance: { title: '深圳国际仲裁院金融借款争议仲裁规则（2025年修正）', url: 'https://www.sciajm.org.cn/sz/arbitration/international-jiangmen/rule/scia-rule-2.html', effective: '2025-07-01起' },
    cietac: { title: '中国国际经济贸易仲裁委员会仲裁费用表（2024版）', url: 'https://www.cietac.org/articles/25014', effective: '2024版' },
    shac: { title: '上海仲裁委员会仲裁规则（2022年）附件一仲裁费用表', url: 'https://fgw.sh.gov.cn/ys-syjf-zc-2.3.1/20240408/996ef35bb9444399834f790b4cf353a7.html', effective: '2022-07-01起' },
    riskAgency: { title: '《关于进一步规范律师服务收费的意见》（司发通〔2021〕87号）', url: 'https://ydzk.chineselaw.com/zxt/statuteDetail/detailPage/934ce8fc5e00f66721d26750038b874b', effective: '2021-12-28发布，现行有效' },
  };

  const riskAgencyTiers = [
    { from: 0, upTo: 1000000, rate: 0.18, label: '不足100万元的部分：18%' },
    { from: 1000000, upTo: 5000000, rate: 0.15, label: '100万元以上不足500万元的部分：15%' },
    { from: 5000000, upTo: 10000000, rate: 0.12, label: '500万元以上不足1000万元的部分：12%' },
    { from: 10000000, upTo: 50000000, rate: 0.09, label: '1000万元以上不足5000万元的部分：9%' },
    { from: 50000000, upTo: Infinity, rate: 0.06, label: '5000万元以上的部分：6%' },
  ];
  const calculatorHistory = { litigation_arbitration: [], risk_agency: [] };
  const calculatorHistoryLoadFailed = { litigation_arbitration: false, risk_agency: false };
  let initialized = false;

  const courtRules = [
    { upTo: 10000, fixed: 50, label: '不超过1万元：50元' },
    { upTo: 100000, from: 10000, base: 50, rate: 0.025, label: '超过1万元至10万元部分：2.5%' },
    { upTo: 200000, from: 100000, base: 2300, rate: 0.02, label: '超过10万元至20万元部分：2%' },
    { upTo: 500000, from: 200000, base: 4300, rate: 0.015, label: '超过20万元至50万元部分：1.5%' },
    { upTo: 1000000, from: 500000, base: 8800, rate: 0.01, label: '超过50万元至100万元部分：1%' },
    { upTo: 2000000, from: 1000000, base: 13800, rate: 0.009, label: '超过100万元至200万元部分：0.9%' },
    { upTo: 5000000, from: 2000000, base: 22800, rate: 0.008, label: '超过200万元至500万元部分：0.8%' },
    { upTo: 10000000, from: 5000000, base: 46800, rate: 0.007, label: '超过500万元至1000万元部分：0.7%' },
    { upTo: 20000000, from: 10000000, base: 81800, rate: 0.006, label: '超过1000万元至2000万元部分：0.6%' },
    { from: 20000000, base: 141800, rate: 0.005, label: '超过2000万元部分：0.5%' },
  ];

  const gzAcceptRules = [
    { upTo: 1000, fixed: 100, label: '1000元以下：100元' },
    { upTo: 50000, from: 1000, base: 100, rate: 0.05, label: '1001元至5万元部分：5%' },
    { upTo: 100000, from: 50000, base: 2550, rate: 0.04, label: '5万元至10万元部分：4%' },
    { upTo: 200000, from: 100000, base: 4550, rate: 0.03, label: '10万元至20万元部分：3%' },
    { upTo: 500000, from: 200000, base: 7550, rate: 0.02, label: '20万元至50万元部分：2%' },
    { upTo: 1000000, from: 500000, base: 13550, rate: 0.01, label: '50万元至100万元部分：1%' },
    { from: 1000000, base: 18550, rate: 0.005, label: '超过100万元部分：0.5%' },
  ];

  const shAcceptRules = gzAcceptRules;
  const shProcessRules = [
    { upTo: 200000, fixed: 3000, label: '20万元及以下：最低3000元' },
    { upTo: 500000, from: 200000, base: 3000, rate: 0.012, label: '20万元至50万元部分：1.2%' },
    { upTo: 1000000, from: 500000, base: 6600, rate: 0.01, label: '50万元至100万元部分：1%' },
    { upTo: 5000000, from: 1000000, base: 11600, rate: 0.004, label: '100万元至500万元部分：0.4%' },
    { upTo: 10000000, from: 5000000, base: 27600, rate: 0.003, label: '500万元至1000万元部分：0.3%' },
    { upTo: 20000000, from: 10000000, base: 42600, rate: 0.002, label: '1000万元至2000万元部分：0.2%' },
    { upTo: 40000000, from: 20000000, base: 62600, rate: 0.001, label: '2000万元至4000万元部分：0.1%' },
    { from: 40000000, base: 82600, rate: 0.0005, label: '超过4000万元部分：0.05%' },
  ];

  const cietacAcceptRules = [
    { upTo: 100000, rate: 0.04, minimum: 100, label: '10万元及以下：4%，最低100元' },
    { upTo: 500000, from: 100000, base: 4000, rate: 0.02, label: '10万元至50万元部分：2%' },
    { upTo: 1000000, from: 500000, base: 12000, rate: 0.01, label: '50万元至100万元部分：1%' },
    { upTo: 50000000, from: 1000000, base: 17000, rate: 0.005, label: '100万元至5000万元部分：0.5%' },
    { upTo: 300000000, from: 50000000, base: 262000, rate: 0.0048, label: '5000万元至3亿元部分：0.48%' },
    { upTo: 1000000000, from: 300000000, base: 1462000, rate: 0.0046, label: '3亿元至10亿元部分：0.46%' },
    { upTo: 2000000000, from: 1000000000, base: 4682000, rate: 0.0042, label: '10亿元至20亿元部分：0.42%' },
    { from: 2000000000, base: 8882000, rate: 0.004, capAt: 3000000000, label: '20亿元至30亿元部分：0.4%；30亿元以上不再计收' },
  ];
  const cietacProcessRules = [
    { upTo: 200000, fixed: 6000, label: '20万元及以下：最低6000元' },
    { upTo: 500000, from: 200000, base: 6000, rate: 0.02, label: '20万元至50万元部分：2%' },
    { upTo: 1000000, from: 500000, base: 12000, rate: 0.015, label: '50万元至100万元部分：1.5%' },
    { upTo: 5000000, from: 1000000, base: 19500, rate: 0.0045, label: '100万元至500万元部分：0.45%' },
    { upTo: 20000000, from: 5000000, base: 37500, rate: 0.003, label: '500万元至2000万元部分：0.3%' },
    { upTo: 100000000, from: 20000000, base: 82500, rate: 0.002, label: '2000万元至1亿元部分：0.2%' },
    { upTo: 1000000000, from: 100000000, base: 242500, rate: 0.001, label: '1亿元至10亿元部分：0.1%' },
    { from: 1000000000, base: 1142500, rate: 0.0003, capAt: 3000000000, label: '10亿元至30亿元部分：0.03%；30亿元以上不再计收' },
  ];

  const sciaGeneralRules = [
    [10000, 8000], [50000, 8000, 10000, 0.08], [100000, 11200, 50000, 0.07], [200000, 14700, 100000, 0.033],
    [500000, 18000, 200000, 0.032], [1000000, 27600, 500000, 0.025], [3000000, 40100, 1000000, 0.0085],
    [5000000, 57100, 3000000, 0.0057], [10000000, 68500, 5000000, 0.0053], [20000000, 116700, 10000000, 0.0052],
    [50000000, 168700, 20000000, 0.0049], [80000000, 315700, 50000000, 0.0046], [100000000, 453700, 80000000, 0.0043],
    [500000000, 539700, 100000000, 0.00395], [1000000000, 2119700, 500000000, 0.0037], [2000000000, 3969700, 1000000000, 0.0033],
    [3000000000, 7269700, 2000000000, 0.003], [Infinity, 10269700],
  ];
  const sciaFinanceRules = [
    [50000, 5000], [100000, 5000, 50000, 0.07], [200000, 8500, 100000, 0.04], [500000, 12500, 200000, 0.017],
    [1000000, 17600, 500000, 0.014], [3000000, 24600, 1000000, 0.0075], [5000000, 39600, 3000000, 0.0065],
    [10000000, 52600, 5000000, 0.0059], [20000000, 97800, 10000000, 0.0046], [50000000, 143800, 20000000, 0.0043],
    [80000000, 272800, 50000000, 0.004], [100000000, 392800, 80000000, 0.0037], [500000000, 466800, 100000000, 0.0034],
    [1000000000, 1826800, 500000000, 0.0032], [2000000000, 3426800, 1000000000, 0.0027], [3000000000, 6126800, 2000000000, 0.0024], [Infinity, 8526800],
  ];
  const cietacInternationalRules = [
    [1000000, 10000, 0, 0.04], [2000000, 40000, 1000000, 0.035], [5000000, 75000, 2000000, 0.025],
    [10000000, 150000, 5000000, 0.015], [100000000, 225000, 10000000, 0.01], [300000000, 1125000, 100000000, 0.0065],
    [1000000000, 2425000, 300000000, 0.006], [2000000000, 6625000, 1000000000, 0.0045], [3000000000, 11125000], [Infinity, 11125000],
  ];

  const schedules = {
    gzac: {
      name: '广州仲裁委员会', source: SOURCES.gzac,
      types: {
        general: { label: '一般国内财产争议', description: '案件受理费 + 案件处理费', calculate: amount => ({ acceptance: byFormula(amount, gzAcceptRules), processing: formula(amount, [
          { upTo: 1000000, fixed: 5000, label: '100万元以下：5000元' }, { upTo: 10000000, from: 1000000, base: 5000, rate: 0.0015, label: '100万元至1000万元部分：0.15%' },
          { upTo: 100000000, from: 10000000, base: 18500, rate: 0.001, label: '1000万元至1亿元部分：0.10%' }, { upTo: 1000000000, from: 100000000, base: 108500, rate: 0.0005, label: '1亿元至10亿元部分：0.05%' },
          { upTo: 2000000000, from: 1000000000, base: 558500, rate: 0.0003, label: '10亿元至20亿元部分：0.03%' }, { from: 2000000000, base: 858500, rate: 0.0001, label: '超过20亿元部分：0.01%' },
        ]) }) },
        finance: { label: '普通金融案件', source: SOURCES.gzacFinance, description: '处理费封顶108,500元', calculate: amount => ({ acceptance: byFormula(amount, gzAcceptRules), processing: cappedGzFinanceProcess(amount) }) },
        internet: { label: '互联网交易争议专门程序', description: '免收案件处理费', calculate: amount => ({ acceptance: byFormula(amount, gzAcceptRules), processing: unavailable('互联网交易争议专门程序案件免收案件处理费', 0) }) },
      },
    },
    fszc: {
      name: '佛山仲裁委员会', source: SOURCES.fszc,
      types: {
        general: { label: '非金融案件', description: '官网费用计算按中限/底限计算受理费', calculate: amount => ({ acceptance: foshanAcceptance(amount, false), processing: unavailable('案件处理费按实际支出收取，以仲裁委通知为准') }) },
        finance: { label: '金融案件', description: '官网费用计算按中限/底限计算受理费', calculate: amount => ({ acceptance: foshanAcceptance(amount, true), processing: unavailable('案件处理费按实际支出收取，以仲裁委通知为准') }) },
      },
    },
    scia: {
      name: '深圳国际仲裁院', source: SOURCES.scia,
      types: {
        general: { label: '一般仲裁案件', description: '现行费用表列示仲裁费用总额，未区分受理费与处理费', calculate: amount => totalOnly(formulaFromTuple(amount, sciaGeneralRules), '现行费用表未分别列示案件受理费和案件处理费') },
        finance: { label: '金融借款争议', source: SOURCES.sciaFinance, description: '现行费用表列示仲裁费用总额，未区分受理费与处理费', calculate: amount => totalOnly(formulaFromTuple(amount, sciaFinanceRules), '现行费用表未分别列示案件受理费和案件处理费') },
      },
    },
    cietac: {
      name: '中国国际经济贸易仲裁委员会', source: SOURCES.cietac,
      types: {
        domestic: { label: '中国内地仲裁案件（费用表二）', description: '案件受理费 + 案件处理费', calculate: amount => ({ acceptance: byFormula(amount, cietacAcceptRules), processing: byFormula(amount, cietacProcessRules) }) },
        international: { label: '涉外／国际商事案件（费用表一）', description: '仲裁费用表一另收立案费10,000元', calculate: amount => {
          const fee = amount <= 1000000
            ? { value: Math.max(10000, amount * 0.04), formula: '争议金额 × 4%，最低10,000元' }
            : formulaFromTuple(amount, cietacInternationalRules);
          return totalOnly({ value: fee.value + 10000, formula: `${fee.formula}；另加立案费10,000元` }, '费用表一列示仲裁费用总额，未区分案件受理费与案件处理费');
        } },
      },
    },
    shac: {
      name: '上海仲裁委员会', source: SOURCES.shac,
      types: {
        domestic: { label: '中国内地仲裁案件', description: '案件受理费 + 案件处理费', calculate: amount => ({ acceptance: byFormula(amount, shAcceptRules), processing: byFormula(amount, shProcessRules) }) },
      },
    },
  };

  function formula(amount, rules) {
    const rule = rules.find(item => amount <= (item.upTo === undefined ? Infinity : item.upTo)) || rules[rules.length - 1];
    let value;
    if (rule.fixed !== undefined) value = rule.fixed;
    else if (rule.from === undefined) value = amount * rule.rate;
    else {
      const cappedAmount = rule.capAt ? Math.min(amount, rule.capAt) : amount;
      value = rule.base + (cappedAmount - rule.from) * rule.rate;
    }
    if (rule.minimum !== undefined) value = Math.max(value, rule.minimum);
    return { value, formula: rule.label };
  }
  function byFormula(amount, rules) { return formula(amount, rules); }
  function formulaFromTuple(amount, rules) {
    const rule = rules.find(item => amount <= item[0]) || rules[rules.length - 1];
    const value = rule.length === 2 ? rule[1] : rule[1] + (amount - rule[2]) * rule[3];
    return { value, formula: rule.length === 2 ? `收费标准：${money(rule[1])}元` : `收费标准：${money(rule[1])} +（标的额 − ${money(rule[2])}）× ${percent(rule[3])}` };
  }
  function cappedGzFinanceProcess(amount) {
    if (amount <= 1000000) return { value: 5000, formula: '100万元以下：5000元' };
    if (amount <= 10000000) return { value: 5000 + (amount - 1000000) * 0.0015, formula: '5000 +（标的额 − 100万元）× 0.15%' };
    return { value: Math.min(108500, 18500 + (amount - 10000000) * 0.001), formula: '5000 + 900万元×0.15% +（标的额 − 1000万元）×0.10%，最高108,500元' };
  }
  function foshanAcceptance(amount, financial) {
    let value; let text;
    if (amount <= 1000) { value = 70; text = '1000元以下：70元'; }
    else if (amount <= 50000) { value = amount * 0.045 + 25; text = '标的额 × 4.5% + 25'; }
    else if (amount <= 100000) { value = amount * 0.035 + 525; text = '标的额 × 3.5% + 525'; }
    else if (amount <= 200000) { value = amount * 0.025 + 1525; text = '标的额 × 2.5% + 1,525'; }
    else if (amount <= 500000) { value = amount * 0.015 + 3525; text = '标的额 × 1.5% + 3,525'; }
    else if (amount <= 1000000) { value = amount * 0.0075 + 7275; text = '标的额 × 0.75% + 7,275'; }
    else if (amount < 10000000) { value = amount * 0.0035 + 11275; text = '标的额 × 0.35% + 11,275'; }
    else if (financial) { value = amount * 0.0025 + 8500; text = '标的额 × 0.25% + 8,500'; }
    else { value = amount * 0.0035 + 11275; text = '标的额 × 0.35% + 11,275'; }
    return { value, formula: `${text}（官网费用计算规则）` };
  }
  function unavailable(text, knownValue) { return { unavailable: true, value: knownValue, formula: text }; }
  function totalOnly(total, note) { return { total, totalOnly: true, note, acceptance: unavailable(note), processing: unavailable(note) }; }

  function calculateCourt(amount, ratePercent) {
    const ordinary = formula(amount, courtRules);
    const simple = { value: ordinary.value / 2, formula: `普通程序案件受理费 ${money(ordinary.value)} 元 × 50%` };
    let preservation;
    if (amount <= 1000) preservation = { value: 30, formula: '财产数额不超过1000元：30元' };
    else if (amount <= 100000) preservation = { value: 30 + (amount - 1000) * 0.01, formula: '30 +（标的额 − 1000元）× 1%' };
    else preservation = { value: Math.min(5000, 1020 + (amount - 100000) * 0.005), formula: '30 + 99,000元×1% +（标的额 − 10万元）×0.5%，最高5000元' };
    const guarantee = { value: amount * ratePercent / 100, formula: `标的额 × ${ratePercent}%（用户可调整的保险担保预估费率）` };
    return { ordinary, simple, preservation, guarantee };
  }

  function calculateRiskAgencyFeeBreakdown(amount) {
    let maximumFee = 0;
    const breakdown = [];
    riskAgencyTiers.forEach(tier => {
      const portion = Math.max(0, Math.min(amount, tier.upTo) - tier.from);
      if (portion <= 0) return;
      const fee = portion * tier.rate;
      maximumFee += fee;
      breakdown.push({ ...tier, portion, fee });
    });
    return { amount, maximumFee, breakdown };
  }

  function switchToolTab(tab) {
    const isInterest = tab === 'interest';
    const isFee = tab === 'fee';
    const isRisk = tab === 'risk';
    document.getElementById('interest-tool-pane').style.display = isInterest ? '' : 'none';
    document.getElementById('fee-tool-pane').classList.toggle('active', isFee);
    document.getElementById('risk-fee-tool-pane').classList.toggle('active', isRisk);
    document.getElementById('interest-tool-tab').classList.toggle('active', isInterest);
    document.getElementById('fee-tool-tab').classList.toggle('active', isFee);
    document.getElementById('risk-fee-tool-tab').classList.toggle('active', isRisk);
    document.getElementById('interest-tool-tab').setAttribute('aria-selected', String(isInterest));
    document.getElementById('fee-tool-tab').setAttribute('aria-selected', String(isFee));
    document.getElementById('risk-fee-tool-tab').setAttribute('aria-selected', String(isRisk));
    if (typeof window.renderFloatingIndex === 'function') window.renderFloatingIndex();
    if (isFee) document.getElementById('fee-amount').focus();
    if (isRisk) document.getElementById('risk-fee-amount').focus();
  }

  function renderArbitrationCaseTypes() {
    const institutionId = document.getElementById('arbitration-institution').value;
    const typeEl = document.getElementById('arbitration-case-type');
    const types = schedules[institutionId].types;
    typeEl.innerHTML = Object.entries(types).map(([key, value]) => `<option value="${key}">${escapeHtml(value.label)}</option>`).join('');
  }

  function calculateLegalFees(keepScroll, saveRecord = true) {
    const amount = Number(document.getElementById('fee-amount').value);
    const rate = Number(document.getElementById('guarantee-rate').value);
    const error = document.getElementById('fee-error-msg');
    if (!Number.isFinite(amount) || amount <= 0) { showFeeError('请输入大于 0 的标的金额'); return; }
    if (!Number.isFinite(rate) || rate < 0) { showFeeError('保险担保费率不能小于 0'); return; }
    error.textContent = ''; error.style.display = 'none';
    const court = calculateCourt(amount, rate);
    renderCourt(court);
    renderArbitration(amount);
    document.getElementById('fee-results').classList.add('visible');
    if (saveRecord) {
      const institutionId = document.getElementById('arbitration-institution').value;
      const caseTypeId = document.getElementById('arbitration-case-type').value;
      const institution = schedules[institutionId];
      const caseType = institution && institution.types[caseTypeId];
      saveCalculatorHistory('litigation_arbitration', amount, {
        guaranteeRate: rate,
        institutionId,
        caseTypeId,
        institutionName: institution ? institution.name : '',
        caseTypeLabel: caseType ? caseType.label : '',
        ordinaryFee: court.ordinary.value,
      });
    }
    if (typeof window.renderFloatingIndex === 'function') window.renderFloatingIndex();
    if (!keepScroll) document.getElementById('fee-results').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function calculateRiskAgencyFee(keepScroll, saveRecord = true) {
    const amount = Number(document.getElementById('risk-fee-amount').value);
    if (!Number.isFinite(amount) || amount <= 0) { showRiskFeeError('请输入大于 0 的标的金额'); return; }
    const error = document.getElementById('risk-fee-error-msg');
    error.textContent = ''; error.style.display = 'none';
    const result = calculateRiskAgencyFeeBreakdown(amount);
    const ratio = result.maximumFee / amount;
    document.getElementById('risk-fee-result-grid').innerHTML = [
      resultCard('律师服务费合计最高金额', { value: result.maximumFee, formula: '按五档累计计算；覆盖风险代理各个环节' }, true),
      resultCard('标的金额', { value: amount, formula: '最终实现的债权或减免的债务金额' }),
      resultTextCard('最高综合比例', percent(ratio), '最高金额 ÷ 标的金额'),
    ].join('');
    const lines = result.breakdown.map(item => `${item.label}：${money(item.portion)} 元 × ${percent(item.rate)} = ${money(item.fee)} 元。`);
    lines.push(`律师服务费最高金额 = ${result.breakdown.map(item => `${money(item.fee)} 元`).join(' + ')} = ${money(result.maximumFee)} 元。`);
    lines.push('该金额为风险代理各个环节收取的律师服务费合计上限。');
    document.getElementById('risk-fee-process').innerHTML = sourceBlock(SOURCES.riskAgency, lines);
    document.getElementById('risk-fee-results').classList.add('visible');
    if (saveRecord) saveCalculatorHistory('risk_agency', amount, { maximumFee: result.maximumFee });
    if (typeof window.renderFloatingIndex === 'function') window.renderFloatingIndex();
    if (!keepScroll) document.getElementById('risk-fee-results').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function calculatorHistoryUi(type) {
    return type === 'risk_agency'
      ? { keyword: 'risk-fee-history-keyword', start: 'risk-fee-history-filter-start', end: 'risk-fee-history-filter-end', empty: 'risk-fee-history-empty', list: 'risk-fee-history-list' }
      : { keyword: 'fee-history-keyword', start: 'fee-history-filter-start', end: 'fee-history-filter-end', empty: 'fee-history-empty', list: 'fee-history-list' };
  }
  function calculatorHistoryTitle(type) { return type === 'risk_agency' ? '风险代理律师费' : '诉讼仲裁费'; }
  function calculatorHistoryTime(record) {
    const time = new Date(record.createdAt);
    return Number.isNaN(time.getTime()) ? new Date(0) : time;
  }
  function formatCalculatorHistoryTime(record) {
    const time = calculatorHistoryTime(record);
    const now = new Date();
    return time.toDateString() === now.toDateString()
      ? `今天 ${String(time.getHours()).padStart(2, '0')}:${String(time.getMinutes()).padStart(2, '0')}`
      : `${time.getMonth() + 1}月${time.getDate()}日 ${String(time.getHours()).padStart(2, '0')}:${String(time.getMinutes()).padStart(2, '0')}`;
  }
  function calculatorHistorySummary(record) {
    const payload = record.payload || {};
    if (record.calculatorType === 'risk_agency') {
      return { title: `标的额 ${money(record.amount)} 元`, amount: payload.maximumFee, label: '律师费上限' };
    }
    const institution = payload.institutionName || '仲裁费用';
    const caseType = payload.caseTypeLabel ? ` · ${payload.caseTypeLabel}` : '';
    return { title: `标的额 ${money(record.amount)} 元 · ${institution}${caseType}`, amount: payload.ordinaryFee, label: '普通程序诉讼费' };
  }
  async function fetchCalculatorHistory(type, retried = false) {
    try {
      const response = await fetch(`/api/calculator-history/${encodeURIComponent(type)}`, { cache: 'no-store' });
      if (!response.ok) throw new Error('无法读取历史记录');
      const data = await response.json();
      calculatorHistory[type] = Array.isArray(data.history) ? data.history : [];
      calculatorHistoryLoadFailed[type] = false;
    } catch (error) {
      calculatorHistoryLoadFailed[type] = true;
      if (!retried) setTimeout(() => fetchCalculatorHistory(type, true), 700);
    }
    renderCalculatorHistory(type);
  }
  async function saveCalculatorHistory(type, amount, payload) {
    try {
      const response = await fetch('/api/calculator-history', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, keepalive: true,
        body: JSON.stringify({ calculatorType: type, amount, payload }),
      });
      if (!response.ok) throw new Error('无法保存历史记录');
      const data = await response.json();
      if (data.history) calculatorHistory[type] = [data.history, ...calculatorHistory[type]];
      renderCalculatorHistory(type);
    } catch (error) {
      // 计算结果仍可正常使用；本地数据库暂不可用时不阻断用户计算。
    }
  }
  function renderCalculatorHistory(type) {
    const ui = calculatorHistoryUi(type);
    const listEl = document.getElementById(ui.list);
    const emptyEl = document.getElementById(ui.empty);
    if (!listEl || !emptyEl) return;
    const keyword = (document.getElementById(ui.keyword)?.value || '').trim().toLowerCase();
    const start = document.getElementById(ui.start)?.value;
    const end = document.getElementById(ui.end)?.value;
    const startTime = start ? new Date(`${start}T00:00:00`).getTime() : null;
    const endTime = end ? new Date(`${end}T23:59:59.999`).getTime() : null;
    const list = calculatorHistory[type].filter(record => {
      const timestamp = calculatorHistoryTime(record).getTime();
      if (startTime !== null && timestamp < startTime) return false;
      if (endTime !== null && timestamp > endTime) return false;
      const summary = calculatorHistorySummary(record);
      const text = [record.note, record.amount, summary.title, summary.label].join(' ').toLowerCase();
      return !keyword || text.includes(keyword);
    }).sort((a, b) => Number(b.pinned) - Number(a.pinned) || calculatorHistoryTime(b) - calculatorHistoryTime(a));
    if (!list.length) {
      emptyEl.style.display = 'block';
      emptyEl.textContent = calculatorHistoryLoadFailed[type]
        ? '本地历史记录暂未加载成功，正在重试…'
        : calculatorHistory[type].length
        ? '当前检索条件下没有历史计算记录'
        : '暂无历史记录，点击“开始计算”后将自动保存到本地数据库';
      listEl.innerHTML = '';
      if (typeof window.renderFloatingIndex === 'function') window.renderFloatingIndex();
      return;
    }
    emptyEl.style.display = 'none';
    listEl.innerHTML = list.map(record => {
      const summary = calculatorHistorySummary(record);
      const amount = Number.isFinite(Number(summary.amount)) ? `¥${money(summary.amount)}` : '—';
      return `<div class="history-item${record.pinned ? ' pinned' : ''}" onclick="loadCalculatorHistory('${type}', ${Number(record.id)})">
        <div class="history-item-main">
          <input class="history-note" type="text" value="${escapeHtml(record.note || '')}" placeholder="自定义标题或关键词备忘" onclick="event.stopPropagation()" onchange="updateCalculatorHistoryNote('${type}', ${Number(record.id)}, this.value)" />
          <div class="history-item-title">${record.pinned ? '<span class="history-pin-label">已保存</span>' : ''}${escapeHtml(summary.title)}</div>
          <div class="history-item-meta"><span>${escapeHtml(summary.label)}</span><span>${formatCalculatorHistoryTime(record)}</span></div>
        </div>
        <div class="history-item-amount">${amount}</div>
        <div class="history-item-actions" onclick="event.stopPropagation()">
          <button class="history-btn${record.pinned ? ' history-btn-primary' : ''}" type="button" onclick="toggleCalculatorHistoryPinned('${type}', ${Number(record.id)})">${record.pinned ? '取消保存' : '保存'}</button>
          <button class="history-btn history-btn-primary" type="button" onclick="loadCalculatorHistory('${type}', ${Number(record.id)})">查看</button>
          <button class="history-btn history-btn-danger" type="button" onclick="deleteCalculatorHistory('${type}', ${Number(record.id)})">删除</button>
        </div>
      </div>`;
    }).join('');
    if (typeof window.renderFloatingIndex === 'function') window.renderFloatingIndex();
  }
  async function updateCalculatorHistory(type, id, update) {
    try {
      const response = await fetch(`/api/calculator-history/${id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(update),
      });
      if (!response.ok) throw new Error('无法更新历史记录');
      const data = await response.json();
      const index = calculatorHistory[type].findIndex(record => Number(record.id) === Number(id));
      if (index >= 0 && data.history) calculatorHistory[type][index] = data.history;
      renderCalculatorHistory(type);
    } catch (error) {}
  }
  function updateCalculatorHistoryNote(type, id, note) { updateCalculatorHistory(type, id, { note }); }
  function toggleCalculatorHistoryPinned(type, id) {
    const record = calculatorHistory[type].find(item => Number(item.id) === Number(id));
    if (record) updateCalculatorHistory(type, id, { pinned: !record.pinned });
  }
  async function deleteCalculatorHistory(type, id) {
    try {
      const response = await fetch(`/api/calculator-history/${id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error('无法删除历史记录');
      calculatorHistory[type] = calculatorHistory[type].filter(item => Number(item.id) !== Number(id));
      renderCalculatorHistory(type);
    } catch (error) {}
  }
  async function clearCalculatorHistory(type) {
    const removable = calculatorHistory[type].filter(item => !item.pinned).length;
    if (!removable) { alert('没有可清空的历史记录；已保存的记录会保留。'); return; }
    if (!confirm(`确定要清空${calculatorHistoryTitle(type)}的 ${removable} 条历史记录吗？已保存的记录会保留。`)) return;
    try {
      const response = await fetch(`/api/calculator-history?calculatorType=${encodeURIComponent(type)}`, { method: 'DELETE' });
      if (!response.ok) throw new Error('无法清空历史记录');
      calculatorHistory[type] = calculatorHistory[type].filter(item => item.pinned);
      renderCalculatorHistory(type);
    } catch (error) {}
  }
  function clearCalculatorHistoryFilter(type) {
    const ui = calculatorHistoryUi(type);
    document.getElementById(ui.keyword).value = '';
    document.getElementById(ui.start).value = '';
    document.getElementById(ui.end).value = '';
    renderCalculatorHistory(type);
  }
  function loadCalculatorHistory(type, id) {
    const record = calculatorHistory[type].find(item => Number(item.id) === Number(id));
    if (!record) return;
    const payload = record.payload || {};
    if (type === 'risk_agency') {
      document.getElementById('risk-fee-amount').value = record.amount;
      updateFeeAmountChinese('risk-fee-amount-chinese', record.amount);
      calculateRiskAgencyFee(false, false);
      return;
    }
    document.getElementById('fee-amount').value = record.amount;
    document.getElementById('guarantee-rate').value = payload.guaranteeRate ?? 0.06;
    updateFeeAmountChinese('fee-amount-chinese', record.amount);
    const institutionEl = document.getElementById('arbitration-institution');
    institutionEl.value = schedules[payload.institutionId] ? payload.institutionId : 'gzac';
    renderArbitrationCaseTypes();
    const caseTypeEl = document.getElementById('arbitration-case-type');
    if (schedules[institutionEl.value].types[payload.caseTypeId]) caseTypeEl.value = payload.caseTypeId;
    calculateLegalFees(false, false);
  }

  function renderCourt(result) {
    const courtCards = [
      ['一审普通程序诉讼费', result.ordinary, true], ['一审简易程序诉讼费', result.simple],
    ];
    const preservationCards = [
      ['财产保全申请费', result.preservation, true], ['保险担保费（预估）', result.guarantee],
    ];
    document.getElementById('court-fee-grid').innerHTML = courtCards.map(([label, fee, emphasis]) => resultCard(label, fee, emphasis)).join('');
    document.getElementById('preservation-fee-grid').innerHTML = preservationCards.map(([label, fee, emphasis]) => resultCard(label, fee, emphasis)).join('');
    document.getElementById('court-fee-process').innerHTML = sourceBlock(SOURCES.court, [
      '适用：财产性案件一审案件受理费（普通程序、简易程序）。',
      `普通程序：${escapeHtml(result.ordinary.formula)}；结果 ${money(result.ordinary.value)} 元。`,
      `简易程序：${escapeHtml(result.simple.formula)}；按普通程序结果减半。`,
    ]);
    document.getElementById('preservation-fee-process').innerHTML = sourceBlock(SOURCES.court, [
      `保全费：${escapeHtml(result.preservation.formula)}。`,
      `保险担保费：${escapeHtml(result.guarantee.formula)}。`,
    ]);
  }

  function renderArbitration(amount) {
    const institutionId = document.getElementById('arbitration-institution').value;
    const typeId = document.getElementById('arbitration-case-type').value;
    const institution = schedules[institutionId];
    const type = institution.types[typeId];
    const data = type.calculate(amount);
    const source = type.source || institution.source;
    let cards;
    if (data.totalOnly) {
      cards = [resultCard('预缴仲裁费', data.total, true), resultTextCard('受理费', '未单列', data.note), resultTextCard('处理费', '未单列', data.note)];
    } else {
      const total = (data.acceptance.value || 0) + (data.processing.value || 0);
      cards = [
        resultCard('案件受理费', data.acceptance), resultCard('案件处理费', data.processing),
        resultCard(data.processing.unavailable ? '可确定费用小计' : '仲裁费合计', { value: total, formula: data.processing.unavailable ? '未包含按实际支出收取的案件处理费' : '案件受理费 + 案件处理费' }, true),
      ];
    }
    document.getElementById('arbitration-fee-grid').innerHTML = cards.join('');
    const lines = data.totalOnly
      ? [data.total.formula, data.note]
      : [`案件受理费：${data.acceptance.formula}。`, `案件处理费：${data.processing.formula}。`, data.processing.unavailable ? '处理费未计入小计。' : '仲裁费合计 = 案件受理费 + 案件处理费。'];
    document.getElementById('arbitration-fee-process').innerHTML = sourceBlock(source, [
      `适用：${institution.name} · ${type.label}${type.description ? `（${type.description}）` : ''}。`, ...lines,
    ]);
  }

  function resultCard(label, fee, emphasis) {
    if (fee.unavailable && fee.value === undefined) return resultTextCard(label, '以通知为准', fee.formula, emphasis);
    return `<div class="fee-result-item${emphasis ? ' emphasis' : ''}"><div class="fee-result-label">${escapeHtml(label)}</div><div class="fee-result-value">¥${money(fee.value)}<span class="unit">元</span></div><div class="fee-result-note">${escapeHtml(fee.formula || '')}</div></div>`;
  }
  function resultTextCard(label, value, note, emphasis) {
    return `<div class="fee-result-item${emphasis ? ' emphasis' : ''}"><div class="fee-result-label">${escapeHtml(label)}</div><div class="fee-result-value" style="font-size:18px">${escapeHtml(value)}</div><div class="fee-result-note">${escapeHtml(note || '')}</div></div>`;
  }
  function sourceBlock(source, lines) {
    return `<strong>计算过程与依据</strong><ul>${lines.map(line => `<li>${line}</li>`).join('')}</ul><div style="margin-top:7px">依据：<a class="fee-source-link" href="${source.url}" target="_blank" rel="noopener noreferrer">${escapeHtml(source.title)}</a>；${escapeHtml(source.effective)}。<br>本工具核验日期：${VERIFIED_ON}。</div>`;
  }
  function showFeeError(message) {
    const error = document.getElementById('fee-error-msg');
    error.textContent = message; error.style.display = 'block';
    error.style.cssText += ';margin-top:14px;padding:10px 12px;border-radius:8px;background:#fff1f2;color:#be123c;border:1px solid #fecdd3;font-size:13px;';
  }
  function showRiskFeeError(message) {
    const error = document.getElementById('risk-fee-error-msg');
    error.textContent = message; error.style.display = 'block';
    error.style.cssText += ';margin-top:14px;padding:10px 12px;border-radius:8px;background:#fff1f2;color:#be123c;border:1px solid #fecdd3;font-size:13px;';
  }
  function updateFeeAmountChinese(displayId, value) {
    const display = document.getElementById(displayId);
    if (!display) return;
    const text = value && typeof window.numberToChinese === 'function'
      ? window.numberToChinese(value)
      : '大写：人民币零元整';
    display.textContent = text;
    display.dataset.copy = text;
  }
  function rateNumberToChinese(value) {
    const digits = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九'];
    const units = ['', '十', '百', '千'];
    const number = Number(value);
    if (!Number.isFinite(number) || number === 0) return '零';
    if (!Number.isInteger(number) || number > 9999) return String(value).replace(/\d/g, digit => digits[Number(digit)]).replace('.', '点');
    let rest = number;
    let result = '';
    let unitIndex = 0;
    while (rest > 0) {
      const digit = rest % 10;
      if (digit) result = `${digits[digit]}${units[unitIndex]}${result}`;
      else if (result && !result.startsWith('零')) result = `零${result}`;
      rest = Math.floor(rest / 10);
      unitIndex += 1;
    }
    return result.replace(/零+/g, '零').replace(/零$/, '').replace(/^一十/, '十');
  }
  function ratePercentToChinese(ratePercent) {
    const rate = Number(ratePercent);
    if (!Number.isFinite(rate) || rate < 0) return '请输入有效费率';
    if (rate === 0) return '零费率';
    const fraction = rate / 100;
    const denominators = [100, 1000, 10000, 100000, 1000000];
    const labels = ['百分之', '千分之', '万分之', '十万分之', '百万分之'];
    for (let index = 0; index < denominators.length; index += 1) {
      const numerator = fraction * denominators[index];
      if (Math.abs(numerator - Math.round(numerator)) < 1e-9 && numerator > 0 && numerator <= 9999) {
        return `${labels[index]}${rateNumberToChinese(Math.round(numerator))}`;
      }
    }
    return `约万分之${rateNumberToChinese((fraction * 10000).toFixed(4).replace(/0+$/, '').replace(/\.$/, ''))}`;
  }
  function updateGuaranteeRateChinese(value) {
    const display = document.getElementById('guarantee-rate-chinese');
    if (display) display.textContent = `费率：${ratePercentToChinese(value)}`;
  }
  async function copyFeeAmountChinese(displayId) {
    const display = document.getElementById(displayId);
    if (!display || !display.dataset.copy) return;
    try {
      await navigator.clipboard.writeText(display.dataset.copy);
      const original = display.textContent;
      display.textContent = '已复制 ✓';
      display.style.color = '#c41e3a';
      setTimeout(() => { display.textContent = original; display.style.color = ''; }, 1500);
    } catch (e) {}
  }
  function money(value) { return Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function percent(value) { return `${(value * 100).toLocaleString('zh-CN', { maximumFractionDigits: 4 })}%`; }
  function escapeHtml(value) { return String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char])); }

  function init() {
    if (initialized) return;
    const institutionEl = document.getElementById('arbitration-institution');
    if (!institutionEl) return;
    initialized = true;
    institutionEl.innerHTML = Object.entries(schedules).map(([key, item]) => `<option value="${key}">${escapeHtml(item.name)}</option>`).join('');
    institutionEl.value = 'gzac';
    renderArbitrationCaseTypes();
    const feeAmountEl = document.getElementById('fee-amount');
    const riskFeeAmountEl = document.getElementById('risk-fee-amount');
    const guaranteeRateEl = document.getElementById('guarantee-rate');
    feeAmountEl.addEventListener('input', () => updateFeeAmountChinese('fee-amount-chinese', feeAmountEl.value));
    feeAmountEl.addEventListener('keydown', event => { if (event.key === 'Enter') calculateLegalFees(); });
    riskFeeAmountEl.addEventListener('input', () => updateFeeAmountChinese('risk-fee-amount-chinese', riskFeeAmountEl.value));
    riskFeeAmountEl.addEventListener('keydown', event => { if (event.key === 'Enter') calculateRiskAgencyFee(); });
    guaranteeRateEl.addEventListener('input', () => updateGuaranteeRateChinese(guaranteeRateEl.value));
    updateFeeAmountChinese('fee-amount-chinese', feeAmountEl.value);
    updateFeeAmountChinese('risk-fee-amount-chinese', riskFeeAmountEl.value);
    updateGuaranteeRateChinese(guaranteeRateEl.value);
    fetchCalculatorHistory('litigation_arbitration');
    fetchCalculatorHistory('risk_agency');
  }

  window.switchToolTab = switchToolTab;
  window.renderArbitrationCaseTypes = renderArbitrationCaseTypes;
  window.calculateLegalFees = calculateLegalFees;
  window.calculateRiskAgencyFee = calculateRiskAgencyFee;
  window.copyFeeAmountChinese = copyFeeAmountChinese;
  window.renderCalculatorHistory = renderCalculatorHistory;
  window.clearCalculatorHistoryFilter = clearCalculatorHistoryFilter;
  window.clearCalculatorHistory = clearCalculatorHistory;
  window.updateCalculatorHistoryNote = updateCalculatorHistoryNote;
  window.toggleCalculatorHistoryPinned = toggleCalculatorHistoryPinned;
  window.deleteCalculatorHistory = deleteCalculatorHistory;
  window.loadCalculatorHistory = loadCalculatorHistory;
  window.__feeCalculator = { formula, calculateCourt, calculateRiskAgencyFeeBreakdown, schedules, money };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
  // 此脚本位于页面末尾；即使原生壳提前触发 DOMContentLoaded，也确保完成初始化。
  setTimeout(init, 0);
  window.addEventListener('pageshow', () => {
    init();
    if (initialized) {
      fetchCalculatorHistory('litigation_arbitration');
      fetchCalculatorHistory('risk_agency');
    }
  });
})();
