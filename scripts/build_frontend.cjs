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
  // Generate record typography from the knowledge article/editor source rules.
  // Keep one typography implementation while isolating case-modal geometry.
  const typography=postcss.root();
  const rootProperties=/^(?:font(?:-.+)?|line-height|letter-spacing|color|white-space|text-indent|text-align|word-break|overflow-wrap)$/;
  function typographyNodes(container, output) {
    for(const node of container.nodes || []) {
      if(node.type==='atrule' && node.nodes) {
        const copy=node.clone({nodes:[]});typographyNodes(node,copy);
        if(copy.nodes.length)output.append(copy);
      } else if(node.type==='rule') {
        const selectors=node.selectors.filter(selector=>/\.tab-article-body-text\b|\.body-editor(?=[.#:\s>]|$)/.test(selector));
        for(const selector of selectors) {
          const mapped=selector.replace(/\.body-editor-page(?:\.continuous-mode|:not\(\.continuous-mode\))?/g,'.case-record-content')
            .replace(/\.body-editor-modal/g,'.case-record-content')
            .replace(/\.tab-article-body-text/g,'.case-record-preview')
            .replace(/\.body-editor(?=[.#:\s>]|$)/g,'.case-record-preview');
          const rule=node.clone({selector:mapped});
          if(/\.case-record-preview(?:\.case-record-preview)?$/.test(mapped))
            rule.walkDecls(decl=>{if(!rootProperties.test(decl.prop))decl.remove();});
          if(rule.nodes.length)output.append(rule);
        }
      }
    }
  }
  typographyNodes(postcss.parse(css),typography);
  fs.writeFileSync(path.join(root,'frontend/apex-record-typography.css'),
    '/* Generated from canonical knowledge article/editor rules. */\n'+typography.toString()+'\n');
  const optimized=await postcss([cssnano({preset:['default',{normalizeUrl:false,discardUnused:false}]})]).process(css,{from:undefined});
  fs.writeFileSync(path.join(root,'frontend/style.min.css'),optimized.css+'\n');
  const sizes={source:Buffer.byteLength(source),bootstrap:Buffer.byteLength(output.code),lazy:Buffer.byteLength(lazy.code),lazyFunctions:functions.length,cssSource:Buffer.byteLength(css),css:Buffer.byteLength(optimized.css)};
  fs.writeFileSync(path.join(root,'docs/architecture/frontend-build.json'),JSON.stringify(sizes,null,2)+'\n');
  console.log(JSON.stringify(sizes));
}
build().catch(e=>{console.error(e);process.exit(1)});
