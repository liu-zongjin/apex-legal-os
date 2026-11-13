/* Adapted from Brain Particle Effort Slider — Vanilla by ozzyxs1a.
 * Reference: https://x.com/ozzyxs1a/status/2107523169649389677/video/1
 * The original six visual positions map to Stella's four actual API settings.
 */
(function () {
  'use strict';
  const LEVELS = [
    {id:'fast', label:'快速', description:'关闭思考，适合简单问题'},
    {id:'low', label:'轻度', description:'兼顾速度与简单推理'},
    {id:'high', label:'深度', description:'适合复杂分析'},
    {id:'max', label:'最深', description:'适合特别复杂的问题'},
  ];
  const COLORS = ['#cda9ac','#dec3c3','#ead6d1','#b9a9bd','#dfbdcb','#c9b4a8'];
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const hash = n => {const value=Math.sin(n*127.1+311.7)*43758.5453;return value-Math.floor(value);};

  function mount(menu, onChange, options = {}) {
    const compact = Boolean(options.compact);
    const content=menu.querySelector('.ask-brain-content');
    const control=menu.querySelector('.ask-brain-control');
    const track=menu.querySelector('.ask-brain-track');
    const fill=menu.querySelector('.ask-brain-fill');
    const thumb=menu.querySelector('.ask-brain-thumb');
    const brain=menu.querySelector('.ask-brain-svg');
    const label=menu.querySelector('#ask-brain-level');
    const description=menu.querySelector('#ask-brain-description');
    const pixels=menu.querySelector('.ask-brain-pixels');
    const particles=menu.querySelector('.ask-brain-particles');
    const layers=[...brain.querySelectorAll('.ge-fold-layer')];
    const dots=pixels.getContext('2d'), sparks=particles.getContext('2d');
    const motion=window.matchMedia('(prefers-reduced-motion: reduce)');
    const state={position:0,velocity:0,target:0,galaxy:0,galaxyVelocity:0};
    let selected=0, frame=0, last=0, clock=0, entered=-100, pointer=null, startValue=0;
    let visible=false, destroyed=false, pixelWidth=0, pixelHeight=0, sparkWidth=0, sparkHeight=0;

    function resizeCanvas(canvas, width, height) {
      const ratio=Math.min(window.devicePixelRatio||1,2);
      const w=Math.max(1,Math.round(width*ratio)),h=Math.max(1,Math.round(height*ratio));
      if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}
      const ctx=canvas.getContext('2d');ctx.setTransform(ratio,0,0,ratio,0,0);
    }
    function resize() {
      pixelWidth=track.clientWidth;pixelHeight=track.clientHeight;
      sparkWidth=particles.clientWidth;sparkHeight=particles.clientHeight;
      if(!pixelWidth||!sparkWidth)return;
      resizeCanvas(pixels,pixelWidth,pixelHeight);resizeCanvas(particles,sparkWidth,sparkHeight);draw();
    }
    function drawPixels(time,strength) {
      dots.clearRect(0,0,pixelWidth,pixelHeight);
      if(strength<=0)return;
      const rows=5, cols=Math.max(1,Math.ceil(pixelWidth/8));
      for(let row=0;row<rows;row++)for(let col=0;col<cols;col++){
        const n=row*cols+col,seed=hash(n+7),wave=.5+.5*Math.sin(time*(2+seed*3)+n*1.618);
        const fraction=cols>1?col/(cols-1):0,density=.14+.78*Math.pow(fraction,1.6);
        if(seed>density+.16*Math.sin(time*1.8+col*.2))continue;
        dots.globalAlpha=strength*(.18+.72*wave)*(.22+.78*fraction);
        dots.fillStyle=COLORS[Math.floor(hash(n+211)*COLORS.length)];
        const size=seed>.74?5.7:5.1,x=col*8+1,y=row*pixelHeight/rows+.5;
        dots.beginPath();if(dots.roundRect)dots.roundRect(x,y,size,size,1.3);else dots.rect(x,y,size,size);dots.fill();
      }
      dots.globalAlpha=1;
    }
    function drawSparks(time,strength,x,y) {
      sparks.clearRect(0,0,sparkWidth,sparkHeight);
      if(strength<=0)return;
      const age=Math.max(0,time-entered),burst=Math.exp(-age*5);
      for(let ray=0;ray<26;ray++){
        const angle=ray*2.399963,seed=hash(ray+94),speed=15+seed*24;
        for(let dot=0;dot<7;dot++){
          const radius=27+((dot*13+time*speed+seed*40)%87)+burst*dot*3;
          const fade=Math.pow(1-clamp((radius-27)/110,0,1),1.6),pulse=.45+.55*Math.sin(time*4+ray+dot)**2;
          sparks.globalAlpha=strength*fade*pulse*(.4+burst*.35);sparks.fillStyle=COLORS[(ray+dot)%COLORS.length];
          const size=seed>.65?3:2;sparks.fillRect(x+Math.cos(angle)*radius,y+Math.sin(angle)*radius,size,size);
        }
      }
      sparks.globalAlpha=1;
    }
    function draw() {
      const position=clamp(state.position,0,3),visual=position/3*5,galaxy=clamp(state.galaxy,0,1);
      const age=Math.max(0,clock-entered),burst=Math.exp(-age*6)*galaxy;
      layers.forEach(layer=>{
        const amount=clamp((visual-Number(layer.dataset.tier)+.85)/.7,0,1),reveal=amount*amount*(3-2*amount);
        layer.style.opacity=String(reveal);layer.style.setProperty('--ge-fold-hidden',String(1-reveal));
      });
      const x=track.offsetLeft+position/3*track.clientWidth;
      thumb.style.left=x+'px';thumb.style.transform=`translate(-50%,-50%) scale(${1+galaxy*.10+burst*.08})`;
      brain.style.setProperty('--ge-brain-fill',galaxy>.01?`rgb(${232-14*galaxy},${198-3*galaxy},${197+9*galaxy})`:'#e8c6c5');
      brain.style.setProperty('--ge-brain-edge',galaxy>.01?`rgb(${166-6*galaxy},${122+3*galaxy},${126+10*galaxy})`:'#a67a7e');
      thumb.style.filter=galaxy>.01?`drop-shadow(0 0 ${4+burst*6}px #d9b6c4) drop-shadow(0 0 ${8+burst*10}px #cbb2c080)`:'none';
      fill.style.width=(position/3*100)+'%';fill.style.opacity=String(1-galaxy);pixels.style.opacity=String(galaxy);
      const shake=motion.matches||compact?0:galaxy*(.28+Math.exp(-age*7)*2.1);
      content.style.transform=shake?`translate(${Math.sin(clock*93)*shake}px,${Math.cos(clock*117)*shake*.65}px)`:'';
      drawPixels(clock,galaxy);
      drawSparks(clock,motion.matches?0:galaxy,control.offsetLeft+x-particles.offsetLeft,control.offsetTop+control.clientHeight/2-particles.offsetTop);
      menu.dataset.brainPosition=position.toFixed(3);menu.dataset.brainGalaxy=galaxy.toFixed(3);
    }
    function spring(key,velocityKey,target,dt,k,damping) {
      state[velocityKey]+=((target-state[key])*k-state[velocityKey]*damping)*dt;state[key]+=state[velocityKey]*dt;
      if(Math.abs(state[key]-target)<.0002&&Math.abs(state[velocityKey])<.002){state[key]=target;state[velocityKey]=0;}
      return state[key]!==target||state[velocityKey]!==0;
    }
    function pause(){cancelAnimationFrame(frame);frame=0;last=0;menu.dataset.brainAnimating='false';}
    function settle(){pause();state.position=state.target;state.velocity=0;state.galaxy=selected===3?1:0;state.galaxyVelocity=0;draw();}
    function onScreen(){
      if(!visible||document.hidden||menu.hidden||!menu.getClientRects().length)return false;
      const rect=menu.getBoundingClientRect();
      return rect.right>0&&rect.bottom>0&&rect.left<window.innerWidth&&rect.top<window.innerHeight;
    }
    function tick(time){
      frame=0;if(destroyed||!onScreen()){pause();return;}
      if(motion.matches){settle();return;}
      const dt=Math.min(.032,(time-(last||time-16))/1000);last=time;clock+=dt;let moving=false;
      for(let step=0;step<3;step++){
        moving=spring('position','velocity',state.target,dt/3,420,32)||moving;
        moving=spring('galaxy','galaxyVelocity',selected===3?1:0,dt/3,190,25)||moving;
      }
      draw();menu.dataset.brainAnimating=String(moving||(!compact&&selected===3));
      if(moving||(!compact&&selected===3))frame=requestAnimationFrame(tick);else last=0;
    }
    function wake(){if(destroyed)return;if(motion.matches||!onScreen()){settle();return;}if(!frame)frame=requestAnimationFrame(tick);}
    function select(index,commit){
      const position=clamp(index,0,3);index=Math.round(position);const previous=selected;selected=index;state.target=commit?index:position;
      if(index===3&&previous!==3)entered=clock;
      const item=LEVELS[index];if(label)label.textContent=item.label;if(description)description.textContent=item.description;
      control.setAttribute('aria-valuenow',String(index));control.setAttribute('aria-valuetext',item.label+'：'+item.description);
      menu.dataset.brainLevel=item.id;wake();
      if(commit)onChange(item.id);
    }
    function pointerValue(event){const bounds=track.getBoundingClientRect();return clamp((event.clientX-bounds.left)/Math.max(bounds.width,1)*3,0,3);}
    control.addEventListener('pointerdown',event=>{
      if(event.button!==0||pointer!==null)return;event.preventDefault();control.focus();pointer=event.pointerId;startValue=selected;
      control.setPointerCapture(pointer);select(pointerValue(event),false);
    });
    control.addEventListener('pointermove',event=>{if(event.pointerId===pointer)select(pointerValue(event),false);});
    function release(event,cancelled){
      if(event.pointerId!==pointer)return;const id=pointer;pointer=null;
      select(cancelled?startValue:selected,!cancelled);
      if(control.hasPointerCapture(id))control.releasePointerCapture(id);
    }
    control.addEventListener('pointerup',event=>release(event,false));
    control.addEventListener('pointercancel',event=>release(event,true));
    control.addEventListener('lostpointercapture',event=>{if(pointer!==null)release(event,true);});
    control.addEventListener('keydown',event=>{
      let next=selected;
      if(event.key==='ArrowRight'||event.key==='ArrowUp')next++;
      else if(event.key==='ArrowLeft'||event.key==='ArrowDown')next--;
      else if(event.key==='Home')next=0;else if(event.key==='End')next=3;
      else if(event.key==='PageUp')next+=2;else if(event.key==='PageDown')next-=2;else return;
      event.preventDefault();select(next,true);
    });
    const observer=new ResizeObserver(resize);observer.observe(content);observer.observe(track);
    function visibility(){if(document.hidden)pause();else wake();}
    function motionChanged(){if(motion.matches)settle();else wake();}
    document.addEventListener('visibilitychange',visibility);motion.addEventListener('change',motionChanged);
    return {
      setValue(value){const index=LEVELS.findIndex(item=>item.id===value);if(index>=0&&pointer===null)select(index,false);},
      start(){visible=true;state.position=state.target;state.velocity=0;state.galaxy=selected===3?1:0;state.galaxyVelocity=0;resize();wake();},
      stop(){visible=false;pointer=null;pause();content.style.transform='';},
      destroy(){destroyed=true;pause();observer.disconnect();document.removeEventListener('visibilitychange',visibility);motion.removeEventListener('change',motionChanged);},
    };
  }
  window.StellaReasoningSlider={mount};
})();
