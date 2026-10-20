(() => {
  'use strict';
  const button=document.getElementById('customization-continue');
  const target=document.querySelector('meta[name="stella-experience-route"]')?.content;
  if(!button || !['/mingsi-meeting','/quick-approval'].includes(target))return;
  const key='stella.customization.ack.v1',url=target+'?experience=1';
  try{if(localStorage.getItem(key)==='true'){location.replace(url);return;}}catch{}
  button.addEventListener('click',()=>{
    if(document.getElementById('customization-remember').checked){try{localStorage.setItem(key,'true');}catch{}}
    location.replace(url);
  });
})();
