const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

class Element {
  constructor(tag) { this.tag=tag; this.children=[]; this.listeners={}; this.style={}; this.value=''; this.hidden=false; this.textContent=''; }
  append(...children) { for (const c of children) { this.children.push(c); if(this.tag==='select' && this.children.length===1) this.value=c.value; } }
  replaceChildren(...children) { this.children=[]; this.append(...children); }
  setAttribute(k,v) { this[k]=String(v); }
  addEventListener(type,fn) { (this.listeners[type] ||= []).push(fn); }
  dispatch(type,ev={}) { for(const fn of this.listeners[type]||[])fn(ev); }
  getBoundingClientRect() { return {left:0,width:700,height:220}; }
}
const ids={}; for(const id of ['chart-range','chart-status','chart-grid','chart-refresh','chart-end','chart-live'])ids[id]=new Element('div'); ids['chart-range'].value='1h';
const calls=[];let intervalMs;
const doc={createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t),getElementById:id=>ids[id]};
const fetch=async url=>{ calls.push(url); const q=new URLSearchParams(url.split('?')[1]);const now=Date.now();return {ok:true,json:async()=>({metric:q.get('metric'),range:q.get('range'),interval:q.get('interval'),statistic:q.get('stat'),start:new Date(now-3600000).toISOString(),end:new Date(now).toISOString(),queried_at:now/1000,series:[{name:'A1',points:[{timestamp:new Date(now-120000).toISOString(),value:10},{timestamp:new Date(now-60000).toISOString(),value:12}]},{name:'E2',points:[{timestamp:new Date(now-120000).toISOString(),value:20},{timestamp:new Date(now-60000).toISOString(),value:22}]}]})}};
const context={document:doc,fetch,URLSearchParams,Date,Number,Math,Promise,setInterval:(_,ms)=>{intervalMs=ms}};
vm.runInNewContext(fs.readFileSync(__dirname+'/chart.js','utf8'),context);
const tick=()=>new Promise(r=>setTimeout(r,0));
(async()=>{
 await tick(); await tick();
 assert.equal(ids['chart-grid'].children.length,6);
 assert.equal(calls.length,6); assert.equal(intervalMs,60000);
 const cpu=ids['chart-grid'].children[0], controls=cpu.children[1], interval=controls.children[0].children[0], stat=controls.children[1].children[0], graph=cpu.children[4].children[0];
 assert(graph.children.some(x=>x.tag==='polyline'),'draws two data series');
 stat.value='p95';stat.dispatch('change');await tick();assert(calls.at(-1).includes('stat=p95'));
 interval.value='1d';interval.dispatch('change');await tick();assert(calls.at(-1).includes('interval=1d'));
 cpu.children[0].children[1].dispatch('click');assert.equal(cpu.children[7].hidden,false);
 ids['chart-range'].value='7d';interval.value='1m';ids['chart-range'].dispatch('change');await tick();assert.equal(interval.value,'5m');
 console.log('动态控件、双实例曲线、P95、间隔、表视图和自动刷新模拟测试通过');
})().catch(e=>{console.error(e);process.exitCode=1});
