(() => {
'use strict';
const byId = id => document.getElementById(id);
let offset=0, loading=false, preview=false, submitting=false, withdrawing=null;
const editor=byId('message-editor');
function text(tag,value,className='') {const el=document.createElement(tag);el.textContent=value;el.className=className;return el;}
async function api(path,options={}) {
  const response=await fetch(path,{cache:'no-store',...options});
  if(response.status===401){location.replace('/login');throw new Error('请重新登录');}
  const data=await response.json();
  if(!response.ok)throw new Error(data.error || '操作失败，请稍后重试');
  return data;
}
async function load() {
  if(loading || document.hidden)return;
  loading=true;
  try {
    const data=await api('/api/messages?offset='+offset);
    byId('message-list').replaceChildren(...data.messages.map(item=>{
      const article=document.createElement('article');article.className='announcement';
      const head=document.createElement('div');head.className='message-heading';
      const details=document.createElement('div');
      details.append(text('h3',item.title),text('p',(item.withdrawn_at?'已撤回 · ':'展示中 · ')+new Date(item.published_at*1000).toLocaleString('zh-CN')));
      head.append(details);
      if(!item.withdrawn_at){const button=text('button','撤回');button.addEventListener('click',()=>{
        withdrawing=item;byId('withdraw-title').textContent=item.title;byId('withdraw-status').textContent='';byId('withdraw-dialog').showModal();
      });head.append(button);}
      article.append(head,text('div',item.body,'message-body'));return article;
    }));
    byId('message-status').textContent=data.messages.length?'':'还没有系统消息。发布后，用户可在首页右上角查看。';
    byId('messages-prev').disabled=offset===0;byId('messages-next').disabled=!data.has_more;
    byId('messages-page').textContent='第 '+(offset/50+1)+' 页';
  } catch(error){byId('message-status').textContent=error.message;}
  finally{loading=false;}
}
function setPreview(value) {
  preview=value;byId('message-fields').hidden=value;byId('message-preview').hidden=!value;byId('back-editor').hidden=!value;
  byId('publish-message').textContent=value?'确认发布给所有用户':'预览消息';
  byId('editor-heading').textContent=value?'确认发布内容':'发布系统消息';
}
byId('compose-message').addEventListener('click',()=>{setPreview(false);byId('publish-status').textContent='';editor.showModal();});
byId('close-editor').addEventListener('click',()=>{if(!submitting)editor.close();});
editor.addEventListener('cancel',event=>{if(submitting)event.preventDefault();});
byId('back-editor').addEventListener('click',()=>{if(!submitting)setPreview(false);});
byId('message-form').addEventListener('submit',async event=>{
  event.preventDefault();if(submitting)return;
  const title=byId('message-title').value.trim(),body=byId('message-body').value.trim();
  if(!title || !body){byId('publish-status').textContent='请填写标题和正文';return;}
  if(!preview){byId('preview-title').textContent=title;byId('preview-body').textContent=body;setPreview(true);return;}
  submitting=true;byId('publish-message').disabled=true;byId('back-editor').disabled=true;
  try {
    await api('/api/messages',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title,body})});
    editor.close();byId('message-form').reset();offset=0;await load();byId('message-status').textContent='已发布，用户联网后将自动获取。';
  }catch(error){byId('publish-status').textContent=error.message;}
  finally{submitting=false;byId('publish-message').disabled=false;byId('back-editor').disabled=false;}
});
byId('cancel-withdraw').addEventListener('click',()=>{if(!submitting)byId('withdraw-dialog').close();});
byId('withdraw-dialog').addEventListener('cancel',event=>{if(submitting)event.preventDefault();});
byId('confirm-withdraw').addEventListener('click',async()=>{
  if(!withdrawing || submitting)return;
  submitting=true;byId('confirm-withdraw').disabled=true;
  try {await api('/api/messages/'+withdrawing.id+'/withdraw',{method:'POST'});byId('withdraw-dialog').close();await load();}
  catch(error){byId('withdraw-status').textContent=error.message;}
  finally{submitting=false;byId('confirm-withdraw').disabled=false;}
});
byId('messages-prev').addEventListener('click',()=>{if(!loading){offset=Math.max(0,offset-50);load();}});
byId('messages-next').addEventListener('click',()=>{if(!loading){offset+=50;load();}});
byId('refresh').addEventListener('click',load);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
load();

})();
