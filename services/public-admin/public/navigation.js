let observer;
function rebuildIndex(){
  observer?.disconnect();
  const view=document.getElementById('view-'+document.body.dataset.view);
  if(!view)return;
  const nav=document.getElementById('section-index');
  const sections=[...view.querySelectorAll('.cards,.panel,footer')].filter(el=>!el.parentElement.closest('.panel'));
  nav.replaceChildren(...sections.map((section,i)=>{
    section.id ||= view.id+'-section-'+i;
    const a=document.createElement('a');a.href='#'+section.id;
    a.textContent=section.querySelector('summary,h2')?.textContent||section.getAttribute('aria-label')||(section.tagName==='FOOTER'?'统计说明':'概览 '+(i+1));
    a.addEventListener('click',e=>{e.preventDefault();if(section.tagName==='DETAILS')section.open=true;section.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});section.tabIndex=-1;section.focus({preventScroll:true});});
    return a;
  }));
  observer=new IntersectionObserver(entries=>{for(const entry of entries)if(entry.isIntersecting){for(const a of nav.children)a.hash==='#'+entry.target.id?a.setAttribute('aria-current','location'):a.removeAttribute('aria-current');}}, {rootMargin:'-90px 0px -55% 0px'});
  sections.forEach(section=>observer.observe(section));
}
document.addEventListener('apex:admin-view',rebuildIndex);
