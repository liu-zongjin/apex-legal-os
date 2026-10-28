const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),acorn=require('acorn');
const source=fs.readFileSync('frontend/case-manager.js','utf8');
const names=['closeSeriesWorkspace','caseUpdatedValue','sortCasesForList'];
const funcs=acorn.parse(source,{ecmaVersion:'latest'}).body.filter(n=>n.type==='FunctionDeclaration'&&names.includes(n.id.name)).map(n=>source.slice(n.start,n.end)).join('\n');
(async()=>{
 const context=vm.createContext({Promise,Set,console});
 vm.runInContext(`
 let finishSave,loads=0;
 const pending=new Promise(resolve=>{finishSave=resolve}),seriesPendingCellSaves=new Set([pending]);
 const state={seriesWorkspace:{id:2},seriesSelectedChildIds:new Set(),seriesCellMultiSelection:new Set()};
 const document={body:{style:{overflow:'hidden'}}};
 const $=()=>({classList:{remove(){}},setAttribute(){}});
 function closeSeriesFilterPopover(){}function closeSeriesSide(){}function closeSeriesDeleteDialog(){}function clearSeriesHash(){}function notifyCaseManagerContext(){}function currentCaseManagerPageLabel(){}function toast(message){throw Error(message)}
 async function loadList(){loads++}
 ${funcs}
 closeSeriesWorkspace();
 `,context);
 assert.equal(vm.runInContext('state.seriesWorkspace',context),null);
 assert.equal(vm.runInContext('loads',context),0,'do not reload before an in-flight edit commits');
 vm.runInContext('finishSave()',context);await new Promise(resolve=>setImmediate(resolve));
 assert.equal(vm.runInContext('loads',context),1);
 assert.equal(vm.runInContext(`sortCasesForList([
 {id:1,pinned:true,updated_at:'2026-01-01T08:00:00'},
 {id:2,pinned:true,case_kind:'series',updated_at:'2026-03-02T08:00:00'},
 {id:3,pinned:false,updated_at:'2026-04-01T08:00:00'}
 ]).map(x=>x.id).join(',')`,context),'2,1,3');
 console.log('Series close waits for saves and list sorting retains pin priority');
})().catch(e=>{console.error(e);process.exit(1)});
