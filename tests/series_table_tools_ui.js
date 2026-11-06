/* Anonymous functional checks for table tools, no live API or business files. */
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert'),acorn=require('acorn');
const source=fs.readFileSync(path.join(__dirname,'../frontend/case-manager.js'),'utf8'),ast=acorn.parse(source,{ecmaVersion:'latest'});
const names=['seriesToolModels','seriesFindMatches','replaceSeriesText','seriesSequenceValue','fillSeriesCells','pasteSeriesSpecial'];
const code=names.map(name=>{const node=ast.body.find(n=>n.type==='FunctionDeclaration'&&n.id.name===name);assert(node,name);return source.slice(node.start,node.end)}).join('\n');
const c=vm.createContext({console,Set,Map,BigInt,Date});
vm.runInContext(`const items=[{id:101,memo:'匿名.*甲',case_no:'00123'},{id:102,memo:'匿名.*乙',case_no:'00456'}],columns=[{key:'memo'},{key:'case_no'}];
const state={seriesWorkspace:{children:items},seriesToolCells:items.flatMap(item=>columns.map(column=>({childId:item.id,field:column.key}))),seriesFindIndex:-1};
const fields={seriesFindText:{value:'.*'},seriesReplaceText:{value:'$1'},seriesFindSelectionOnly:{checked:true},seriesFindCase:{checked:true},seriesFillOverwrite:{checked:true},seriesSequenceStart:{value:'0001'},seriesSequenceStep:{value:'2'},seriesFillValue:{value:'同值'}};
const $=id=>fields[id],currentSeriesVisibleColumns=()=>columns,seriesFilteredItems=()=>items,seriesCellValue=(item,key)=>item[key],seriesCellEditable=column=>!column.readonly,cloneSeriesCellFormat=f=>JSON.parse(JSON.stringify(f||{}));
let lastUpdates=[],lastFormats=[],messages=[];
async function saveSeriesCellBatch(updates){lastUpdates=updates;updates.forEach(update=>{items.find(item=>item.id===update.childId)[update.field]=update.value})}
async function saveSeriesCellFormatBatch(updates){lastFormats=updates}
function renderSeriesChildTable(){}function toast(message){messages.push(message)}
${code}`,c);
(async()=>{
 assert.equal(vm.runInContext('seriesFindMatches().length',c),2);
 await vm.runInContext('replaceSeriesText(true)',c);
 assert.equal(vm.runInContext('items[0].memo',c),'匿名$1甲');
 vm.runInContext("items[0].memo='甲甲';state.seriesToolCells=[{childId:101,field:'memo'}];fields.seriesFindText.value='甲';fields.seriesReplaceText.value='乙';state.seriesFindIndex=0;",c);
 assert.equal(vm.runInContext('seriesFindMatches().length',c),2);await vm.runInContext('replaceSeriesText(false)',c);assert.equal(vm.runInContext('items[0].memo',c),'乙甲');
 vm.runInContext('state.seriesToolCells=items.flatMap(item=>columns.map(column=>({childId:item.id,field:column.key})))',c);
 assert.equal(vm.runInContext("seriesSequenceValue('999999999999999999999',1,1)",c),'1000000000000000000000');
 assert.equal(vm.runInContext("seriesSequenceValue('2024-02-28',1,1)",c),'2024-02-29');
 await vm.runInContext("fillSeriesCells('sequence')",c);
 assert.equal(vm.runInContext('items[0].memo',c),'0001');assert.equal(vm.runInContext('items[1].memo',c),'0003');
 vm.runInContext("state.seriesToolCells=[{childId:101,field:'memo'}];state.seriesTableClipboard={matrix:[['甲','乙'],['丙','丁']],formats:[[{align:'right'},{}],[{},{}]]};",c);
 await vm.runInContext("pasteSeriesSpecial('transpose')",c);
 assert.equal(vm.runInContext('items[0].case_no',c),'丙');assert.equal(vm.runInContext('items[1].memo',c),'乙');
 await vm.runInContext("pasteSeriesSpecial('formats')",c);assert.equal(vm.runInContext('lastFormats[0].format.align',c),'right');
 vm.runInContext("state.seriesToolCells=[{childId:101,field:'memo'},{childId:102,field:'case_no'}];lastUpdates=[];",c);
 await vm.runInContext("pasteSeriesSpecial('values')",c);assert.equal(vm.runInContext('lastUpdates.length',c),0);assert(vm.runInContext('messages.at(-1).includes("形状")',c));
 console.log('Series table literal replacement, exact sequence, transpose, formats and shape guards passed');
})().catch(e=>{console.error(e);process.exit(1)});
