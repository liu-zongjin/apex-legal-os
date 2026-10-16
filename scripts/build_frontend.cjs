// Canonical app.js/style.css remain reviewable; generated assets are reproducible.
const fs = require('fs');
const path = require('path');
const acorn = require('acorn');
const terser = require('terser');
const postcss = require('postcss');
const cssnano = require('cssnano');
const root = path.resolve(__dirname, '..');
async function build() {
  const source = fs.readFileSync(path.join(root,'frontend/app.js'),'utf8');
  const tree = acorn.parse(source,{ecmaVersion:'latest'});
  const start = source.indexOf('   AI增强面板\n');
  const end = source.indexOf('async function restartLegalKnowledgeBase');
  if(start<0 || end<0) throw Error('Missing reviewed feature boundaries');
  const functions = tree.body.filter(n=>n.type==='FunctionDeclaration'&&n.async&&n.start>start&&n.start<end);
  const chunk = ['window.StellaAsyncFeatures = window.StellaAsyncFeatures || {};'];
  let core=source;
  for(const node of [...functions].reverse()) {
    const name=node.id.name;
    chunk.push(`window.StellaAsyncFeatures[${JSON.stringify(name)}]=(${source.slice(node.start,node.end)});`);
    core=core.slice(0,node.start)+`async function ${name}(...args){await window.StellaFeatures.loadAI();return window.StellaAsyncFeatures[${JSON.stringify(name)}].apply(this,args);}`+core.slice(node.end);
  }
  const options={compress:false,mangle:false,format:{comments:false}};
  const output = await terser.minify(core,options);
  const lazy = await terser.minify(chunk.join('\n'),options);
  fs.writeFileSync(path.join(root,'frontend/app-bootstrap.js'), output.code+'\n');
  fs.writeFileSync(path.join(root,'frontend/app-ai-lazy.js'), lazy.code+'\n');
  const css=fs.readFileSync(path.join(root,'frontend/style.css'),'utf8');
  const optimized=await postcss([cssnano({preset:['default',{normalizeUrl:false,discardUnused:false}]})]).process(css,{from:undefined});
  fs.writeFileSync(path.join(root,'frontend/style.min.css'),optimized.css+'\n');
  const sizes={source:Buffer.byteLength(source),bootstrap:Buffer.byteLength(output.code),lazy:Buffer.byteLength(lazy.code),lazyFunctions:functions.length,cssSource:Buffer.byteLength(css),css:Buffer.byteLength(optimized.css)};
  fs.writeFileSync(path.join(root,'docs/architecture/frontend-build.json'),JSON.stringify(sizes,null,2)+'\n');
  console.log(JSON.stringify(sizes));
}
build().catch(e=>{console.error(e);process.exit(1)});
