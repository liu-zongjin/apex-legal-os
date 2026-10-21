import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
function dashboard(){
 const elements=new Map();
 const element=()=>({children:[],style:{},append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},addEventListener(){}});
 const context={Intl,document:{hidden:true,body:{dataset:{view:'website'}},createElement:element,getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},querySelectorAll(){return [];},addEventListener(){}},setInterval(){}};
 const source=fs.readFileSync(new URL('../public/website-admin.js',import.meta.url),'utf8').replace(/\}\)\(\);\s*$/, 'globalThis.renderDownloads=renderDownloads;globalThis.downloadRows=downloadRows;})();');
 vm.runInNewContext(source,context);
 return {context,values:()=>elements.get('web-downloads').children.map(row=>row.children.map(cell=>cell.textContent))};
}
test('download table shows all package targets, zero states and click shares',()=>{
 const {context,values}=dashboard();
 context.renderDownloads([{label:'windows',count:3,visitors:2},{label:'arm',count:1,visitors:1}]);
 assert.deepEqual(values(),[['macOS · Apple 芯片','1','1','25.0%'],['macOS · Intel','0','0','0.0%'],['Windows','3','2','75.0%']]);
 context.renderDownloads([]);
 assert.deepEqual(values(),[['macOS · Apple 芯片','0','0','—'],['macOS · Intel','0','0','—'],['Windows','0','0','—']]);
});
