/* OCI monitoring chart controls, time-based plots and minute-level refresh. */
(() => {
  const definitions = [
    ['cpu', 'CPU 占用率', '%'], ['memory', '内存使用率', '%'],
    ['network_in', '网络接收速率', 'Mbps'], ['network_out', '网络发送速率', 'Mbps'],
    ['disk_read', '磁盘读取速率', 'MB/s'], ['disk_write', '磁盘写入速率', 'MB/s']
  ];
  const intervals = [['auto','自动'], ['1m','1 分钟'], ['5m','5 分钟'], ['1h','1 小时'], ['1d','1 天']];
  const stats = [['mean','均值'],['min','最小值'],['max','最大值'],['sum','总和'],['count','计数'],['rate','速率'],['p50','P50'],['p90','P90'],['p95','P95'],['p99','P99'],['p999','P99.9']];
  const colors = ['#5bdfc2', '#83aaff', '#f7c569', '#f791a5', '#c49aff'];
  const sec = {'1m':60,'5m':300,'1h':3600,'1d':86400};
  const charts = [];
  const $ = (tag, text, cls) => { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n; };
  const svg = (tag, attrs={}) => { const n=document.createElementNS('http://www.w3.org/2000/svg',tag); Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v)); return n; };
  const choose = values => { const el=document.createElement('select'); for(const [v,label] of values){const o=$('option',label);o.value=v;el.append(o)}return el; };
  const fmtTime = t => new Date(t).toLocaleString(undefined,{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
  const plotTime = t => new Date(t).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'});
  const convert = (key, v) => key.startsWith('network_') ? v * 8 / 1e6 : key.startsWith('disk_') ? v / 1e6 : v;
  const autoInterval = range => range==='7d'?'1h':range==='24h'?'5m':'1m';
  const rangeSelect=document.getElementById('chart-range'), endInput=document.getElementById('chart-end'), status=document.getElementById('chart-status');
  let generation=0;
  function unitFor(c,data){if(c.key!=='cpu'&&c.key!=='memory')return c.unit; if(data.statistic==='count')return '次'; if(data.statistic==='rate')return '%/s'; if(data.statistic==='sum')return '%（累计样本值）'; return '%';}
  function draw(c) {
    if(!c.data)return;
    const data=c.data,start=Date.parse(data.start),end=Date.parse(data.end),unit=unitFor(c,data);
    const series=data.series.map((s,i)=>({name:s.name,error:s.error,color:colors[i%colors.length],points:s.points.map(p=>({time:Date.parse(p.timestamp),value:convert(c.key,p.value)})).filter(p=>Number.isFinite(p.time)&&Number.isFinite(p.value)).sort((a,b)=>a.time-b.time)}));
    c.plot.replaceChildren();c.legend.replaceChildren();
    for(const s of series){const el=$('span',s.name+(s.error?' · 查询失败':''));el.style.color=s.color;c.legend.append(el)}
    const points=series.flatMap(s=>s.points), width=700,height=220,L=53,R=16,T=10,B=30;
    const graph=svg('svg',{viewBox:`0 0 ${width} ${height}`,role:'img','aria-label':c.title+'时间趋势'}); c.plot.append(graph);
    if(!points.length){c.message.textContent=series.some(s=>s.error)?'指标查询失败，请检查连接和权限':'所选范围暂无指标数据';c.message.className='chart-message notice';c.tip.textContent='';c.unitLabel.textContent='单位：'+unit+' · '+data.interval+' · '+fmtTime(data.queried_at*1000)+' 查询';c.table.replaceChildren();return}
    c.message.textContent='';let max=Math.max(...points.map(p=>p.value),0),min=Math.min(...points.map(p=>p.value),0);
    if((c.key==='cpu'||c.key==='memory')&&['mean','min','max','p50','p90','p95','p99','p999'].includes(data.statistic)){max=Math.max(100,max);min=Math.min(0,min)}else{max=max<=0?1:max*1.1;min=min<0?min*1.1:0}
    const X=t=>L+(t-start)/(end-start)*(width-L-R),Y=v=>T+(max-v)/(max-min)*(height-T-B);
    for(let i=0;i<=4;i++){let y=T+i*(height-T-B)/4, val=max-i*(max-min)/4;graph.append(svg('line',{x1:L,y1:y,x2:width-R,y2:y,stroke:'#344860'}));let label=svg('text',{x:L-7,y:y+4,'text-anchor':'end',fill:'#9aacbf','font-size':'11'});label.textContent=val>=100?val.toFixed(0):val.toFixed(1);graph.append(label)}
    for(let i=0;i<=4;i++){let x=L+i*(width-L-R)/4,t=start+i*(end-start)/4;let label=svg('text',{x,y:height-8,'text-anchor':i===0?'start':i===4?'end':'middle',fill:'#9aacbf','font-size':'11'});label.textContent=data.range==='7d'?fmtTime(t):plotTime(t);graph.append(label)}
    for(const s of series){let segment=[];function flush(){if(segment.length>1)graph.append(svg('polyline',{points:segment.join(' '),fill:'none',stroke:s.color,'stroke-width':'2','vector-effect':'non-scaling-stroke'}));else if(segment.length===1){let [x,y]=segment[0].split(',');graph.append(svg('circle',{cx:x,cy:y,r:'2',fill:s.color}))}segment=[]}let prev=null;for(const p of s.points){if(prev!==null&&p.time-prev>sec[data.interval]*2200)flush();segment.push(X(p.time)+','+Y(p.value));prev=p.time}flush()}
    graph.addEventListener('pointermove',ev=>{let rect=graph.getBoundingClientRect(),xx=(ev.clientX-rect.left)/rect.width*width,t=start+(xx-L)/(width-L-R)*(end-start);const pieces=[];for(const s of series){if(!s.points.length)continue;let p=s.points.reduce((best,x)=>Math.abs(x.time-t)<Math.abs(best.time-t)?x:best);if(Math.abs(p.time-t)<=sec[data.interval]*1500)pieces.push(s.name+' '+fmtTime(p.time)+'：'+p.value.toFixed(2)+' '+unit)}c.tip.textContent=pieces.length?pieces.join('　 |　 '):'此时间附近无数据'});
    graph.addEventListener('pointerleave',()=>c.tip.textContent='将鼠标移到图上查看各服务器数值');
    c.tip.textContent='将鼠标移到图上查看各服务器数值';c.unitLabel.textContent='单位：'+unit+' · '+data.interval+' · '+fmtTime(data.queried_at*1000)+' 查询';
    if(c.tableVisible)renderTable(c,series,unit);
  }
  function renderTable(c,series,unit){c.table.replaceChildren();const rows=series.flatMap(s=>s.points.map(p=>({name:s.name,...p}))).sort((a,b)=>b.time-a.time);const note=$('p','按时间倒序显示最近最多 200 条记录。','muted');c.table.append(note);const table=$('table'),head=$('tr');for(const x of ['时间（本机时区）','服务器','数值（'+unit+'）'])head.append($('th',x));table.append(head);for(const x of rows.slice(0,200)){const tr=$('tr');for(const v of [new Date(x.time).toLocaleString(),x.name,x.value.toFixed(3)])tr.append($('td',v));table.append(tr)}c.table.append(table)}
  async function load(c, token) {
    const seq=++c.seq;
    const range=rangeSelect.value;let interval=c.interval.value==='auto'?autoInterval(range):c.interval.value;
    if(range==='7d'&&interval==='1m'){c.interval.value='5m';interval='5m';status.textContent='7 天范围已改用 5 分钟间隔，以控制查询量。'}
    c.message.textContent='正在从 OCI 获取数据…';c.message.className='chart-message muted';
    const q=new URLSearchParams({metric:c.key,range,interval,stat:c.stat.value});if(endInput.value){const selected=new Date(endInput.value);if(!Number.isFinite(selected.getTime())){c.message.textContent='结束时间无效';return}q.set('end',selected.toISOString())}
    try{const res=await fetch('/api/chart?'+q,{cache:'no-store'});if(!res.ok)throw new Error('HTTP '+res.status);const data=await res.json();if(token!==generation||seq!==c.seq)return;c.data=data;draw(c)}catch(err){if(token!==generation||seq!==c.seq)return;c.data=null;c.plot.replaceChildren();c.legend.replaceChildren();c.table.replaceChildren();c.tip.textContent='';c.unitLabel.textContent='';c.message.textContent='获取失败：'+err.message+'；稍后自动重试。';c.message.className='chart-message notice'}
  }
  function reloadAll(){const token=++generation;status.textContent='正在更新各图表；OCI 数据按分钟上报，存在延迟。';Promise.all(charts.map(c=>load(c,token))).then(()=>{if(token===generation)status.textContent='最近刷新 '+new Date().toLocaleTimeString()+(endInput.value?' · 固定历史时间':' · 每 60 秒自动刷新')+' · 数据来自 OCI Monitoring'})}
  function reloadOne(c){load(c,generation)}
  for(const [key,title,unit] of definitions){const card=$('section',undefined,'metric-chart');const header=$('div',undefined,'chart-head');header.append($('h3',title));const tableButton=$('button','表视图','secondary');header.append(tableButton);card.append(header);
    const controls=$('div',undefined,'chart-controls');const interval=choose(intervals),stat=choose((key==='cpu'||key==='memory')?stats:[['rate','速率']]);for(const [label,field] of [['间隔',interval],['统计',stat]]){const el=$('label',label+' ');el.append(field);controls.append(el)}card.append(controls);
    const legend=$('div',undefined,'chart-legend'),unitLabel=$('div','','muted'),plot=$('div',undefined,'chart-plot'),message=$('div','','chart-message'),tip=$('div','','chart-tip muted'),table=$('div',undefined,'tablewrap chart-table');table.hidden=true;card.append(legend,unitLabel,plot,message,tip,table);document.getElementById('chart-grid').append(card);
    const c={key,title,unit,interval,stat,legend,unitLabel,plot,message,tip,table,tableVisible:false,data:null,seq:0};charts.push(c);interval.addEventListener('change',()=>reloadOne(c));stat.addEventListener('change',()=>reloadOne(c));tableButton.addEventListener('click',()=>{c.tableVisible=!c.tableVisible;table.hidden=!c.tableVisible;tableButton.textContent=c.tableVisible?'关闭表视图':'表视图';if(c.data)draw(c)});
  }
  rangeSelect.addEventListener('change',reloadAll);endInput.addEventListener('change',reloadAll);document.getElementById('chart-live').addEventListener('click',()=>{endInput.value='';reloadAll()});document.getElementById('chart-refresh').addEventListener('click',reloadAll);
  reloadAll();setInterval(()=>{if(!endInput.value)reloadAll()},60000);
})();
