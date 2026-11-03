import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
function dashboard(){
 const elements=new Map();
 const element=()=>({children:[],style:{},append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},addEventListener(){}});
 const context={Intl,document:{hidden:true,body:{dataset:{view:'website'}},createElement:element,getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},querySelectorAll(){return [];},addEventListener(){}},setInterval(){}};
 const source=fs.readFileSync(new URL('../public/website-admin.js',import.meta.url),'utf8').replace(/\}\)\(\);\s*$/, 'globalThis.renderDownloads=renderDownloads;globalThis.downloadRows=downloadRows;globalThis.renderRows=renderRows;globalThis.valueLabel=valueLabel;})();');
 vm.runInNewContext(source,context);
 return {context,elements,values:()=>elements.get('web-downloads').children.map(row=>row.children.map(cell=>cell.textContent))};
}
test('download table shows all package targets, zero states and click shares',()=>{
 const {context,values}=dashboard();
 context.renderDownloads([{label:'windows',count:3,visitors:2},{label:'arm',count:1,visitors:1}]);
 assert.deepEqual(values(),[['macOS · Apple 芯片','1','1','25.0%'],['macOS · Intel','0','0','0.0%'],['Windows','3','2','75.0%']]);
 context.renderDownloads([]);
 assert.deepEqual(values(),[['macOS · Apple 芯片','0','0','—'],['macOS · Intel','0','0','—'],['Windows','0','0','—']]);
});
test('interaction panels name the current controls, public chapters and zero states',()=>{
 const {context,elements}=dashboard();
 assert.equal(context.valueLabel('copy_targets','mac'),'Mac 安装指令');
 assert.equal(context.valueLabel('copy_targets','windows'),'Windows 安装指令');
 assert.equal(context.valueLabel('tab_targets','arm'),'macOS · Apple 芯片');
 assert.equal(context.valueLabel('chapter_targets','03'),'03 · 文书合集');
 assert.equal(context.valueLabel('chapter_targets','99'),'章节 99');
 assert.equal(context.valueLabel('assistant_targets','workbuddy'),'WorkBuddy（腾讯）');
 assert.equal(context.valueLabel('sections','agent-install'),'AI 辅助源码安装');
 assert.equal(context.valueLabel('landings','watch'),'功能介绍视频');
 context.renderRows('tab_targets',[{label:'arm',count:2,visitors:1}]);
 const rows=elements.get('web-tab-targets').children;
 assert.equal(rows.length,3);
 assert.equal(rows[0].children[0].children[0].textContent,'macOS · Apple 芯片');
 assert.equal(rows[0].children[0].children[1].textContent,'2 次 · 1 位访客');
 assert.equal(rows[2].children[0].children[0].textContent,'Windows');
 assert.equal(rows[2].children[0].children[1].textContent,'0 次 · 0 位访客');
});
