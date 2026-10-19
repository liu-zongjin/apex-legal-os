import {test} from 'node:test';
import assert from 'node:assert/strict';
import entrance from '../../public-admin-entrance/public/_worker.js';

test('Pages forwards the original URL, origin, credentials and body to the bound service',async()=>{
 const payload=JSON.stringify({password:'anonymous-fixture'});
 const request=new Request('https://stella-admin.pages.dev/api/login',{method:'POST',
   headers:{Origin:'https://stella-admin.pages.dev','Content-Type':'application/json',Cookie:'fixture=value'},body:payload});
 const response=await entrance.fetch(request,{ADMIN:{fetch:async forwarded=>{
   assert.equal(forwarded,request);
   assert.equal(forwarded.url,'https://stella-admin.pages.dev/api/login');
   assert.equal(forwarded.headers.get('Origin'),'https://stella-admin.pages.dev');
   assert.equal(forwarded.headers.get('Cookie'),'fixture=value');
   assert.equal(await forwarded.text(),payload);
   return new Response('authenticated',{headers:{'Set-Cookie':'__Host-stella_admin=fixture; Secure; HttpOnly; SameSite=Strict; Path=/'}});
 }}});
 assert.equal(await response.text(),'authenticated');
 assert.ok(response.headers.get('Set-Cookie').includes('HttpOnly'));
});
test('the entrance fails closed if binding is missing or unavailable',async()=>{
 for(const env of [{},{ADMIN:{fetch:async()=>{throw Error('unavailable');}}}]){
  const response=await entrance.fetch(new Request('https://stella-admin.pages.dev/api/summary'),env);
  assert.equal(response.status,503);assert.equal(response.headers.get('Cache-Control'),'no-store');
  assert.ok(!(await response.text()).includes('fixture'));
 }
});
