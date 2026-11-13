import {test} from 'node:test';
import assert from 'node:assert/strict';
import {syncSourceTraffic} from '../src/source-traffic.js';

test('saves complete traffic in one batch and preserves history on API failure', async()=>{
  const original=globalThis.fetch; let calls=0, batches=[];
  const entry={timestamp:'2026-11-10T00:00:00Z',count:4,uniques:2};
  const env={SOURCE_TRAFFIC_TOKEN:'fixture',DB:{prepare(sql){return {bind(...args){return {sql,args}}}},async batch(rows){batches.push(rows)}}};
  try {
    globalThis.fetch=async url=>{calls++;const key=url.split('/').at(-1);return new Response(JSON.stringify(key==='views'||key==='clones'?{count:4,uniques:2,[key]:[entry]}:[]));};
    await syncSourceTraffic(env);
    assert.equal(calls,4);assert.equal(batches.length,1);assert.equal(batches[0].length,2);
    globalThis.fetch=async()=>new Response('',{status:403});
    await assert.rejects(syncSourceTraffic(env),/403/);assert.equal(batches.length,1);
  } finally {globalThis.fetch=original;}
});
