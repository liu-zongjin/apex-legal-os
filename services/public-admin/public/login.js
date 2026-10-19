document.getElementById('login').addEventListener('submit', async event=>{
  event.preventDefault();const button=event.target.querySelector('button'),message=document.getElementById('message');
  button.disabled=true;message.textContent='正在登录…';
  try {
    const response=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({password:document.getElementById('password').value})});
    document.getElementById('password').value='';
    if(response.ok){location.replace('/');return;}
    message.textContent=(await response.json()).error || '登录失败，请稍后重试';
  }catch{message.textContent='连接失败，请稍后重试';}finally{button.disabled=false;}
});
