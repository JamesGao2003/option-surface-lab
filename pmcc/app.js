'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const book = window.PMCC_BOOK;
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const money = value => finite(value) ? value.toLocaleString('en-US',{style:'currency',currency:'USD',minimumFractionDigits:2,maximumFractionDigits:2}) : '—';
  const price = value => finite(value) ? value.toLocaleString('en-US',{style:'currency',currency:'USD',minimumFractionDigits:2,maximumFractionDigits:4}) : '—';
  const pct = value => finite(value) ? (100 * value).toFixed(2) + '%' : '—';
  const number = value => finite(value) ? value.toLocaleString('en-US') : '—';
  const shortDate = value => value ? new Date(value.length === 10 ? value + 'T12:00:00Z' : value).toLocaleDateString('en-US',{timeZone:'America/New_York',month:'short',day:'numeric',year:'numeric'}) : '—';
  const parts = value => new Intl.DateTimeFormat('sv-SE',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(value));
  const nyIso = value => {const p=Object.fromEntries(parts(value).map(x=>[x.type,x.value]));return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}:00`;};
  const time = value => value ? nyIso(value).replace('T',' ').slice(0,16) : '—';
  const month = value => value ? nyIso(value).slice(0,7) : '';
  const names = {PMCC:'PMCC',covered_call:'Stock covered call',buy_hold:'100 shares',long_call:'Long call only'};
  const colors = {PMCC:'#17644e',covered_call:'#4067a7',buy_hold:'#ae7a35',long_call:'#8061a8'};
  const accounts = Object.keys(names);
  const cell = (value, cls='') => `<td${cls ? ` class="${cls}"` : ''}>${esc(value)}</td>`;
  const cashCell = value => cell(money(value),finite(value)&&value<0?'negative':'');
  const text = (id,value) => {$(id).textContent=value;};
  if (!book || !Array.isArray(book.ledger) || !book.summary || /synthetic|fixture|example/i.test(String(book.provenance?.source_kind || ''))) {
    document.querySelectorAll('[data-download]').forEach(a => {a.classList.add('disabled-link');a.setAttribute('aria-disabled','true');a.removeAttribute('href');});
    return;
  }
  const cfg=book.config||{}, quality=book.source_quality||{}, summary=book.summary, funding=book.funding||{}, pm=summary.PMCC||{};
  const initial=pm.initial_cash??cfg.initial_cash;
  const allLedger=book.ledger, allBlotter=book.blotter||[], decisions=book.decisions||[];
  const complete=book.status==='complete';
  const sourceProblems=(quality.missing_mark_rows||0);
  const status=$('status');
  status.className='notice'+(!complete||sourceProblems?' warning':'');
  const statusTitle=book.status==='no_entry'?'No eligible opening trade':complete?'Observed revised backtest complete':'Backtest halted — unresolved exposure retained';
  const qualityText=`${number(quality.short_calls_opened??decisions.filter(d=>d.status==='SELL').length)} short calls opened · ${number(quality.skipped_weeks??decisions.filter(d=>d.status==='SKIP').length)} weeks skipped · ${number(quality.missing_mark_rows||0)} missing held-position account marks. Source gaps and failed alias requests remain in the audit.`;
  status.innerHTML=`<span class="status-dot"></span><div><strong>${esc(statusTitle)}</strong><p>${esc(book.halt ? time(book.halt.time)+' ET: '+book.halt.reason : qualityText)}</p>${book.halt?`<p>${esc(qualityText)}</p>`:''}</div>`;
  text('sample',shortDate(cfg.start)+' — '+shortDate(cfg.end));
  text('budget',money(initial)+' each');
  text('horizon',pm.end_time ? (complete?'Completed ':'Observed through ')+shortDate(pm.end_time) : 'No marked horizon');
  text('capital',money(funding.initial_debit?.PMCC));
  const debitSaving=finite(funding.initial_debit?.covered_call)&&finite(funding.initial_debit?.PMCC)?funding.initial_debit.covered_call-funding.initial_debit.PMCC:null;
  text('saving',money(debitSaving));
  $('saving').nextElementSibling.textContent=finite(funding.capital_saving_vs_cc)?pct(funding.capital_saving_vs_cc)+' less initial outlay; not broker buying power':'Opening debit comparison; not broker buying power';
  text('return',pct(pm.total_return));
  text('drawdown',pct(pm.max_drawdown));
  text('return-note',!finite(pm.ending_nav)?'Ending NAV unavailable; see last common snapshot':pm.realized_only?'Closed positions; spread and fees included':complete?'Net of spread and option fees':'Partial horizon; open positions marked');
  const comparisonRows=accounts.map(a=>{const s=summary[a]||{};return '<tr>'+cell(names[a])+cashCell(funding.initial_debit?.[a])+cashCell(s.ending_nav)+cashCell(s.net_pnl)+cell(pct(s.total_return))+cell(pct(s.max_drawdown))+cashCell(s.fees)+'</tr>';});
  $('comparison').tBodies[0].innerHTML=comparisonRows.join('');
  const longPnl=summary.long_call?.net_pnl, ccPnl=summary.covered_call?.net_pnl, holdPnl=summary.buy_hold?.net_pnl;
  const overlay=finite(pm.net_pnl)&&finite(longPnl)?pm.net_pnl-longPnl:null;
  if(finite(pm.net_pnl)){
    const ccDifference=finite(ccPnl)?pm.net_pnl-ccPnl:null;
    let verdict=`The PMCC ${pm.net_pnl>=0?'gained':'lost'} ${money(Math.abs(pm.net_pnl))} (${pct(pm.total_return)}) on the common ${money(initial)} budget.`;
    if(finite(debitSaving)) verdict+=` It used ${money(debitSaving)} less opening cash than the stock covered call`;
    if(finite(ccDifference)) verdict+=`, and ${ccDifference>=0?'outperformed':'underperformed'} that account by ${money(Math.abs(ccDifference))}.`;
    else verdict+='.';
    if(!complete) verdict+=' This is an incomplete, marked result—not a completed six-month track record.';
    text('verdict',verdict);
    text('outcome',`Long-call-only net P&L was ${money(longPnl)}. The weekly short-call overlay contributed ${money(overlay)} after buybacks and fees. It collected ${money(pm.premium_received)} in premium but spent ${money(pm.short_close_cost)} on buybacks before fees. Premium is not profit.`);
    if(finite(holdPnl)) text('tradeoff',`Versus the 100-share account, the PMCC finished ${money(Math.abs(pm.net_pnl-holdPnl))} ${pm.net_pnl>=holdPnl?'ahead':'behind'}. ${finite(overlay)?`The short-call overlay ${overlay>=0?'helped':'hurt'} the long-call position by ${money(Math.abs(overlay))}. `:''}Different delta, time decay and volatility exposure make the opening debit an incomplete risk comparison.`);
  } else {
    text('verdict',book.halt?.reason ? 'No defensible completed performance claim: '+book.halt.reason : 'The current observations do not support a marked ending NAV. Inspect the retained positions and missing-data audit before drawing a performance conclusion.');
    const shortCash=pm.cash_flow_by_leg?.short_calls;
    text('outcome',`The account collected ${money(pm.premium_received)} in gross short-call premium and paid ${money(pm.fees)} in option fees. ${finite(shortCash)?`Net short-leg cash flow, including buybacks and fees, was ${money(shortCash)}. `:''}An unresolved short is still a liability, so this is not a completed profit figure.`);
    text('tradeoff',`Opening the PMCC used ${money(funding.initial_debit?.PMCC)}, versus ${money(funding.initial_debit?.covered_call)} for the stock covered call. This saved cash at entry, but the missing mandatory observation prevents an honest end-of-sample performance comparison.`);
    text('next-step','Resolve the exact missing source observation first. Do not choose a friendlier end date, delete the open short, or silently fill it with a later quote. Then test a later holdout period and broker-specific assignment and margin handling.');
  }
  const shortCycles=allBlotter.filter(e=>e.account==='PMCC'&&e.side==='BUY_TO_CLOSE').map(close=>{
    const entry=allBlotter.find(e=>e.account==='PMCC'&&e.side==='SELL'&&e.instrument===close.instrument&&e.time===close.original_entry_time);
    return entry&&finite(entry.cash_delta)&&finite(close.cash_delta)?{entry,close,pnl:entry.cash_delta+close.cash_delta}:null;
  }).filter(Boolean);
  if(complete&&shortCycles.length){
    const wins=shortCycles.filter(c=>c.pnl>0).length, worst=shortCycles.reduce((a,b)=>a.pnl<b.pnl?a:b);
    text('tradeoff',`${wins} of ${shortCycles.length} short-call cycles made money after fees, yet the overlay ${overlay<0?'lost':'made'} ${money(Math.abs(overlay))} overall. The worst cycle, closing ${shortDate(worst.close.time)}, sold at ${price(worst.entry.fill)} and bought back at ${price(worst.close.fill)}, losing ${money(Math.abs(worst.pnl))} after fees. A high win rate did not offset the cost of the losing calls.`);
  }
  const common=book.last_common_mark;
  if(!complete&&common?.time&&common.accounts?.PMCC){
    const c=common.accounts, snap=c.PMCC, snapOverlay=finite(c.long_call?.pnl)?snap.pnl-c.long_call.pnl:null;
    $('comparison').closest('.panel').insertAdjacentHTML('afterend',`<div class="panel"><div class="panel-heading"><div><h3>Last common observable snapshot</h3><p>${esc(time(common.time))} ET. Marked comparison before the unresolved exit—not a substitute ending date.</p></div><span class="pill">Positions remain open</span></div><div class="table-scroll"><table><thead><tr><th>Strategy</th><th>Marked NAV</th><th>Marked P&amp;L</th><th>Account return</th><th>Liquidation estimate</th></tr></thead><tbody>${accounts.map(a=>'<tr>'+cell(names[a])+cashCell(c[a]?.nav)+cashCell(c[a]?.pnl)+cell(pct(c[a]?.return))+cashCell(c[a]?.liquidation_nav)+'</tr>').join('')}</tbody></table></div><p class="caption">${esc(common.note||'This snapshot books no liquidation and does not repair the missing final quote.')}</p></div>`);
    text('verdict',`The PMCC saved ${money(debitSaving)} (${pct(funding.capital_saving_vs_cc)}) in opening cash. At the last common observable mark (${time(common.time)} ET), it had ${money(snap.pnl)} in marked P&L (${pct(snap.return)}), versus ${money(c.covered_call?.pnl)} for the stock covered call. The later mandatory exit is unresolved, so no completed-period return is claimed.`);
    text('outcome',`At that same snapshot, the long-call-only position had ${money(c.long_call?.pnl)} in marked P&L. The short-call overlay contributed ${money(snapOverlay)} after fees and its remaining marked liability. Collected premium (${money(pm.premium_received)}) is not profit; short buybacks had cost ${money(pm.short_close_cost)}.`);
    text('tradeoff',`At the common snapshot, the 100-share account had ${money(c.buy_hold?.pnl)} in P&L. Lower opening outlay did not give the PMCC equal upside participation. The short overlay and the long call’s different delta, time decay and volatility exposure matter.`);
  }
  text('marks-note',`${number(pm.observed_mark_rows)} observed PMCC NAV marks; ${number(pm.missing_mark_rows||0)} missing. Option marks use midquotes, fills use bid/ask, and gaps are not connected or forward-filled. Observed drawdown may miss intrabar or unmarked losses. ${complete?'All positions closed at the final horizon.':'Unresolved positions remain in the ledger.'}`);
  text('exit-breakdown',`Booked PMCC short-call exits: ${number(pm.take_profit_closes)} at the 50% premium-capture trigger, ${number(pm.early_risk_closes)} at the ITM risk trigger, and ${number(pm.scheduled_expiry_closes)} at the scheduled Friday close. Each buyback includes the $0.65 contract fee. The stock covered call uses the same short trades.`);
  const baseLayout={paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'#fff',font:{family:'system-ui, sans-serif',color:'#53675c',size:11},margin:{l:68,r:24,t:22,b:55},hovermode:'x unified',legend:{orientation:'h',x:0,y:1.11,font:{size:10}},xaxis:{gridcolor:'#edf0e9',title:{text:'New York time',font:{size:10}}},yaxis:{gridcolor:'#edf0e9',tickprefix:'$',zerolinecolor:'#bccabe'},hoverlabel:{bgcolor:'#fff',font:{size:11}}};
  const plotConfig={responsive:true,displaylogo:false,modeBarButtonsToRemove:['select2d','lasso2d','autoScale2d'],toImageButtonOptions:{format:'png',scale:2}};
  const rowsByAccount=Object.fromEntries(accounts.map(a=>[a,allLedger.filter(r=>r.account===a)]));
  function renderNav(){
    if(!window.Plotly||!allLedger.length) return;
    const pnl=$('nav-view').value==='pnl';
    const traces=accounts.map(a=>({name:names[a],x:rowsByAccount[a].map(r=>nyIso(r.time)),y:rowsByAccount[a].map(r=>finite(r.nav)?r.nav-(pnl?(summary[a]?.initial_cash||initial):0):null),type:'scatter',mode:'lines',connectgaps:false,line:{color:colors[a],width:a==='PMCC'?2.8:1.5},hovertemplate:'%{y:$,.2f}<extra>'+names[a]+'</extra>'}));
    traces.push({name:'PMCC liquidation',x:rowsByAccount.PMCC.map(r=>nyIso(r.time)),y:rowsByAccount.PMCC.map(r=>finite(r.liquidation_nav)?r.liquidation_nav-(pnl?initial:0):null),type:'scatter',mode:'lines',connectgaps:false,line:{color:colors.PMCC,width:1.3,dash:'dot'},hovertemplate:'%{y:$,.2f}<extra>PMCC liquidation</extra>'});
    $('nav-chart').innerHTML='';
    Plotly.newPlot('nav-chart',traces,{...baseLayout,yaxis:{...baseLayout.yaxis,title:{text:pnl?'Net P&L ($)':'NAV ($)',font:{size:10}}}},plotConfig);
  }
  if(window.Plotly&&allLedger.length){
    renderNav();
    const drawdownTraces=accounts.map(a=>{let peak=summary[a]?.initial_cash||initial;return {name:names[a],x:rowsByAccount[a].map(r=>nyIso(r.time)),y:rowsByAccount[a].map(r=>{if(!finite(r.nav))return null;peak=Math.max(peak,r.nav);return r.nav/peak-1;}),type:'scatter',mode:'lines',connectgaps:false,line:{color:colors[a],width:a==='PMCC'?2.1:1.1},hovertemplate:'%{y:.2%}<extra>'+names[a]+'</extra>'};});
    Plotly.newPlot('drawdown-chart',drawdownTraces,{...baseLayout,showlegend:false,margin:{l:68,r:24,t:10,b:46},yaxis:{gridcolor:'#edf0e9',tickformat:'.0%',title:{text:'Drawdown',font:{size:10}}}},plotConfig);
  } else if(!window.Plotly){
    $('nav-chart').innerHTML='<div class="chart-empty">Chart library unavailable. The full results remain available in the tables and downloads.</div>';
  }
  $('nav-view').addEventListener('change',renderNav);
  const months=[...new Set(allLedger.map(r=>month(r.time)))].sort();
  $('month-filter').innerHTML='<option value="all">All months</option>'+months.map(m=>`<option value="${esc(m)}">${esc(m)}</option>`).join('');
  function optionCell(row,kind){const qty=row[kind+'_calls'];if(!qty)return '—';return `${qty} × ${row[kind+'_ric']||'call'} / K ${price(row[kind+'_strike'])} / ${row[kind+'_expiry']||'expiry unavailable'}`;}
  function filterTables(){
    const account=$('account-filter').value, selectedMonth=$('month-filter').value;
    const matches=r=>(account==='all'||r.account===account)&&(selectedMonth==='all'||month(r.time)===selectedMonth);
    const events=allBlotter.filter(matches), ledger=allLedger.filter(matches);
    $('blotter').tBodies[0].innerHTML=events.length?events.map(r=>'<tr>'+cell(time(r.time))+cell(names[r.account]||r.account)+cell(r.instrument)+`<td><span class="side ${esc(String(r.side).split('_')[0])}">${esc(r.side)}</span></td>`+cell(r.qty)+cell(price(r.fill))+cashCell(r.fee)+cashCell(r.cash_delta)+cell(r.rule||r.note||'')+'</tr>').join(''):'<tr><td colspan="9" class="empty">No booked trades in this selection.</td></tr>';
    $('ledger').tBodies[0].innerHTML=ledger.length?ledger.map(r=>'<tr>'+cell(time(r.time))+cell(names[r.account]||r.account)+cashCell(r.cash)+cell(r.shares)+cell(optionCell(r,'long'))+cell(optionCell(r,'short'))+cell(price(r.stock_mark))+cell(price(r.long_mark))+cell(price(r.short_mark))+cashCell(r.nav)+cashCell(r.liquidation_nav)+cell(Array.isArray(r.missing_marks)?r.missing_marks.join(', '):r.missing_marks||'—')+'</tr>').join(''):'<tr><td colspan="12" class="empty">No ledger observations in this selection.</td></tr>';
    text('blotter-count',number(events.length)+' events');text('ledger-count',number(ledger.length)+' observations');
  }
  $('account-filter').addEventListener('change',filterTables);$('month-filter').addEventListener('change',filterTables);filterTables();
  text('decision-count',number(decisions.length)+' decisions');
  $('decisions').tBodies[0].innerHTML=decisions.length?decisions.map(r=>'<tr>'+cell(r.time?time(r.time):r.monday)+cell(r.status)+cell(r.ric||'—')+cell(price(r.strike))+cell(r.reason)+'</tr>').join(''):'<tr><td colspan="5" class="empty">No entry decisions.</td></tr>';
  const pooledFit=book.scatter||{}, groupFits=book.regression_by_leg||pooledFit.by_leg||{};
  $('regression').insertAdjacentHTML('beforebegin','<label class="compact-label">Option sample<select id="scatter-leg"><option value="short">Weekly short calls</option><option value="long">Long call</option><option value="pooled">Pooled calls</option></select></label>');
  if(!groupFits.short)$('scatter-leg').value='pooled';
  function renderScatter(){
    const selected=$('scatter-leg').value, fit=selected==='pooled'?pooledFit:(groupFits[selected]||{}), points=fit.points||[];
    text('regression',(selected==='pooled'?'Pooled':'Within-leg')+' R² '+(finite(fit.r2)?fit.r2.toFixed(4):'unavailable'));
    const statRows=[['Paired observations',number(fit.n??points.length)],['OLS slope / intercept',finite(fit.slope)&&finite(fit.intercept)?fit.slope.toFixed(4)+' / '+fit.intercept.toFixed(4):'—'],['Mean |trade − mid|',price(fit.mae)]];
    $('fit-stats').innerHTML=statRows.map(([label,value])=>`<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join('');
    if(!window.Plotly)return;
    if(!points.length){$('scatter-chart').innerHTML='<div class="chart-empty">No observed pairs in this selection</div>';return;}
    $('scatter-chart').innerHTML='';
    const x=points.map(p=>p.mid), y=points.map(p=>p.trade), min=x.reduce((a,b)=>Math.min(a,b),Infinity), max=x.reduce((a,b)=>Math.max(a,b),-Infinity);
    const scatter=[{x,y,type:'scattergl',mode:'markers',name:'Observed bars',marker:{color:'#27755d',size:4,opacity:.35},text:points.map(p=>esc(p.ric)+'<br>'+time(p.time)+' ET'),hovertemplate:'%{text}<br>Mid %{x:$,.4f}<br>Trade %{y:$,.4f}<extra></extra>'}];
    scatter.push({x:[min,max],y:[min,max],name:'Trade = mid',mode:'lines',line:{color:'#9baba0',width:1,dash:'dot'},hoverinfo:'skip'});
    if(finite(fit.slope)&&finite(fit.intercept))scatter.push({x:[min,max],y:[fit.intercept+fit.slope*min,fit.intercept+fit.slope*max],name:'OLS fit',mode:'lines',line:{color:'#c17c36',width:1.5},hoverinfo:'skip'});
    Plotly.newPlot('scatter-chart',scatter,{...baseLayout,hovermode:'closest',xaxis:{gridcolor:'#edf0e9',title:'Quote mid ($)'},yaxis:{gridcolor:'#edf0e9',title:'TRDPRC_1 ($)'},margin:{l:65,r:18,t:34,b:57}},plotConfig);
  }
  $('scatter-leg').addEventListener('change',renderScatter);renderScatter();
  const scenarios=book.stress?.scenarios||[];
  if(scenarios.length){
    $('stress-content').innerHTML=scenarios.map(s=>{
      const fields=[['Scenario time',s.time?time(s.time)+' ET':null],['Hypothetical ending cash',money(s.ending_cash)],['P&L versus initial cash',money(s.pnl_vs_initial_cash)],['Assignment receipt',money(s.assignment_receipt)],['Voluntary exercise payment',money(s.exercise_payment)],['Long time value sacrificed',money(s.long_extrinsic_sacrificed)],['Short stock before exercise',money(s.short_stock_notional_before_exercise)],['Extra exercise funding if assignment cash unavailable',money(s.exercise_funding_if_assignment_proceeds_unavailable)]];
      let html=`<h3>${esc(s.name||'Stress scenario')}</h3><p>${esc(s.assumption||s.description||'')}</p><dl>${fields.filter(([,v])=>v&&v!=='—').map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>`;
      if(s.events?.length)html+='<details><summary>Explicit scenario events</summary><div class="table-scroll"><table class="stress-table"><thead><tr><th>Action</th><th>Cash change</th><th>Shares after</th><th>Long calls after</th><th>Short calls after</th></tr></thead><tbody>'+s.events.map(e=>'<tr>'+cell(e.side)+cashCell(e.cash_delta)+cell(e.shares_after)+cell(e.long_calls_after)+cell(e.short_calls_after)+'</tr>').join('')+'</tbody></table></div></details>';
      return html;
    }).join('<hr>');
    const assignment=scenarios.find(s=>finite(s.long_extrinsic_sacrificed));
    if(assignment)text('stress-summary',`An immediate assignment-and-voluntary-exercise scenario sacrifices ${money(assignment.long_extrinsic_sacrificed)} of marked long-call time value. This is an off-path mechanical scenario, not a forecast or an observed trade.`);
  }
  const execution=book.execution_sensitivity||[];
  if(execution.length){
    $('stress-content').insertAdjacentHTML('beforeend','<hr><h3>Worse fills on the same booked trades</h3><p>'+esc(execution[0].assumption)+'</p><div class="table-scroll"><table><thead><tr><th>Additional price concession</th>'+accounts.map(a=>'<th>'+esc(names[a])+' extra cost</th>').join('')+'</tr></thead><tbody>'+execution.map(s=>'<tr>'+cell(price(s.per_share_slippage)+' per option share')+accounts.map(a=>cashCell(s.accounts?.[a]?.extra_cost)).join('')+'</tr>').join('')+'</tbody></table></div><p>These are additional execution costs on fixed trades. They do not re-simulate how worse executions might change subsequent decisions.</p>');
  }
  const p=book.provenance||{};
  const auditRows=[['Provider',p.provider],['Library',p.library],['Source type',p.source_kind],['Source recorded timestamp',p.completed_utc||p.retrieved_utc||p.created_utc],['Source SHA-256',p.source_sha256],['Rule revision SHA-256',p.strategy_revision_sha256],['Engine',p.engine_version],['Long-call candidates',quality.long_candidate_count],['Short-call candidates',quality.short_candidate_count],['Requests / errors / empty',`${quality.request_count??'—'} / ${quality.request_errors??'—'} / ${quality.empty_requests??'—'}`],['Weeks scheduled / decided',`${quality.scheduled_weeks??'—'} / ${quality.decided_weeks??'—'}`],['Base status',book.status],['Capital convention',funding.note||book.methodology?.capital]];
  $('provenance').innerHTML='<dl>'+auditRows.filter(([,v])=>v!==undefined&&v!==null).map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')+'</dl><h3>Raw-source coverage versus position coverage</h3><p>Seven quotes required by the original selected-position path are absent on August 13–14 for the August 14 $290 call. Minute, hourly and event queries did not recover them. This is not a claim that the entire candidate universe has only seven missing quotes. The original source has not been repaired.</p><p>'+esc(`The revised path has ${number(quality.missing_mark_rows||0)} missing held-position account marks, including ${number(pm.missing_mark_rows||0)} for the PMCC. Closing earlier can remove a later quote requirement; it does not supply the missing quote. The 50% threshold was recorded before the revised run was calculated, after the source gap was known.`)+'</p><p>The original strategy halted on August 14 at 15:00 ET. Its retained book is an audit of that failed path, not a comparable full-period return. Failed alias attempts are also retained when another RIC spelling returns entry-time data; the failed-request count is not the number of missing trades.</p><ul>'+(quality.limitations||[]).map(s=>`<li>${esc(s)}</li>`).join('')+'</ul><div class="download-links"><a href="PMCC_source.json" download>Original source JSON ↗</a><a href="requests.csv" download>Request audit ↗</a><a href="strategy_revision.json" download>Dated rule revision ↗</a><a href="strict_baseline/book.json" download>Original halted book ↗</a><a href="diagnostics/README.md">Quote-recovery evidence ↗</a></div>';
  if(book.requests?.length){
    $('provenance').insertAdjacentHTML('beforeend','<details><summary>Request records ('+number(book.requests.length)+')</summary><div class="table-scroll bounded"><table><thead><tr><th>RIC</th><th>Start</th><th>End</th><th>Status</th><th>Rows</th><th>Error / note</th></tr></thead><tbody>'+book.requests.map(r=>'<tr>'+cell(r.ric)+cell(r.start)+cell(r.end)+cell(r.status)+cell(r.rows)+cell(r.error||r.note||'—')+'</tr>').join('')+'</tbody></table></div></details>');
  }
})();
