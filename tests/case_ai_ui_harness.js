const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync('frontend/app.js','utf8');
function extract(name) {
  const start = source.indexOf('function '+name+'(');
  assert(start >= 0);
  return source.slice(start, source.indexOf('\nfunction ', start+1));
}
const context = vm.createContext({URLSearchParams});
vm.runInContext(extract('normaliseCaseDatabaseCitation')+extract('cleanCaseAiContent'), context);
const sourceData = {source_type:'case_database', record_count:5, excerpt:'[{"id":1460,"title":"开庭","case_id":54,"case_title":"匿名甲案件"},{"id":222,"case_id":16,"case_title":"匿名乙案件","notes":"被截断'};
const result = context.normaliseCaseDatabaseCitation(sourceData);
assert.equal(result.case_links.length,2);
assert.equal(result.case_links[0].case_id,54);
assert.equal(result.case_links[0].case_title,'匿名甲案件');
assert(!result.case_links.some(link=>link.case_id===1460));
assert(!result.excerpt.includes('case_id'));
const content = context.cleanCaseAiContent('[citation:1] has_more=false court_contact current_stage pending');
assert.equal(content,'【依据1】 结果已完整返回 案件联系人 当前阶段 未完成');
assert.equal(sourceData.excerpt[0],'[');
console.log('Case AI UI compatibility checks passed');

vm.runInContext(extract('caseManagerFrameSrc'),context);
const frameUrl = context.caseManagerFrameSrc({id:'tab_1',data:{viewState:{caseId:54}}});
assert.equal(new URLSearchParams(frameUrl.split('?')[1]).get('case_id'),'54');
vm.runInContext("var tabState={tabs:[]}; var TAB_TYPES={CASE_MANAGER:'case_manager'}; var selected=null; function openCaseManagerTab(view){selected=view.caseId;} function switchTab(id){selected=id;}"+extract('openCaseDatabaseCitationCase'),context);
context.openCaseDatabaseCitationCase(54);
assert.equal(vm.runInContext('selected',context),54);
console.log('Case detail navigation checks passed');
