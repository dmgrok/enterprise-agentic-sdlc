import { validateSnapshot, eventIndices, chartValue, windowIndices, change } from './market-model.mjs';
const $ = s => document.querySelector(s), NS = 'http://www.w3.org/2000/svg';
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
const svg = (tag, attrs, text) => { const n = document.createElementNS(NS, tag); for (const [k,v] of Object.entries(attrs)) n.setAttribute(k,v); if (text !== undefined) n.textContent = text; return n; };
const dateLabel = date => new Date(date + 'T12:00:00Z').toLocaleDateString('en-GB', {day:'numeric',month:'short',timeZone:'UTC'});
const signed = value => `${value >= 0 ? '+' : ''}${value.toFixed(2)}`;
const groups = {
 all: {label:'All exposures', symbols:['NVDA','MSFT','SPY'], title:'Follow the business exposure', description:'Compare listed chip and cloud companies with a broad-market ETF. Their mixed businesses are not pure measures of AI demand.', hypothesis:'A cheaper credible model could pressure pricing and change compute expectations; greater adoption could offset those effects.', check:'Test substitution, paid usage, serving cost, utilization and capacity orders. A share-price move is evidence to investigate, not proof of the mechanism.'},
 frontier: {label:'Frontier labs', symbols:['MSFT','GOOGL','SPY'], title:'Frontier labs: no direct price series here', description:'This snapshot has no direct stock-price series for OpenAI or Anthropic. Microsoft and Alphabet are diversified public comparators, not valuations of those labs.', hypothesis:'Pricing and differentiation may weaken, while lower serving costs or more paid usage could support margins.', check:'Look for realized API prices, customer retention, successful-task serving cost and contribution margin. Listed cloud-company prices cannot establish a private lab’s profit impact.'},
 chips: {label:'Chip suppliers', symbols:['NVDA','AVGO','SPY'], title:'Chip suppliers: volume versus efficiency', description:'NVIDIA and Broadcom give two listed perspectives. Broadcom also has a substantial software business; neither line isolates AI chip demand.', hypothesis:'Less compute per task could reduce fixed-volume demand. More tasks, different hardware requirements or platform share could offset it.', check:'Check utilization, orders, product mix and training versus inference. A supplier’s exposure depends on which platform the model runs on.'},
 cloud: {label:'Cloud & data centres', symbols:['MSFT','GOOGL','SPY'], title:'Cloud operators can host open models too', description:'Microsoft and Alphabet are diversified cloud comparators. No standalone data-centre landlord is included in this snapshot.', hypothesis:'More model use could raise hosting demand, while efficiency, lower prices and capacity commitments change how much profit operators capture.', check:'Separate traffic growth from revenue and margin. Inspect power availability, contracted capacity and utilization. Company earnings are competing explanations for price moves.'}
};
export function createMarketAnalysis({onFocus}) {
  let data, promise, active = false, group = 'all', event = 'selloff', mode = 'indexed', window = 'near', selected = 0;
  let visible = new Set(groups.all.symbols), chartGeometry;
  const root = $('#market-analysis'), plot = $('#market-chart');
  const state = () => ({data,group,event,mode,window,selected});
  function setGroup(id, notify = false) {
    if (!groups[id]) return;
    group = id; visible = new Set(groups[id].symbols);
    if (data) render();
    if (notify) onFocus?.(id);
  }
  function sourceLink(label,url) { const a=el('a','',label); a.href=url; a.target='_blank'; a.rel='noopener noreferrer'; return a; }
  function render() {
    if (!data) return;
    const ev=data.events.find(e=>e.id===event), {baseline}=eventIndices(data,ev.date), [lo,hi]=windowIndices(data,ev.date,window);
    selected=Math.max(lo,Math.min(hi,selected));
    $('#market-baseline').textContent=`${mode==='indexed'?'100 = each asset’s adjusted close':'Difference in returns versus SPY'} at ${dateLabel(data.dates[baseline])} 2025. Daily observations; no intraday path.`;
    $('#market-event-note').replaceChildren(el('span','',ev.note+' '),sourceLink(event==='selloff'?'Retrospective BIS context':'Event source',ev.url));
    $('#market-group-title').textContent=groups[group].title;
    $('#market-group-description').textContent=groups[group].description;
    $('#market-hypothesis').textContent=groups[group].hypothesis;
    $('#market-check').textContent=groups[group].check;
    for(const button of $('#market-groups').children)button.setAttribute('aria-pressed',button.dataset.group===group);
    for(const button of $('#market-events').children)button.setAttribute('aria-pressed',button.dataset.event===event);
    const legend=$('#market-legend'); legend.replaceChildren();
    for(const series of data.series){
      const b=el('button','series-toggle',series.symbol);b.type='button';b.dataset.symbol=series.symbol;
      b.setAttribute('aria-pressed',visible.has(series.symbol));b.setAttribute('aria-label',`${series.name}: ${series.role}`);
      const swatch=svg('svg',{width:19,height:10,viewBox:'0 0 19 10','aria-hidden':'true'});
      swatch.append(svg('path',{d:'M0 5 H19',stroke:series.color,'stroke-width':3,...(series.symbol==='SPY'?{'stroke-dasharray':'4 3'}:{})}));b.prepend(swatch);
      if(series.symbol==='SPY'){b.setAttribute('aria-disabled','true');b.title='SPY stays visible as the comparator';}
      b.addEventListener('click',()=>{if(series.symbol==='SPY')return; if(visible.has(series.symbol))visible.delete(series.symbol);else visible.add(series.symbol);render();$('#market-legend [data-symbol="'+series.symbol+'"]').focus();});
      legend.append(b);
    }
    plot.replaceChildren();
    const width=Math.max(300,Math.floor($('#market-chart-frame').clientWidth)),height=320,left=48,right=18,top=47,bottom=37;
    const indices=Array.from({length:hi-lo+1},(_,i)=>i+lo),series=data.series.filter(s=>visible.has(s.symbol));
    const values=series.flatMap(s=>indices.map(i=>chartValue(data,s,i,baseline,mode)));
    const center=mode==='indexed'?100:0,min=Math.min(center,...values),max=Math.max(center,...values),pad=Math.max((max-min)*.13,1);
    const low=min-pad,high=max+pad,t0=Date.parse(data.dates[lo]),t1=Date.parse(data.dates[hi]);
    const x=date=>left+(Date.parse(date)-t0)/(t1-t0)*(width-left-right),y=v=>top+(high-v)/(high-low)*(height-top-bottom);
    chartGeometry={width,left,right,lo,hi,x};plot.setAttribute('viewBox',`0 0 ${width} ${height}`);
    plot.append(svg('title',{},`Historical adjusted closes, ${dateLabel(data.dates[lo])} to ${dateLabel(data.dates[hi])} 2025. ${mode==='relative'?'Return differences in percentage points versus SPY.':'Rebased to 100 at the previous session.'}`));
    for(let i=0;i<5;i++){
      const v=low+(high-low)*i/4,yy=y(v);
      plot.append(svg('line',{x1:left,x2:width-right,y1:yy,y2:yy,class:'price-grid'}));
      plot.append(svg('text',{x:left-9,y:yy+4,'text-anchor':'end',class:'price-axis'},v.toFixed(0)+(mode==='relative'?'pp':'')));
    }
    plot.append(svg('line',{x1:left,x2:width-right,y1:y(center),y2:y(center),class:'price-baseline'}));
    for(const i of [...new Set([lo,Math.round((lo+hi)/2),hi])])plot.append(svg('text',{x:x(data.dates[i]),y:height-12,'text-anchor':i===lo?'start':i===hi?'end':'middle',class:'price-axis'},dateLabel(data.dates[i])));
    data.events.forEach((e,i)=>{
      if(e.date<data.dates[lo]||e.date>data.dates[hi])return;
      const xx=x(e.date);
      plot.append(svg('line',{x1:xx,x2:xx,y1:top-8,y2:height-bottom,class:e.id===event?'price-event selected':'price-event'}));
      plot.append(svg('text',{x:xx,y:i%2?35:16,'text-anchor':xx>width*.8?'end':xx<width*.2?'start':'middle',class:'price-axis event-label'},e.id==='release'?'20 Jan: R1':e.id==='selloff'?'27 Jan: sell-off':'29 Jan: Fed'));
    });
    for(const s of series){
      const d=indices.map((i,j)=>`${j?'L':'M'}${x(data.dates[i]).toFixed(2)},${y(chartValue(data,s,i,baseline,mode)).toFixed(2)}`).join(' ');
      plot.append(svg('path',{d,fill:'none',stroke:s.color,'stroke-width':s.symbol==='SPY'?2:2.8,'stroke-linejoin':'round','stroke-linecap':'round',...(s.symbol==='SPY'?{'stroke-dasharray':'6 5'}:{}),'data-price-series':s.symbol}));
    }
    plot.append(svg('line',{id:'price-cursor',x1:x(data.dates[selected]),x2:x(data.dates[selected]),y1:top,y2:height-bottom,class:'price-cursor'}));
    for(const s of series)plot.append(svg('circle',{cx:x(data.dates[selected]),cy:y(chartValue(data,s,selected,baseline,mode)),r:4,fill:s.color,stroke:'white','stroke-width':1.5}));
    const slider=$('#market-date');slider.min=lo;slider.max=hi;slider.value=selected;slider.setAttribute('aria-valuetext',data.dates[selected]);
    $('#market-selected-date').textContent=`${dateLabel(data.dates[selected])} 2025`;
    const body=$('#market-readout');body.replaceChildren();
    const spy=data.series.find(s=>s.symbol==='SPY');
    for(const s of series){
      const tr=el('tr'),name=el('th','',s.symbol);name.scope='row';name.append(el('small','',s.name));tr.append(name);
      const daily=selected?change(s.values[selected],s.values[selected-1]):null,own=change(s.values[selected],s.values[baseline]),diff=own-change(spy.values[selected],spy.values[baseline]);
      tr.append(el('td','',daily===null?'—':signed(daily)+'%'),el('td','',signed(own)+'%'),el('td','',signed(diff)+' pp'));body.append(tr);
    }
    const sources=$('#market-price-sources');sources.replaceChildren();
    for(const s of data.series){sources.append(sourceLink(s.symbol,s.source_url),' ');}
    $('#market-provenance').textContent=`Yahoo Finance adjusted daily closes · USD · US sessions · snapshot retrieved ${data.retrieved_at.slice(0,10)}. 13 Jan–7 Feb 2025. No live feed.`;
  }
  for(const [id,g] of Object.entries(groups)){
    const b=el('button','exposure-button',g.label);b.type='button';b.dataset.group=id;b.addEventListener('click',()=>setGroup(id,true));$('#market-groups').append(b);
  }
  const load=async()=>{
    try {
      promise ||= fetch('./data/deepseek-2025.json',{cache:'no-cache'}).then(r=>{if(!r.ok)throw new Error('Snapshot unavailable');return r.json();}).then(validateSnapshot);
      data=await promise;if(!active)return;
      $('#market-loading').hidden=true;$('#market-body').hidden=false;
      $('#market-events').replaceChildren();
      for(const ev of data.events){const b=el('button','event-button',`${dateLabel(ev.date)} · ${ev.label}`);b.type='button';b.dataset.event=ev.id;b.addEventListener('click',()=>{event=ev.id;selected=eventIndices(data,ev.date).first;render();});$('#market-events').append(b);}
      selected=eventIndices(data,data.events.find(e=>e.id===event).date).first;render();
    } catch {
      promise=undefined;$('#market-loading').hidden=false;$('#market-loading').replaceChildren(el('p','','Historical prices could not be loaded. The mechanism map still works.'));
      const b=el('button','', 'Retry prices');b.type='button';b.addEventListener('click',load);$('#market-loading').append(b);
    }
  };
  $('#market-mode').addEventListener('change',e=>{mode=e.target.value;render();});
  $('#market-window').addEventListener('change',e=>{window=e.target.value;render();});
  $('#market-date').addEventListener('input',e=>{selected=Number(e.target.value);render();});
  plot.addEventListener('pointermove',e=>{
    if(!chartGeometry||!data)return;
    const box=plot.getBoundingClientRect(),xx=(e.clientX-box.left)/box.width*chartGeometry.width;
    const {lo,hi,x}=chartGeometry;let nearest=lo;
    for(let i=lo+1;i<=hi;i++)if(Math.abs(x(data.dates[i])-xx)<Math.abs(x(data.dates[nearest])-xx))nearest=i;
    if(nearest!==selected){selected=nearest;render();}
  });
  new ResizeObserver(()=>{if(active&&data)render();}).observe($('#market-chart-frame'));
  return {
    setCase(id){active=id==='open-model-release';root.hidden=!active;if(active){group='all';visible=new Set(groups.all.symbols);load();}},
    focusGroup(id,notify=false){setGroup(id,notify);},
    open(id='all'){if(!active)return;setGroup(id,true);root.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});$('#market-groups button[data-group="'+id+'"]').focus({preventScroll:true});},
    state
  };
}
