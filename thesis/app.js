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
  const layout = extra => Object.assign({margin: {l: 52, r: 18, t: 10, b: 40}, paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    font: {family: 'Inter, ui-sans-serif, system-ui, sans-serif', size: 12, color: C.ink}, hovermode: 'x unified',
    legend: {orientation: 'h', y: 1.12, x: 0}, xaxis: {gridcolor: C.line, linecolor: C.line}, yaxis: {gridcolor: C.line, zerolinecolor: '#9ca99e'}}, extra);
  const cfg = {displayModeBar: false, responsive: true};

  (async () => {
    const [t, A] = await Promise.all([get('tracker.json'), get('alpha_long.json')]);
    if (!t) { $('status').className = 'notice warning'; $('status').innerHTML = '<span class="status-dot"></span><div><strong>tracker.json did not load</strong><p>The nightly run has not written it, or the file is missing.</p></div>'; return; }

    // ---- header numbers ---------------------------------------------------------------------------
    const L = t.latest, S = t.latest_settled, st = t.stats;
    text('h-iv', num(L.iv, 1)); text('h-rv', num(L.rv, 1)); text('h-gap', signed(S.gap_settled, 1) + ' pts'); text('h-date', L.date);
    text('h-upd', t.updated_utc + ' UTC');
    const tripped = t.tests.filter(x => x.tripped);
    $('status').className = 'notice' + (tripped.length ? ' warning' : '');
    $('status').innerHTML = `<span class="status-dot"></span><div><strong>${tripped.length ? tripped.length + ' wrong-if test' + (tripped.length > 1 ? 's' : '') + ' tripped: I would stop selling.' : 'All three wrong-if tests are clear as of ' + esc(L.date) + '.'}</strong><p>Month ending ${esc(S.date)}: the market had priced ${num(S.implied_then, 1)}% volatility, Apple delivered ${num(S.rv, 1)}%. Gap ${signed(S.gap_settled, 1)} points. Since ${esc(st.from.slice(0, 4))} the gap has been positive on ${num(st.share_positive, 0)}% of days.</p></div>`;
    text('m-share', num(st.share_positive, 0) + '%'); text('m-share-note', `${st.days.toLocaleString()} sessions, ${st.from} to ${st.to}`);
    text('m-gap', signed(st.mean_gap, 1)); text('m-gap-note', `implied ${num(st.mean_implied, 1)} vs realised ${num(st.mean_realised, 1)}; median gap ${signed(st.median_gap, 1)}`);
    text('m-2y', signed(st.last2y_mean_gap, 1)); text('m-2y-note', `positive on ${num(st.last2y_share_positive, 0)}% of days in the last two years`);
    text('m-now', signed(S.gap_avg250, 1)); text('m-now-note', `250 sessions to ${S.date}; wrong-if test 1 trips at 0`);

    // ---- tracker chart ----------------------------------------------------------------------------
    const s = t.series.filter(r => fin(r.gap_settled));
    const x = s.map(r => r.date);
    Plotly.newPlot('tracker-chart', [
      {x, y: s.map(r => r.implied_then), name: 'Implied a month earlier (Apple VIX, 21 sessions back)', mode: 'lines', line: {color: C.blue, width: 1.6}, hovertemplate: '%{y:.1f}'},
      {x, y: s.map(r => r.rv), name: 'What Apple then did (21-session realised)', mode: 'lines', line: {color: C.ink, width: 1.6}, hovertemplate: '%{y:.1f}'},
      {x, y: s.map(r => r.gap_settled), name: 'Gap', type: 'bar', yaxis: 'y2', marker: {color: s.map(r => r.gap_settled >= 0 ? 'rgba(23,100,78,.55)' : 'rgba(163,64,54,.65)')}, hovertemplate: '%{y:+.1f}'},
      {x, y: s.map(r => r.gap_avg250), name: 'One-year average of the gap', mode: 'lines', yaxis: 'y2', line: {color: C.amber, width: 2}, hovertemplate: '%{y:+.1f}'}
    ], layout({height: 520, grid: {rows: 2, columns: 1, roworder: 'top to bottom'}, bargap: 0,
      yaxis: {domain: [0.46, 1], title: {text: 'Annualised volatility, %'}, gridcolor: C.line},
      yaxis2: {domain: [0, 0.38], title: {text: 'Gap, vol points'}, gridcolor: C.line, zerolinecolor: C.ink, zerolinewidth: 1.2},
      xaxis: {anchor: 'y2', gridcolor: C.line},
      shapes: [{type: 'line', xref: 'x', yref: 'paper', x0: t.inception, x1: t.inception, y0: 0, y1: 1, line: {color: C.muted, width: 1, dash: 'dot'}}],
      annotations: [{x: t.inception, xref: 'x', yref: 'paper', y: 1.0, text: 'thesis written', showarrow: false, xanchor: 'right', font: {size: 10, color: C.muted}}]}), cfg);
    text('tracker-caption', `Sources: Cboe Apple VIX (VXAPL) from FRED, with Yahoo for days FRED has not posted yet; Apple closes from the course server's Interactive Brokers bars, Yahoo before ${'2026-09-23'}. Last bar ${L.date}. Rebuilt ${t.updated_utc} UTC by the nightly Action.`);

    // ---- by year ----------------------------------------------------------------------------------
    Plotly.newPlot('year-chart', [
      {x: t.years.map(y => y.year), y: t.years.map(y => y.gap), type: 'bar', marker: {color: t.years.map(y => y.gap >= 0 ? C.green : C.red)},
       text: t.years.map(y => y.share_positive.toFixed(0) + '%'), textposition: 'outside', cliponaxis: false, hovertemplate: '%{x}: gap %{y:+.1f} pts<extra></extra>'}
    ], layout({height: 300, hovermode: 'closest', showlegend: false, yaxis: {title: {text: 'Average gap, vol points'}, gridcolor: C.line, zerolinecolor: C.ink}, xaxis: {type: 'category', linecolor: C.line}}), cfg);

    // ---- live record ------------------------------------------------------------------------------
    const live = t.live.slice().reverse();
    $('live').tBodies[0].innerHTML = live.map(r => '<tr>' + cell(r.date) + cell('$' + num(r.close, 2)) + cell(num(r.iv, 2)) + cell(num(r.rv, 2)) + cell(num(r.implied_then, 2)) + cell(signed(r.gap_settled, 2), tone(r.gap_settled)) + cell(signed(r.gap_avg250, 2), tone(r.gap_avg250)) + '</tr>').join('') || '<tr><td colspan="7">No sessions since the thesis was written yet.</td></tr>';
    text('live-caption', `${live.length} session${live.length === 1 ? '' : 's'} since ${t.inception}. One row is added each night.`);

    // ---- wrong-if tests ---------------------------------------------------------------------------
    $('tests').tBodies[0].innerHTML = t.tests.map(x => '<tr>' + cell(x.label) + cell(fin(x.value) ? x.value + (x.unit ? ' ' + x.unit : '') : '—') + cell(x.threshold) + cell(x.as_of || '—') + `<td><span class="pill ${x.tripped ? 'bad' : 'good'}">${x.tripped ? 'TRIPPED' : 'clear'}</span></td></tr>`).join('');

    // ---- alpha: six years of real quotes ----------------------------------------------------------
    if (A) {
      const row = (label, r) => '<tr>' + cell(label) + cell(r.weeks) + cell(num(r.premium_pct, 2) + '%') + cell(num(r.payoff_pct, 2) + '%') + cell(signed(r.mean_week_pct, 2) + '%', tone(r.mean_week_pct)) + cell(signed(r.ann_pct, 1) + '%', tone(r.ann_pct)) + cell(num(r.ann_vol_pct, 1) + '%') + cell(signed(r.t_stat, 2)) + cell(num(r.win_pct, 0) + '%') + cell(signed(r.worst_week_pct, 1) + '%', 'neg') + '</tr>';
      const S6 = A.summary, S2 = A.last2y;
      $('alpha-table').tBodies[0].innerHTML =
        row('The put my script sells (about 4.6% below the stock)', S6.rule_put) +
        row('At-the-money put', S6.atm_put) + row('At-the-money call', S6.atm_call) +
        row('At-the-money put + call together', S6.straddle) +
        '<tr class="sub"><td colspan="10">Last two years only</td></tr>' +
        row('The put my script sells', S2.rule_put) + row('At-the-money put + call together', S2.straddle);
      text('alpha-caption', `${A.weeks_with_quotes} of ${A.weeks_total} weeks had quotes, ${A.window[0]} to ${A.window[1]}. Sold at the first session's closing bid, held to expiry, settled at the expiry-day close, $0.65 a contract. Return is on the strike. The rule's put skips weeks after an 8% drop in ten sessions, as the live script does, which is why it has fewer weeks. The at-the-money put and call rows are mostly a bet on direction: Apple roughly tripled over these six years, so puts paid and calls lost. Together they cancel that out.`);
      const yrs = A.by_year.rule_put.map(y => y.year), sy = Object.fromEntries(A.by_year.straddle.map(y => [y.year, y.sum_pct]));
      Plotly.newPlot('alpha-year-chart', [
        {x: yrs, y: A.by_year.rule_put.map(y => y.sum_pct), name: 'The put my script sells', type: 'bar', marker: {color: C.green}, hovertemplate: '%{y:+.1f}%'},
        {x: yrs, y: yrs.map(y => sy[y]), name: 'At-the-money put + call', type: 'bar', marker: {color: '#9ca99e'}, hovertemplate: '%{y:+.1f}%'}
      ], layout({height: 300, barmode: 'group', yaxis: {title: {text: 'Kept in the year, % of strike'}, gridcolor: C.line, zerolinecolor: C.ink}, xaxis: {type: 'category', linecolor: C.line}}), cfg);
      const w = A.straddle_weeks;
      Plotly.newPlot('move-chart', [
        {x: w.map(r => r.week), y: w.map(r => r.actual_move_pct), name: 'What happened: |expiry close − strike|', type: 'bar', marker: {color: w.map(r => r.actual_move_pct > r.implied_move_pct ? 'rgba(163,64,54,.8)' : 'rgba(23,100,78,.5)')}, hovertemplate: '%{y:.2f}%'},
        {x: w.map(r => r.week), y: w.map(r => r.implied_move_pct), name: 'Priced in: put + call mid, % of strike', mode: 'lines', line: {color: C.blue, width: 1.6, shape: 'hv'}, hovertemplate: '%{y:.2f}%'}
      ], layout({height: 340, yaxis: {title: {text: 'One-week move, %'}, gridcolor: C.line}, bargap: 0.15}), cfg);
      text('move-caption', `${w.length} weeks. Average priced in ${num(S6.straddle.implied_move_pct, 2)}%, average move ${num(S6.straddle.actual_move_pct, 2)}%. The price was above the move in ${S6.straddle.weeks_market_overpaid} weeks (${(100 * S6.straddle.weeks_market_overpaid / w.length).toFixed(0)}%); the red bars are the weeks it wasn't.`);
    }
  })();
})();
