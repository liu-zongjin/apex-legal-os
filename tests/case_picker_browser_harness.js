(async () => {
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
  const make = () => { const input = document.createElement('input'), menu = document.createElement('div'); document.body.append(input, menu); return {input, menu}; };
  const results = [];
  try {
    localStorage.clear();
    const api = window.ApexCasePicker;
    const child = {id: 22, case_kind:'series_child', series_code:'22', display_name:'22', title:'匿名系列案件（仲裁）·匿名委托人甲与匿名对方乙商品房买卖合同纠纷案（完整名称）', clients:[{name:'甲客户'}], updated_at:'2026-10-02'};
    assert(api.caseName(child) === child.title, 'series title must use full saved case name');
    assert(api.caseName({...child,title:'22'}) === '22', 'a missing display name must not repeat the series code');
    const roots = [{id:1,title:'匿名系列',children:[child]}];
    const flat = api.flatten(roots);
    assert(flat.length===2 && flat[1].parentTitle==='匿名系列', 'series context and IDs survive flattening');
    const grouped = api.displayRows([{id:2,title:'多客户案件',clients:[{name:'甲客户'},{name:'乙客户'}]},{id:3,title:'未关联案件'}], 'client');
    assert(grouped.length===3 && grouped.at(-1).group==='未关联客户', 'multi-client case appears under each client and unassigned comes last');
    const offsets=[];
    const loaded = await api.load('', {request: async url => { const offset=Number(new URL(url,location.href).searchParams.get('offset')); offsets.push(offset); return offset===0?{items:[roots[0]],has_more:true,next_offset:1}:{items:[{id:4,title:'下一页'}],has_more:false,next_offset:2}; }});
    assert(loaded.length===2 && offsets.join(',')==='0,1', 'loader must retrieve all server pages');
    results.push('full names, series context, client groups, pagination');

    const source = [child, ...Array.from({length:85},(_,index)=>({id:100+index,title:`匿名案件 ${index+1}`,clients:[{name:index%2?'乙客户':'甲客户'}],updated_at:'2026-10-01'}))];
    const elements = make(); let picked=null;
    const picker=api.attach({...elements,items:query=> query==='新查询'?[{id:999,title:'新查询案件'}]:source,onSelect:item=>{picked=item;elements.input.value=item.title;}});
    await picker.open();
    assert(elements.menu.parentNode===document.body && elements.menu.querySelectorAll('[data-case-index]').length===60,'popup must portal and bound initial DOM size');
    elements.menu.querySelector('[data-case-more]').click();
    assert(elements.menu.querySelectorAll('[data-case-index]').length===86,'load-more preserves all candidates');
    const title=elements.menu.querySelector('strong');
    assert(getComputedStyle(title).whiteSpace==='normal','long names must wrap');
    elements.input.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}));
    assert(elements.input.getAttribute('aria-activedescendant'), 'keyboard active row must be exposed');
    elements.input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
    assert(picked && !picker.opened && elements.input.getAttribute('aria-expanded')==='false','keyboard selection closes popup');
    await picker.open();
    elements.input.value='新查询';elements.input.dispatchEvent(new Event('input',{bubbles:true}));
    await delay(210);
    assert(elements.menu.textContent.includes('新查询案件') && !elements.menu.textContent.includes('匿名案件 1'),'editing selected text must replace results');
    assert(picker.selected.size===0,'editing text clears the selected ID');
    results.push('bounded DOM, full-name wrapping, keyboard selection, new query after selection');

    const multiElements=make(); const selected=new Set();
    const multi=api.attach({...multiElements,inline:true,mode:'multiple',items:source,selected:()=>selected,onSelect:(item,checked)=>{if(checked)selected.add(Number(item.id));else selected.delete(Number(item.id));}});
    await multi.open();
    multiElements.menu.querySelector('[data-case-sort="client"]').click();
    const first=multiElements.menu.querySelector('[data-case-index]');const index=Number(first.dataset.caseIndex),id=Number(multi.display[index].item.id);first.click();
    assert(selected.has(id) && multi.opened,'multiple selection stays open');
    multiElements.menu.querySelector(`[data-case-index="${index}"]`).click();
    assert(!selected.has(id), 'multiple selection can be toggled off');
    const otherElements=make(); const other=api.attach({...otherElements,items:source}); await other.open();
    assert(other.sort==='client','browse preference is shared between menus');
    results.push('client browse preference, persistent multi-selection');

    const clearElements=make(); let cleared=false;
    const clearPicker=api.attach({...clearElements,inline:true,items:source,value:child.id,allowClear:true,onClear:()=>{cleared=true;}});
    await clearPicker.open();
    clearElements.menu.querySelector('[data-case-clear]').click();
    assert(cleared && clearPicker.selected.size===0,'optional clear action removes the selected case');
    results.push('optional clear action');

    const raceElements=make();let finishOld;
    const race=api.attach({...raceElements,items:query=>query==='fresh'?Promise.resolve([{id:700,title:'fresh result'}]):new Promise(resolve=>{finishOld=resolve;})});
    const pending=race.open();raceElements.input.value='fresh';await race.open(true);finishOld([{id:600,title:'stale result'}]);await pending;
    assert(raceElements.menu.textContent.includes('fresh result')&&!raceElements.menu.textContent.includes('stale result'),'older request cannot overwrite a newer search');
    race.close();assert(raceElements.menu.hidden,'close hides menu');
    raceElements.input.remove();await delay(0);assert(race.destroyed&&!raceElements.menu.isConnected,'removed forms must destroy their portal menus');
    results.push('request races, close, removed-form cleanup');
    [picker,multi,other,clearPicker].forEach(item=>item.destroy());
    document.getElementById('result').textContent=JSON.stringify({ok:true,results});
  } catch(error) { document.getElementById('result').textContent=JSON.stringify({ok:false,error:error.stack}); }
})();
