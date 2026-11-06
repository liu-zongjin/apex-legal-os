/* Selection identity and keyboard regressions, anonymous data only. */
const fs=require('fs'),vm=require('vm'),assert=require('assert'),acorn=require('acorn');
const source=fs.readFileSync(require('path').join(__dirname,'../frontend/case-manager.js'),'utf8');
const ast=acorn.parse(source,{ecmaVersion:'latest'});
const names=['seriesMultiCellKey','seriesSelectionBounds','seriesSelectedCellKeySet','seriesSelectionAnchorBounds','selectSeriesAxis','handleSeriesWorkspaceKeydown'];
const code=names.map(name=>{const n=ast.body.find(n=>n.type==='FunctionDeclaration'&&n.id.name===name);assert(n,name);return source.slice(n.start,n.end)}).join('\n');
const context=vm.createContext({Set,Map,console});
vm.runInContext(`const columns=[{key:'memo'},{key:'case_no'},{key:'court'}],items=[{id:101},{id:102},{id:103},{id:104}];
const state={seriesWorkspaceTab:'children',seriesTableEditMode:true,seriesCellSelection:null,seriesCellMultiSelection:new Set(),seriesSelectedChildIds:new Set()};
const currentSeriesVisibleColumns=()=>columns,seriesFilteredItems=()=>items;
const document={querySelectorAll:()=>[],querySelector:()=>null};
function applySeriesCellSelectionStyles(){} function updateSeriesSelectionSummary(){}
const event=(extra={})=>({preventDefault(){},stopPropagation(){},target:{closest:()=>null},...extra});
${code}
selectSeriesAxis(event(),'row',0);selectSeriesAxis(event({shiftKey:true}),'row',2);
if(seriesSelectedCellKeySet().size!==9)throw Error('continuous rows');
selectSeriesAxis(event(),'row',0);selectSeriesAxis(event({metaKey:true}),'row',3);
if(seriesSelectedCellKeySet().size!==6||!state.seriesSelectedChildIds.has(104)||state.seriesSelectedChildIds.has(102))throw Error('nonconsecutive rows');
selectSeriesAxis(event(),'column',0);selectSeriesAxis(event({ctrlKey:true}),'column',2);
if(seriesSelectedCellKeySet().size!==8)throw Error('nonconsecutive columns');
handleSeriesWorkspaceKeydown(event({key:'a',metaKey:true}));if(seriesSelectedCellKeySet().size!==12)throw Error('select all');
handleSeriesWorkspaceKeydown(event({key:'Escape'}));if(seriesSelectedCellKeySet().size!==0)throw Error('clear selection');
state.seriesCellSelection={startRow:0,startColumn:0,endRow:0,endColumn:0};
handleSeriesWorkspaceKeydown(event({key:'ArrowDown',shiftKey:true}));if(seriesSelectedCellKeySet().size!==2)throw Error('keyboard range');
handleSeriesWorkspaceKeydown(event({key:'ArrowDown',isComposing:true}));if(state.seriesCellSelection.endRow!==1)throw Error('IME navigation');
`,context);
console.log('Series table row/column selection and keyboard regression passed');
