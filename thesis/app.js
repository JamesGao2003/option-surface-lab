'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fin = v => typeof v === 'number' && Number.isFinite(v);
  const num = (v, d = 1) => fin(v) ? v.toFixed(d) : '—';
  const signed = (v, d = 1) => fin(v) ? (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d) : '—';
  const text = (id, v) => { const el = $(id); if (el) el.textContent = v; };
  const cell = (v, cls = '') => `<td${cls ? ` class="${cls}"` : ''}>${esc(v)}</td>`;
  const tone = v => !fin(v) ? '' : v > 0 ? 'pos' : v < 0 ? 'neg' : '';
  const get = async url => { try { const r = await fetch(url, {cache: 'no-store'}); if (!r.ok) throw new Error(r.status); return await r.json(); } catch (e) { return null; } };
  const C = {ink: '#162623', muted: '#5d6e67', green: '#17644e', red: '#a34036', amber: '#996317', blue: '#4067a7', line: '#d9dfd8'};
  const narrow = window.innerWidth < 700;   // on a phone the legend goes under the chart so it cannot sit on the lines
  const layout = extra => Object.assign({margin: {l: 52, r: 18, t: 10, b: 40}, paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    font: {family: 'Inter, ui-sans-serif, system-ui, sans-serif', size: 12, color: C.ink}, hovermode: 'x unified',
    legend: narrow ? {orientation: 'h', x: 0, y: -0.16, yanchor: 'top', font: {size: 10}} : {orientation: 'h', y: 1.12, x: 0},
    xaxis: {gridcolor: C.line, linecolor: C.line}, yaxis: {gridcolor: C.line, zerolinecolor: '#9ca99e'}}, extra);
  const cfg = {displayModeBar: false, responsive: true};

  (async () => {
    const [t, A] = await Promise.all([get('tracker.json'), get('alpha_long.json')]);
    if (!t) { $('status').className = 'notice warning'; $('status').innerHTML = '<span class="status-dot"></span><div><strong>tracker.json did not load</strong><p>The nightly run has not written it, or the file is missing.</p></div>'; return; }
    const N = t.tonight, s = t.stats, P = Object.fromEntries(t.by_period.map(p => [p.label, p]));
    const pre = P['Before the rule was published'], post = P['After publication'], now = P['2020 to the thesis date'], two = P['Last two years before the thesis'];

    // ---- tonight ----------------------------------------------------------------------------------
    text('h-state', N.state.charAt(0) + N.state.slice(1).toLowerCase()); text('h-close', '$' + num(N.close, 2)); text('h-rsi', num(N.rsi2, 1));
    text('h-trend', signed(N.pct_from_avg200, 1) + '% (' + (N.above_trend ? 'above' : 'below') + ')'); text('h-date', N.date); text('h-upd', t.updated_utc + ' UTC');
    const tripped = t.tests.filter(x => x.tripped);
    $('status').className = 'notice' + (tripped.length ? ' warning' : '');
    $('status').innerHTML = `<span class="status-dot"></span><div><strong>Tonight (${esc(N.date)}): ${esc(N.state.toLowerCase())}.</strong><p>${esc(N.detail)} ${tripped.length ? tripped.length + ' wrong-if test' + (tripped.length > 1 ? 's are' : ' is') + ' tripped.' : 'All three wrong-if tests are clear.'}</p></div>`;

    // ---- headline numbers -------------------------------------------------------------------------
    text('m-n', String(s.trades)); text('m-n-note', `${s.start} to ${s.end}, about ${num(s.per_year, 0)} a year`);
    text('m-win', num(s.win_pct, 0) + '%'); text('m-win-note', `average win ${signed(s.avg_win_pct, 2)}%, average loss ${signed(s.avg_loss_pct, 2)}%`);
    text('m-avg', signed(s.avg_pct, 2) + '%'); text('m-avg-note', `median ${signed(s.median_pct, 2)}%, t-stat ${num(s.t_stat, 1)}, held ${num(s.avg_days, 1)} sessions`);
    text('m-day', num(s.per_day_held_bp, 0) + ' vs ' + num(s.per_day_always_in_bp, 0) + ' bp'); text('m-day-note', `in the market ${num(s.time_in_market_pct, 0)}% of sessions`);
    text('hz-edge', `It has shown up in every stretch of the last ${num(s.years, 0)} years. Before the rule was published the average trade made ${signed(pre.avg_pct, 2)}%. In the eleven years after, with everyone able to read about it, it made ${signed(post.avg_pct, 2)}%, and since 2020 ${signed(now.avg_pct, 2)}%. So it got smaller once it was public but didn't go away, and I expect it to stay around that smaller size as long as there are funds that must sell into a falling market.`);
    text('hz-trade', `The market usually fixes the overshoot within a week. The average trade is held for ${num(s.avg_days, 1)} sessions and the longest took ${Math.max(...t.trades.map(x => x.days))}. There are about ${num(s.per_year, 0)} trades a year, so the money is in the market only ${num(s.time_in_market_pct, 0)}% of the time.`);

    // ---- price chart ------------------------------------------------------------------------------
    const S = t.series, x = S.map(r => r.date), first = x[0];
    const recent = t.trades.filter(r => r.out >= first);
    const tr = [
      {x, y: S.map(r => r.close), name: 'SPY close', mode: 'lines', line: {color: C.ink, width: 1.7}, hovertemplate: '%{y:.2f}'},
      {x, y: S.map(r => r.avg200), name: '200-day average', mode: 'lines', line: {color: C.amber, width: 1.5, dash: 'dash'}, hovertemplate: '%{y:.2f}'},
      {x: recent.filter(r => r.in >= first).map(r => r.in), y: recent.filter(r => r.in >= first).map(r => r.entry), name: 'Buy at the open', mode: 'markers', marker: {symbol: 'triangle-up', size: 11, color: C.green}, hovertemplate: 'buy %{y:.2f}'},
      {x: recent.map(r => r.out), y: recent.map(r => r.exit), name: 'Sell at the open', mode: 'markers', marker: {symbol: 'triangle-down', size: 11, color: C.red}, hovertemplate: 'sell %{y:.2f}'},
      {x, y: S.map(r => r.rsi2), name: '2-day RSI', mode: 'lines', yaxis: 'y2', line: {color: C.blue, width: 1.2}, hovertemplate: '%{y:.1f}'}
    ];
    if (N.open_trade) tr.push({x: [N.open_trade.in], y: [N.open_trade.entry], name: 'Open trade', mode: 'markers', marker: {symbol: 'triangle-up', size: 13, color: C.green, line: {color: C.ink, width: 2}}, hovertemplate: 'open trade, bought %{y:.2f}'});
    Plotly.newPlot('price-chart', tr, layout({height: 520,
      yaxis: {domain: [0.36, 1], title: {text: 'SPY, $'}, gridcolor: C.line},
      yaxis2: {domain: [0, 0.27], title: {text: 'RSI(2)'}, range: [0, 100], gridcolor: C.line},
      xaxis: {anchor: 'y2', gridcolor: C.line},
      shapes: [{type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y2', y0: t.rule.entry_below, y1: t.rule.entry_below, line: {color: C.red, width: 1, dash: 'dot'}},
               {type: 'line', xref: 'x', yref: 'paper', x0: t.inception, x1: t.inception, y0: 0, y1: 1, line: {color: C.muted, width: 1, dash: 'dot'}}]}), cfg);
    text('price-caption', `Source: Yahoo daily bars for SPY. Last bar ${N.date}: close ${num(N.close, 2)}, 200-day average ${num(N.avg200, 2)}, 5-day average ${num(N.avg5, 2)}, RSI(2) ${num(N.rsi2, 1)}. Rebuilt ${t.updated_utc} UTC by the nightly Action.`);

    // ---- periods ----------------------------------------------------------------------------------
    const prow = (label, r) => '<tr>' + cell(label) + cell(r.trades) + cell(num(r.per_year, 1)) + cell(signed(r.avg_pct, 2) + '%', tone(r.avg_pct)) + cell(signed(r.median_pct, 2) + '%') + cell(num(r.win_pct, 0) + '%') + cell(num(r.t_stat, 1)) + cell(signed(r.worst_pct, 1) + '%', 'neg') + cell(signed(r.sum_per_year_pct, 1) + '%', tone(r.sum_per_year_pct)) + '</tr>';
    $('periods').tBodies[0].innerHTML = prow(`All trades, ${s.start.slice(0, 4)} to ${s.end.slice(0, 4)}`, s) + t.by_period.map(p => prow(`${p.label} (${p.start.slice(0, 4)} to ${p.end.slice(0, 4)})`, p)).join('');

    // ---- equity -----------------------------------------------------------------------------------
    Plotly.newPlot('equity-chart', [{x: [s.start].concat(t.equity.map(e => e.date)), y: [1].concat(t.equity.map(e => e.equity)), mode: 'lines', line: {color: C.green, width: 1.8, shape: 'hv'}, name: 'Rule, after costs', hovertemplate: '$%{y:.2f}'}],
      layout({height: 340, showlegend: false, yaxis: {type: 'log', title: {text: 'Value of $1'}, gridcolor: C.line, tickvals: [1, 1.5, 2, 3, 4, 5], ticktext: ['$1', '$1.5', '$2', '$3', '$4', '$5']},
        shapes: [{type: 'line', xref: 'x', yref: 'paper', x0: t.inception, x1: t.inception, y0: 0, y1: 1, line: {color: C.muted, width: 1, dash: 'dot'}}]}), cfg);
    Plotly.newPlot('year-chart', [{x: t.by_year.map(y => y.year), y: t.by_year.map(y => y.sum_pct), type: 'bar', marker: {color: t.by_year.map(y => y.sum_pct >= 0 ? C.green : C.red)},
      text: t.by_year.map(y => String(y.trades)), textposition: 'outside', cliponaxis: false, hovertemplate: '%{x}: %{y:+.1f}%<extra></extra>'}],
      layout({height: 300, hovermode: 'closest', showlegend: false, yaxis: {title: {text: 'Sum of trades, %'}, gridcolor: C.line, zerolinecolor: C.ink}, xaxis: {type: 'category', linecolor: C.line, tickangle: -60}}), cfg);

    // ---- trades -----------------------------------------------------------------------------------
    const last = t.trades.slice(-15).reverse();
    const openRow = N.open_trade ? '<tr>' + cell(N.open_trade.signal) + cell(N.open_trade.in) + cell(N.open_trade.exit_tomorrow ? 'next open' : 'still held') + cell('') + cell('$' + num(N.open_trade.entry, 2)) + cell('') + cell(N.open_trade.days + 1) + cell(signed(100 * N.open_trade.mark, 2) + '% so far', tone(N.open_trade.mark)) + '<td><span class="pill">open</span></td></tr>' : '';
    const trow = r => '<tr>' + cell(r.signal) + cell(r.in) + cell(r.out) + cell(num(r.rsi, 1)) + cell('$' + num(r.entry, 2)) + cell('$' + num(r.exit, 2)) + cell(r.days) + cell(signed(r.ret_pct, 2) + '%', tone(r.ret_pct)) + `<td>${r.live ? '<span class="pill good">live</span>' : ''}</td></tr>`;
    $('trades').tBodies[0].innerHTML = openRow + last.map(trow).join('');
    text('trades-caption', `${t.live.trades} live trade${t.live.trades === 1 ? '' : 's'} closed since ${t.inception}${t.live.trades ? ', averaging ' + signed(t.live.avg_pct, 2) + '%' : ''}. The full list of ${s.trades} trades is in tracker.json.`);

    // ---- wrong-if tests ---------------------------------------------------------------------------
    $('tests').tBodies[0].innerHTML = t.tests.map(q => '<tr>' + cell(q.label) + cell(q.value) + cell(q.threshold) + cell(q.history) + cell(q.as_of || '—') + `<td><span class="pill ${q.tripped ? 'bad' : 'good'}">${q.tripped ? 'TRIPPED' : 'clear'}</span></td></tr>`).join('');

    // ---- alpha ------------------------------------------------------------------------------------
    const beta = s.per_day_always_in_bp * s.avg_days / 100;       // what the market pays anyone for holding that many days
    text('alpha-size', `Over ${num(s.years, 0)} years the average trade made ${signed(s.avg_pct, 2)}% in ${num(s.avg_days, 1)} sessions. Just holding SPY for that long earns about ${signed(beta, 2)}%, so roughly ${signed(s.avg_pct - beta, 2)}% of each trade is above what the market pays anyone for being long. With ${num(s.per_year, 0)} trades a year that adds up to about ${signed(s.sum_per_year_pct, 1)}% a year on the money, while being invested ${num(s.time_in_market_pct, 0)}% of the time. Per day actually held it is ${num(s.per_day_held_bp, 0)} basis points, against ${num(s.per_day_always_in_bp, 0)} for someone who holds every day.`);
    text('alpha-plan', `I wouldn't plan on the full-history number. The fair guide is what it did after everyone could read the book: ${signed(post.avg_pct, 2)}% a trade from 2009 to 2019 and ${signed(now.avg_pct, 2)}% since 2020. So I'd plan on about ${num(post.sum_per_year_pct, 0)}% a year over cash, and treat anything above that as luck until the live record says otherwise.`);
    text('alpha-cost', `Costs are small here. SPY trades with a one-cent spread on a $${num(N.close, 0)} share, and I assumed ${num(s.cost_per_round_trip_bp, 0)} basis points for each round trip to cover slippage at the open and commission. That is about ${num(s.cost_per_year_pct, 1)}% a year, under a tenth of the average trade, and it is already taken out of the $1 chart above.`);
    text('alpha-risk', `The risk is the shape of the results. The average loss (${signed(s.avg_loss_pct, 2)}%) is bigger than the average win (${signed(s.avg_win_pct, 2)}%), and it only works because ${num(s.win_pct, 0)}% of trades win. The worst trade lost ${num(Math.abs(s.worst_pct), 1)}% and the rule's worst run from a high was ${num(Math.abs(s.worst_drawdown_pct), 1)}%. It lost money in ${s.losing_years.length} calendar years: ${s.losing_years.join(', ')}.`);
    const vrow = r => `<tr${r.label.includes('the rule') ? ' class="hl"' : ''}>` + cell(r.label) + cell(r.trades) + cell(signed(r.avg_pct, 2) + '%', tone(r.avg_pct)) + cell(num(r.win_pct, 0) + '%') + cell(num(r.t_stat, 1)) + cell(signed(r.worst_pct, 1) + '%', 'neg') + cell(signed(r.sum_per_year_pct, 1) + '%', tone(r.sum_per_year_pct)) + '</tr>';
    $('variants').tBodies[0].innerHTML = t.variants.map(vrow).join('');
    $('worst').tBodies[0].innerHTML = t.worst_trades.map(r => '<tr>' + cell(r.in) + cell(r.out) + cell('$' + num(r.entry, 2)) + cell('$' + num(r.exit, 2)) + cell(r.days) + cell(signed(r.ret_pct, 2) + '%', 'neg') + '</tr>').join('');
    if (A) {
      const rp = A.summary.rule_put;
      text('compare', `Apple put: ${rp.weeks} weeks, kept ${signed(rp.ann_pct, 1)}% a year, t-stat ${num(rp.t_stat, 1)}, worst week ${signed(rp.worst_week_pct, 1)}%, lost money over the last two years. This rule: ${s.trades} trades, ${signed(s.sum_per_year_pct, 1)}% a year, t-stat ${num(s.t_stat, 1)}, worst trade ${signed(s.worst_pct, 1)}%, and ${signed(two.avg_pct, 2)}% a trade over the last two years. The evidence for this one is a lot stronger, so I switched.`);
    }

    // ---- macro: tonight's part --------------------------------------------------------------------
    const ot = N.open_trade;
    text('macro-now', (ot
      ? `Right now it is being tested. SPY fell from 739.95 on 16 November to 689.81 on 20 November, and the VIX closed that Friday at 35.9, its highest close of 2026. The rule bought at the open on ${ot.in} at ${num(ot.entry, 2)} and is ${signed(100 * ot.mark, 1)}% on the trade as of ${N.date}. `
      : `SPY fell from 739.95 on 16 November 2026 to 689.81 on 20 November, and the VIX closed that Friday at 35.9, its highest close of 2026. The rule's most recent trade is in the table above. `)
      + (N.above_trend ? `SPY is ${signed(N.pct_from_avg200, 1)}% from its 200-day average, so the rule is allowed to trade.` : `SPY closed ${num(Math.abs(N.pct_from_avg200), 1)}% below its 200-day average, so once this trade is closed the rule takes no new ones until the index is back above it. That is the filter doing its job: the drop was big enough that I can't call the trend intact any more.`));
  })();
})();
