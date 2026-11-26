const fs = require('fs'), assert = require('assert'), vm = require('vm'), acorn = require('acorn');
const src = fs.readFileSync('frontend/app.js', 'utf8');
const ast = acorn.parse(src, {ecmaVersion: 'latest'});
const declarations = new Map(ast.body.filter(n => n.type === 'FunctionDeclaration').map(n => [n.id.name, src.slice(n.start, n.end)]));
function extract(name) { assert(declarations.has(name), name); return declarations.get(name); }
(async () => {
  const storage = new Map(), saved = [], opened = [], input = {value: '保留草稿', dispatchEvent(){}, focus(){}};
  const frame = {}, foreign = {};
  const context = vm.createContext({console, URLSearchParams, Event, location: {origin: 'http://fada.test'},
    window: {addEventListener(){}},
    document: {getElementById: id => id === 'fada-tab' ? {querySelector: () => ({contentWindow: frame})} : id === 'ask-input' ? input : null},
    localStorage: {getItem: k => storage.get(k) || null, setItem: (k,v) => storage.set(k,v), removeItem: k => storage.delete(k), key: i => [...storage.keys()][i], get length(){return storage.size;}},
    openAskPanel(opts){opened.push(opts);}, currentAskWorkspaceTab(){return null;}, saveTabsState(){},
    apiFetch: async (url, options) => {if (!options) return {conversations: []}; saved.push(JSON.parse(options.body)); return {version: 1};},
  });
  vm.runInContext(`var tabState={activeTabId:'fada-tab',tabs:[{id:'fada-tab',type:'fada'}]},TAB_TYPES={FADA_WANG:'fada'},askContext=null,askHistoryLoadPromise=null,askHistoryCache=new Map(),askHistoryVersions=new Map(),askHistoryFiledCases=new Map();\n` +
    ['normaliseFadaAskContext','openFadaAiWorkspace','handleFadaAiMessage','getStableAskHistoryHash','getAskBaseHistoryKey','getAskScopeLabel','sourceModeForAskContext','ensureAskHistoryLoaded'].map(extract).join('\n'), context);
  context.frame = frame; context.foreign = foreign;
  vm.runInContext(`var payload={type:'apex:open-fada-ai',version:1,context:{type:'fada',ids:['fada-22222222','fada-11111111'],title:'当前筛选结果'},question:'单条追问'};
  handleFadaAiMessage({origin:'https://foreign.test',source:frame,data:payload});
  handleFadaAiMessage({origin:location.origin,source:foreign,data:payload});`, context);
  assert.equal(opened.length, 0, 'only registered same-origin frames may open a scope');
  vm.runInContext('handleFadaAiMessage({origin:location.origin,source:frame,data:payload});', context);
  assert.equal(opened.length, 1); assert.equal(input.value, '保留草稿\n\n单条追问');
  assert.equal(vm.runInContext('sourceModeForAskContext(askContext)', context), 'fada');
  assert.match(vm.runInContext('getAskScopeLabel(askContext)', context), /法答网/);
  const all = vm.runInContext("getAskBaseHistoryKey({type:'fada',ids:null})", context);
  const empty = vm.runInContext("getAskBaseHistoryKey({type:'fada',ids:[]})", context);
  assert.notEqual(all, empty);
  assert.equal(vm.runInContext("getAskBaseHistoryKey(askContext)", context), vm.runInContext("getAskBaseHistoryKey({type:'fada',ids:['fada-11111111','fada-22222222']})", context));
  assert.equal(vm.runInContext("normaliseFadaAskContext({type:'fada',ids:['invalid']})", context), null);
  storage.set('fada_ai_ask_history', JSON.stringify([{id:'old',role:'ai',content:'旧回答',citedSources:[{id:'fada-11111111'}],ts:1}]));
  await vm.runInContext('ensureAskHistoryLoaded()', context);
  assert.equal(saved.length, 1); assert.equal(saved[0].records[0].citedSources[0].source_type, 'fada');
  assert.equal(storage.has('fada_ai_ask_history'), false);
  // The old key must survive a failed import, and retry once persistence recovers.
  storage.set('fada_ai_ask_history', JSON.stringify([{id:'retry',role:'user',content:'重试',ts:2}]));
  context.apiFetch = async (url, options) => {if (!options) return {conversations: []}; throw new Error('fixture unavailable');};
  await vm.runInContext('askHistoryLoadPromise=null;ensureAskHistoryLoaded()', context);
  assert(storage.has('fada_ai_ask_history'));

  // Exercise the actual Fada page entry using its current view selection.
  const page = fs.readFileSync('fada-wang/fada_wang_search.html','utf8');
  assert(!page.includes('id="fadaAiModelSelect"')); assert(!page.includes("fetch('/api/fada-ask'"));
  const sent = [];
  const fada = vm.createContext({URLSearchParams, location:{origin:'http://fada.test'},
    window:{parent:{postMessage:(...args)=>sent.push(args)}}, activeFadaFilters:{procedure:'执行程序'},
    document:{getElementById:()=>({value:''})},getFilteredFadaData:()=>[{id:'fada-11111111'}]});
  const fn = page.slice(page.indexOf('        function openFadaAiPanel('), page.indexOf('    </script>',page.indexOf('        function openFadaAiPanel(')));
  vm.runInContext(fn+'\nopenFadaAiPanel();',fada);
  assert.equal(sent[0][1],'http://fada.test'); assert.equal(sent[0][0].context.ids[0],'fada-11111111');
  fada.getFilteredFadaData=()=>[];vm.runInContext('openFadaAiPanel()',fada);assert.equal(sent[1][0].context.ids.length,0);
  vm.runInContext("activeFadaFilters={};openFadaAiPanel();openFadaAiPanel({id:'fada-22222222',question:'单条问题'});",fada);
  assert.equal(sent[2][0].context.ids,null);assert.equal(sent[3][0].context.ids[0],'fada-22222222');assert(sent[3][0].question.includes('单条问题'));
  console.log('Fada entry, scope identity, draft preservation, source validation and legacy import passed');
})().catch(error => { console.error(error); process.exit(1); });
