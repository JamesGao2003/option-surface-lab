'use strict';
const DATA=JSON.parse(document.getElementById('dataset').textContent);
const $=id=>document.getElementById(id);
const contracts=new Map(DATA.contracts.map(c=>[c.ric,c]));
const byDate=new Map(DATA.dates.map(d=>[d,new Map()]));
for(const [d,ric,mid,trade] of DATA.records)byDate.get(d).set(ric,{...contracts.get(ric),mid,trade});
const spotByDate=new Map(DATA.stock.map(r=>[r[0],r[4]]));
const MID='#6aa5ff',TRADE='#ffb45a',GRID='#29374f',BG='#111b2d',TEXT='#d7e3f7';
const present=v=>v!==null&&v!==undefined&&Number.isFinite(v);
const dte=(expiry,date)=>Math.round((Date.parse(expiry+'T00:00:00Z')-Date.parse(date+'T00:00:00Z'))/86400000);
const median=a=>{if(!a.length)return null;const s=[...a].sort((a,b)=>a-b),i=Math.floor(s.length/2);return s.length%2?s[i]:(s[i-1]+s[i])/2;};
const money=(v,n=2)=>present(v)?'$'+v.toFixed(n):'N/A';
const config={responsive:true,displaylogo:false,scrollZoom:false,toImageButtonOptions:{format:'png',scale:2}};
const base={paper_bgcolor:BG,plot_bgcolor:BG,font:{family:'Arial, sans-serif',color:TEXT,size:12},margin:{l:60,r:20,t:30,b:65},hoverlabel:{font:{size:13}},colorway:[MID,TRADE]};
const axis=(title,more={})=>({title:{text:title},gridcolor:GRID,zerolinecolor:GRID,...more});
function stats(date,side){
 const rows=[...(byDate.get(date)||new Map()).values()].filter(r=>r.type===side);
 const eligible=DATA.contracts.filter(c=>c.type===side&&c.first_seen&&c.first_seen<=date&&date<=c.expiry);
 const midOnly=rows.filter(r=>present(r.mid)&&!present(r.trade)).length;
 const pairs=rows.filter(r=>present(r.mid)&&present(r.trade));
 return {rows,eligible,midOnly,pairs,percent:eligible.length?100*midOnly/eligible.length:null,median:median(pairs.map(r=>Math.abs(r.mid-r.trade)))};
}
function drawStock(date){
 const rows=DATA.stock;
 Plotly.react('stock-chart',[{type:'candlestick',x:rows.map(r=>r[0]),open:rows.map(r=>r[1]),high:rows.map(r=>r[2]),low:rows.map(r=>r[3]),close:rows.map(r=>r[4]),name:'UUUU stock',increasing:{line:{color:MID}},decreasing:{line:{color:TRADE}}}],{
 ...base,margin:{l:60,r:20,t:15,b:45},xaxis:axis('',{type:'date',rangeslider:{visible:false},rangebreaks:[{bounds:['sat','mon']}]}),yaxis:axis('Stock price ($)'),showlegend:false,
 shapes:[{type:'line',xref:'x',yref:'paper',x0:date,x1:date,y0:0,y1:1,line:{color:'#bdcce6',width:1,dash:'dot'}}]
 },config);
}
function render(){
 const date=$('date').value,side=$('side').value,s=stats(date,side),spot=spotByDate.get(date);
 $('chart-title').textContent=`${side}s · ${date}`;
 $('eligible').textContent=String(s.eligible.length);
 $('eligible-detail').textContent=`${s.rows.length} with at least one price today`;
 $('pct').textContent=present(s.percent)?s.percent.toFixed(1)+'%':'N/A';
 $('pct-detail').textContent=`${s.midOnly} mid-only / ${s.eligible.length} sampled active series`;
 $('median').textContent=money(s.median,3);
 $('median-detail').textContent=`${s.pairs.length} contracts with both fields`;
 $('spot').textContent=money(spot);
 $('denominator').textContent='Listing proxy: first observed price ≤ as-of date ≤ expiry; includes sample contracts with neither field today. Full listed-universe percentage is unavailable.';
 const fieldSpec=[['mid','MID_PRICE',MID,'circle'],['trade','TRDPRC_1',TRADE,'diamond']];
 const traces=fieldSpec.map(([field,name,color,symbol])=>{
   const rows=s.rows.filter(r=>present(r[field]));
   return {type:'scatter3d',mode:'markers',name,visible:$(field).checked,x:rows.map(r=>dte(r.expiry,date)),y:rows.map(r=>r.strike),z:rows.map(r=>r[field]),
     marker:{size:4.5,color,symbol,opacity:.92,line:{width:.4,color:'#e8f0ff'}},customdata:rows.map(r=>[r.ric,r.expiry]),
     hovertemplate:'%{customdata[0]}<br>Expiry: %{customdata[1]}<br>DTE: %{x}<br>Strike: $%{y:.2f}<br>'+name+': $%{z:.4f}<extra></extra>'};
 });
 const noVisible=!traces.some(t=>t.visible&&t.x.length);
 $('empty').hidden=!noVisible;
 $('empty').textContent=s.rows.length?'No points are visible for the selected fields; turn on a price series.':`No ${side.toLowerCase()} price observations were returned for this date; missing data or failed requests do not prove that these contracts never traded.`;
 Plotly.react('cloud',traces,{...base,margin:{l:0,r:0,t:12,b:5},showlegend:false,uirevision:'option-cloud-camera',scene:{bgcolor:BG,xaxis:axis('Days to expiry'),yaxis:axis('Strike ($)'),zaxis:axis('Option price ($)',{rangemode:'tozero'}),camera:{eye:{x:1.55,y:1.55,z:1.0}},aspectmode:'manual',aspectratio:{x:1.3,y:1.25,z:.85}}},config);
 const candidateGrid=DATA.contracts.filter(c=>c.type===side&&c.expiry>=date);
 const strikes=[...new Set(candidateGrid.map(c=>c.strike))].sort((a,b)=>a-b);
 const expiries=[...new Set(candidateGrid.map(c=>c.expiry))].sort();
 const index=new Map(candidateGrid.map(c=>[c.expiry+'|'+c.strike,c]));
 const observed=byDate.get(date)||new Map();
 const labels=['No observation','Request failed','Trade only','Mid only','Both'];
 const z=[],texts=[];
 for(const strike of strikes){
   const zr=[],tr=[];
   for(const expiry of expiries){
     const c=index.get(expiry+'|'+strike),r=c?observed.get(c.ric):null;
     const state=r?(present(r.mid)&&present(r.trade)?4:present(r.mid)?3:2):c?.status==='request_failed'?1:0;
     zr.push(state);tr.push(`${c?.ric||'Not requested'}<br>${labels[state]}<br>Expiry: ${expiry}<br>Strike: $${strike.toFixed(2)}`);
   }z.push(zr);texts.push(tr);
 }
 const colors=['#303b51','#985e87',TRADE,MID,'#61dacb'];
 const scale=colors.flatMap((c,i)=>[[i/5,c],[(i+1)/5,c]]);
 Plotly.react('coverage',[{type:'heatmap',x:expiries,y:strikes,z,text:texts,hovertemplate:'%{text}<extra></extra>',zmin:-.5,zmax:4.5,colorscale:scale,showscale:false,xgap:3,ygap:3}],{...base,margin:{l:60,r:5,t:20,b:85},xaxis:axis('Expiration date',{type:'category',tickangle:-35}),yaxis:axis('Strike ($)',{dtick:.5}),annotations:expiries.length?[]:[{text:'No requested expiries remain',showarrow:false,x:.5,y:.5,xref:'paper',yref:'paper'}]},config);
 const max=s.pairs.length?Math.max(...s.pairs.flatMap(r=>[r.mid,r.trade]))*1.08:1;
 Plotly.react('comparison',[{type:'scatter',mode:'lines',x:[0,max],y:[0,max],name:'Mid = trade',line:{color:'#91a1ba',dash:'dot',width:1},hoverinfo:'skip'},{type:'scatter',mode:'markers',x:s.pairs.map(r=>r.mid),y:s.pairs.map(r=>r.trade),name:side+'s',marker:{color:TRADE,size:7,opacity:.8},text:s.pairs.map(r=>r.ric),hovertemplate:'%{text}<br>MID_PRICE: $%{x:.4f}<br>TRDPRC_1: $%{y:.4f}<extra></extra>'}],{...base,showlegend:false,xaxis:axis('MID_PRICE ($)',{range:[0,max]}),yaxis:axis('TRDPRC_1 ($)',{range:[0,max]}),annotations:s.pairs.length?[]:[{text:'No contracts with both fields',showarrow:false,x:.5,y:.5,xref:'paper',yref:'paper'}]},config);
 let density;
 if(s.rows.length){
   const counts=new Map();for(const r of s.rows)counts.set(r.expiry,(counts.get(r.expiry)||0)+1);
   const [expiry,n]=[...counts].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]))[0];
   const dense=s.rows.filter(r=>r.expiry===expiry),low=Math.min(...dense.map(r=>r.strike)),high=Math.max(...dense.map(r=>r.strike));
   const failed=candidateGrid.filter(c=>c.status==='request_failed').length;
   density=`On ${date}, the densest expiry slice for ${side.toLowerCase()}s is ${expiry} with ${n} observed strikes between $${low.toFixed(2)} and $${high.toFixed(2)}; ${candidateGrid.length-s.rows.length} of ${candidateGrid.length} requested strike–expiry cells have neither price, including ${failed} unresolved requests, so empty regions are coverage gaps rather than zero prices.`;
 }else density=`On ${date}, the ${side.toLowerCase()} price cloud is empty across the requested grid because the cache contains no observations for this selection; this is a data-coverage result and does not establish that the contracts were unlisted or never traded.`;
 $('answer-density').textContent=density;
 drawStock(date);
}
$('date').innerHTML=DATA.dates.map(d=>`<option value="${d}">${d}</option>`).join('');$('date').value=DATA.default_date;
$('snapshot').textContent=DATA.fetched_at.slice(0,19).replace('T',' ')+' UTC';
const a=DATA.audit;
$('quality-note').textContent=DATA.settings.schema_version===2 ? `Correction pending · ${a.calls} calls with observations · the initial put RIC suffixes were incorrect; all 221 put candidates require a corrected pull, including ${a.failed_requests} failures. Call observations are retained.` : `${a.failed_requests ? 'Partial' : 'Cached'} snapshot · ${a.observed_contracts} observed contracts (${a.calls} calls / ${a.puts} puts) · ${a.failed_requests} unresolved requests · listing coverage remains a sample.`;
$('provenance').textContent=`LSEG CodeBook pull: ${DATA.settings.start}–${DATA.settings.end}; $${DATA.settings.strike_step.toFixed(2)} strike spacing and Friday expiries, using the full-window stock high/low band; ${a.candidate_count} candidate RICs, ${a.observed_contracts} observed contracts, ${a.mid_count.toLocaleString()} mid observations and ${a.trade_count.toLocaleString()} trade observations.`;
$('audit-detail').textContent=`${a.candidate_count} requested = ${a.observed_contracts} observed + ${a.no_observations} returned without observations + ${a.failed_requests} request failures; ${a.duplicates} duplicate contract/date rows and ${a.negative_prices} negative prices. Stock dates begin ${a.stock_first}; an option date without a same-day stock close shows N/A. Source cache: ${DATA.cache_name}.`;
$('hash').textContent='Source cache SHA-256: '+a.cache_sha256;
for(const id of ['date','side','mid','trade'])$(id).addEventListener('change',render);
render();
// Optional imperative interface for agents/browsers with WebMCP support.
if(navigator.modelContext?.registerTool){navigator.modelContext.registerTool({name:'select_option_snapshot',description:'Select an available date and Call or Put to inspect cached option prices and metrics.',inputSchema:{type:'object',properties:{date:{type:'string',enum:DATA.dates},side:{type:'string',enum:['Call','Put']}},required:['date','side']},execute:async({date,side})=>{if(!DATA.dates.includes(date)||!['Call','Put'].includes(side))throw Error('Invalid date or option type');$('date').value=date;$('side').value=side;render();const s=stats(date,side);return {content:[{type:'text',text:JSON.stringify({date,side,denominator:s.eligible.length,mid_only:s.midOnly,percent:s.percent,paired:s.pairs.length,median:s.median})}]};}});}
