'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const book = window.WHEEL_BOOK, variants = window.WHEEL_VARIANTS || {};
  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fin = v => typeof v === 'number' && Number.isFinite(v);
  const money = v => fin(v) ? v.toLocaleString('en-US', {style:'currency', currency:'USD', minimumFractionDigits:2, maximumFractionDigits:2}) : '—';
  const money0 = v => fin(v) ? v.toLocaleString('en-US', {style:'currency', currency:'USD', maximumFractionDigits:0}) : '—';
  const px = v => fin(v) ? '$' + v.toFixed(2) : '—';
  const pct = v => fin(v) ? (100 * v).toFixed(1) + '%' : '—';
  const pct2 = v => fin(v) ? (100 * v).toFixed(2) + '%' : '—';
  const num = v => fin(v) ? v.toLocaleString('en-US') : '—';
  const sd = v => v ? new Date(v + 'T12:00:00Z').toLocaleDateString('en-US', {timeZone:'UTC', month:'short', day:'numeric', year:'numeric'}) : '—';
  const sdShort = v => v ? new Date(v + 'T12:00:00Z').toLocaleDateString('en-US', {timeZone:'UTC', month:'short', day:'numeric'}) : '—';
  const cell = (v, cls='') => `<td${cls ? ` class="${cls}"` : ''}>${esc(v)}</td>`;
  const cashCell = v => cell(money(v), fin(v) && v < 0 ? 'negative' : '');
  const text = (id, v) => { const el = $(id); if (el) el.textContent = v; };
  if (!book || !book.ledger || !book.summary) {
    $('status').className = 'notice warning';
    $('status').innerHTML = '<span class="status-dot"></span><div><strong>No results loaded</strong><p>book.js is missing. Run engine.py first.</p></div>';
    return;
  }
  const cfg = book.config, S = book.summary, W = S.wheel, B = S.buy_hold, L = book.ledger, BL = book.blotter, D = book.decisions, ev = book.fill_evidence, prov = book.provenance;
  const name = cfg.underlying;
  const full = {AMZN:'Amazon', UUUU:'Energy Fuels', AAPL:'Apple'}[name] || name;
  const hasBA = !!prov.has_bid_ask;

  // ---------- header ----------
  text('h-name', full); text('h-tag', `${name} / WEEKLY WHEEL`);
  text('h-sample', `${sdShort(book.sample.start)} — ${sd(book.sample.end)}`);
  text('h-cash', money0(cfg.initial_cash));
  text('h-fill', hasBA ? 'Sell at closing bid' : 'Sell at closing mid');
  text('h-data', `LSEG daily ${hasBA ? 'bid/ask' : 'mid'} quotes`);
  text('r-otm', Math.round(100 * cfg.put_otm) + '%'); text('r-max', cfg.max_contracts);

  // ---------- status ----------
  const audit = prov.audit;
  const auditText = audit ? `${num(audit.candidates)} contracts requested from LSEG, ${num(audit.observed)} came back with prices, ${num(audit.no_observations)} returned no data at all (strikes that were most likely never listed), ${num(audit.request_failed)} requests failed.` : 'Source: the Assignment 1.1 UUUU cache (daily mid prices only).';
  $('status').className = 'notice' + (audit && audit.request_failed ? ' warning' : '');
  $('status').innerHTML = `<span class="status-dot"></span><div><strong>Backtest complete: ${S.weeks} weeks, ${BL.length} booked events, ${S.puts_sold} puts and ${S.calls_sold} calls sold.</strong><p>${esc(auditText)} ${S.estimated_marks ? `${S.estimated_marks} daily option mark${S.estimated_marks > 1 ? 's were' : ' was'} estimated because the contract had no closing quote that day; they are flagged in the ledger.` : 'Every daily option mark in the ledger is an observed closing quote.'}</p></div>`;

  // ---------- metrics ----------
  text('m-ret', pct(W.total_return)); text('m-bh', pct(B.total_return));
  text('m-ret-note', `${money(S.net_pnl)} on ${money0(cfg.initial_cash)}, ${W.trading_days} trading days`);
  text('m-bh-note', `${S.bh_shares} shares bought ${sdShort(book.sample.first_entry)}, ${money0(S.bh_cash_left)} left in cash`);
  text('m-sharpe', `${fin(W.sharpe_rf0) ? W.sharpe_rf0.toFixed(2) : '—'} / ${fin(B.sharpe_rf0) ? B.sharpe_rf0.toFixed(2) : '—'}`);
  text('m-dd', `${pct(W.max_drawdown)} / ${pct(B.max_drawdown)}`);
  const row = (label, m, pnl) => '<tr>' + cell(label) + cashCell(m.end) + cashCell(pnl) + cell(pct2(m.total_return)) + cell(pct(m.annualized_return)) + cell(pct(m.annualized_vol)) + cell(fin(m.sharpe_rf0) ? m.sharpe_rf0.toFixed(2) : '—') + cell(pct(m.max_drawdown)) + cell(pct(m.worst_day)) + '</tr>';
  $('comparison').tBodies[0].innerHTML = row('Wheel', W, S.net_pnl) + row(`Buy and hold ${S.bh_shares} shares`, B, B.end - cfg.initial_cash) + '<tr>' + cell('Cash, no trades') + cashCell(cfg.initial_cash) + cashCell(0) + cell('0.00%') + cell('0.0%') + cell('0.0%') + cell('—') + cell('0.0%') + cell('0.0%') + '</tr>';
  text('nav-pill', `${S.days_in_stock} of ${S.days_total} days holding shares`);

  // ---------- narrative ----------
  const cycles = book.cycles || [];
  const closed = cycles.filter(c => c.called_away), open = cycles.find(c => c.open_at_end);
  const firstClose = L[0].close, lastClose = L[L.length - 1].close, stockMove = lastClose / firstClose - 1;
  let happened = `${full} went from ${px(firstClose)} to ${px(lastClose)} over the sample (${pct(stockMove)}), with a worst drawdown of ${pct(B.max_drawdown)} for a plain holder. `;
  happened += `I sold puts in ${S.puts_sold} weeks. ${S.puts_expired} expired worthless and ${S.puts_assigned} ${S.puts_assigned === 1 ? 'was' : 'were'} assigned. `;
  if (S.calls_sold) happened += `While holding shares I sold ${S.calls_sold} covered call${S.calls_sold === 1 ? '' : 's'}; ${S.calls_expired} expired and ${S.calls_called_away} took the shares away. `;
  if (S.weeks_holding_without_call) happened += `In ${S.weeks_holding_without_call} week${S.weeks_holding_without_call === 1 ? '' : 's'} I held shares but there was no call at or above my cost worth selling, so I just sat. `;
  if (S.weeks_skipped) happened += `${S.weeks_skipped} week${S.weeks_skipped === 1 ? ' was' : 's were'} skipped for the reasons in the decision log.`;
  text('t-happened', happened.trim());
  const realized = S.realized_stock_pnl, unreal = S.unrealized_stock_pnl;
  let moneyTxt = `Premium collected: ${money(S.premium_collected)} before ${money(S.fees_paid)} of fees. `;
  if (closed.length) moneyTxt += realized === 0 ? `The shares I was assigned were bought and called away at the same strike, so the stock leg made nothing and the whole result is premium. ` : `Shares bought on assignment and later called away made ${money(realized)} on the stock legs. `;
  if (open && S.ending_shares) moneyTxt += `At the end I still hold ${S.ending_shares} shares bought at ${px(S.ending_basis)}, worth ${money(unreal)} ${unreal >= 0 ? 'more' : 'less'} than I paid, marked at the last close. `;
  if (S.open_option_liability) moneyTxt += `There is ${money(-S.open_option_liability)} of open short-option value marked against the account. `;
  moneyTxt += `Net result: ${money(S.net_pnl)}. The premium is cash I received, not profit by itself; the stock leg decides whether I keep it.`;
  text('t-money', moneyTxt);
  const beatReturn = W.total_return > B.total_return, beatSharpe = fin(W.sharpe_rf0) && fin(B.sharpe_rf0) && W.sharpe_rf0 > B.sharpe_rf0, beatDD = W.max_drawdown > B.max_drawdown;
  let verdict = `Return: the wheel ${beatReturn ? 'beat' : 'lost to'} buy and hold by ${pct(Math.abs(W.total_return - B.total_return))}. `;
  verdict += `Risk: drawdown was ${beatDD ? 'smaller' : 'larger'} (${pct(W.max_drawdown)} vs ${pct(B.max_drawdown)}) and the Sharpe ratio was ${beatSharpe ? 'higher' : 'lower'} (${fin(W.sharpe_rf0) ? W.sharpe_rf0.toFixed(2) : '—'} vs ${fin(B.sharpe_rf0) ? B.sharpe_rf0.toFixed(2) : '—'}). `;
  const score = [beatReturn, beatSharpe, beatDD].filter(Boolean).length;
  verdict += score === 3 ? 'So the thesis held on all three counts in this sample. ' : score === 0 ? 'So the thesis did not hold in this sample on any count. ' : `So the thesis held on ${score} of 3 counts. `;
  verdict += stockMove > 0.1 ? 'A strong rally is the wheel\'s worst case for relative return, because the put only earns its premium while the stock runs away, and that is part of what happened here. ' : stockMove < -0.1 ? 'A falling market is where the wheel is supposed to help, since the premium cushions the drop, but once assigned you own the stock all the way down like anyone else. ' : 'The stock ended near where it started, which is the kind of sideways market the wheel is built for. ';
  verdict += `One stock and ${S.weeks} weeks is not enough to call it a good strategy in general; it is enough to say the mechanics work and what they cost.`;
  text('t-verdict', verdict);

  // ---------- NAV chart ----------
  const dates = L.map(r => r.date);
  const assigned = L.filter(r => /assigned/.test(r.events)), called = L.filter(r => /called away/.test(r.events));
  const navTraces = [
    {x: dates, y: L.map(r => r.nav), name: 'Wheel account', mode: 'lines', line: {color: '#17644e', width: 2.2}, hovertemplate: '%{x|%b %d}<br>Wheel %{y:$,.0f}<extra></extra>'},
    {x: dates, y: L.map(r => r.bh_nav), name: `Buy and hold ${S.bh_shares} shares`, mode: 'lines', line: {color: '#ae7a35', width: 1.6, dash: 'dot'}, hovertemplate: '%{x|%b %d}<br>Hold %{y:$,.0f}<extra></extra>'},
    {x: dates, y: L.map(r => r.cash), name: 'Cash in the wheel account', mode: 'lines', line: {color: '#9ca99e', width: 1}, hovertemplate: '%{x|%b %d}<br>Cash %{y:$,.0f}<extra></extra>'},
    {x: assigned.map(r => r.date), y: assigned.map(r => r.nav), name: 'Assigned (bought shares)', mode: 'markers', marker: {symbol: 'triangle-down', size: 12, color: '#a34036'}, hovertemplate: '%{x|%b %d}: assigned<extra></extra>'},
    {x: called.map(r => r.date), y: called.map(r => r.nav), name: 'Called away (sold shares)', mode: 'markers', marker: {symbol: 'triangle-up', size: 12, color: '#4067a7'}, hovertemplate: '%{x|%b %d}: called away<extra></extra>'}
  ];
  const layout = (extra={}) => Object.assign({margin: {l: 70, r: 20, t: 10, b: 45}, paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: {family: 'Inter, system-ui, sans-serif', size: 11, color: '#5d6e67'}, legend: {orientation: 'h', y: -0.18}, hovermode: 'x unified', xaxis: {gridcolor: '#e6e9e3'}, yaxis: {gridcolor: '#e6e9e3', tickprefix: '$', tickformat: ',.0f'}}, extra);
  const plotReady = () => typeof Plotly !== 'undefined';
  const draw = () => {
    if (!plotReady()) { setTimeout(draw, 100); return; }
    Plotly.newPlot('nav-chart', navTraces, layout(), {displayModeBar: false, responsive: true});
    if (ev.scatter && ev.scatter.length) {
      const xs = ev.scatter.map(p => p[0]), ys = ev.scatter.map(p => p[1]);
      const mx = Math.max(...xs, ...ys) * 1.05;
      Plotly.newPlot('fill-chart', [
        {x: xs, y: ys, mode: 'markers', type: 'scatter', marker: {size: 5, color: '#17644e', opacity: 0.45}, name: 'Contract-day', hovertemplate: 'mid %{x:$.2f}<br>trade %{y:$.2f}<extra></extra>'},
        {x: [0, mx], y: [0, mx], mode: 'lines', line: {color: '#ae7a35', dash: 'dot', width: 1}, name: 'Trade = mid', hoverinfo: 'skip'}
      ], layout({xaxis: {title: 'Closing mid ($)', gridcolor: '#e6e9e3'}, yaxis: {title: 'Last trade of the day ($)', gridcolor: '#e6e9e3'}, hovermode: 'closest', showlegend: false}), {displayModeBar: false, responsive: true});
    } else {
      $('fill-chart').innerHTML = '<div class="chart-empty">No paired quote/trade observations in the source.</div>';
    }
  };
  draw();

  // ---------- portfolio viewer ----------
  const sel = $('pf-date');
  L.forEach((r, i) => { const o = document.createElement('option'); o.value = i; o.textContent = `${sd(r.date)}${r.events ? '  ·  ' + r.events : ''}`; sel.appendChild(o); });
  const showDay = i => {
    const r = L[i]; sel.value = i;
    text('pf-cash', money(r.cash)); text('pf-reserved', r.cash_reserved ? `${money0(r.cash_reserved)} of it is set aside to cover the short put` : 'Nothing reserved; no put open');
    text('pf-shares', num(r.shares)); text('pf-basis', r.shares ? `bought at ${px(r.basis)} on assignment, now worth ${money(r.stock_mv)}` : 'No shares held');
    const p = r.short_put, c = r.short_call;
    text('pf-put', p ? `−${p.qty} × ${px(p.strike)} put` : 'none'); text('pf-put-detail', p ? `${p.ric}, expires ${sdShort(p.expiry)}, sold at ${px(p.sold_at)}, marked ${px(p.mark)}${p.mark_status === 'estimated' ? ' (estimated)' : p.mark_status === 'settled' ? ' (settled today)' : ''}` : '');
    text('pf-call', c ? `−${c.qty} × ${px(c.strike)} call` : 'none'); text('pf-call-detail', c ? `${c.ric}, expires ${sdShort(c.expiry)}, sold at ${px(c.sold_at)}, marked ${px(c.mark)}${c.mark_status === 'estimated' ? ' (estimated)' : c.mark_status === 'settled' ? ' (settled today)' : ''}` : '');
    text('pf-nav', money(r.nav)); text('pf-nav-detail', `${pct2(r.nav / cfg.initial_cash - 1)} since the start · buy and hold would be ${money(r.bh_nav)}`);
    text('pf-close', px(r.close)); text('pf-events', r.events ? `Today: ${r.events}` : 'No account events today');
    $('pf-prev').disabled = i === 0; $('pf-next').disabled = i === L.length - 1;
  };
  sel.addEventListener('change', () => showDay(+sel.value));
  $('pf-prev').addEventListener('click', () => showDay(Math.max(0, +sel.value - 1)));
  $('pf-next').addEventListener('click', () => showDay(Math.min(L.length - 1, +sel.value + 1)));
  const firstEvent = L.findIndex(r => r.events); showDay(firstEvent >= 0 ? firstEvent : 0);

  // ---------- blotter ----------
  const weeks = [...new Set(BL.map(b => b.week).filter(Boolean))];
  weeks.forEach(w => { const o = document.createElement('option'); o.value = w; o.textContent = `Week ending ${sdShort(w)}`; $('bl-week').appendChild(o); });
  const renderBlotter = () => {
    const w = $('bl-week').value, s = $('bl-side').value;
    const rows = BL.filter(b => (!w || b.week === w) && (!s || b.side === s));
    $('blotter-table').tBodies[0].innerHTML = rows.length ? rows.map(b => '<tr>' + cell(b.id) + cell(sd(b.date)) + cell(b.instrument) + `<td><span class="side ${esc(b.side)}">${esc(b.side)}</span></td>` + cell(num(b.qty)) + cell(fin(b.bid) ? px(b.bid) : '—') + cell(fin(b.ask) ? px(b.ask) : '—') + cell(b.side === 'EXPIRE' || b.side === 'ASSIGN' ? '—' : px(b.fill)) + cell(b.fee ? money(b.fee) : '—') + cashCell(b.cash_delta) + cashCell(b.cash_after) + cell(b.note) + '</tr>').join('') : '<tr><td colspan="12" class="empty">Nothing matches that filter.</td></tr>';
    text('bl-caption', `${rows.length} of ${BL.length} events shown. Option quantities are contracts (100 shares each); stock quantities are shares. ASSIGN and EXPIRE rows move no cash themselves; the stock leg next to an assignment carries the strike × shares. Fees: ${money(cfg.fee_per_contract)} per contract per option order, nothing on expiry or assignment.`);
  };
  $('bl-week').addEventListener('change', renderBlotter); $('bl-side').addEventListener('change', renderBlotter); renderBlotter();
  $('decisions').tBodies[0].innerHTML = D.map(d => '<tr>' + cell(sd(d.date)) + `<td><span class="side ${d.status.startsWith('SOLD') ? 'SELL' : d.status === 'HOLD' ? 'EXPIRE' : 'ASSIGN'}">${esc(d.status)}</span></td>` + cell(fin(d.strike) ? px(d.strike) : '—') + cell(px(d.spot)) + cell(d.reason) + '</tr>').join('');

  // ---------- ledger ----------
  const renderLedger = () => {
    const f = $('lg-filter').value;
    const rows = L.filter(r => f === 'all' || (f === 'events' && r.events) || (f === 'estimated' && ((r.short_put && r.short_put.mark_status === 'estimated') || (r.short_call && r.short_call.mark_status === 'estimated'))));
    const pos = p => p ? `${p.qty} × ${px(p.strike)} exp ${sdShort(p.expiry)}` : '—';
    const mk = p => p ? (p.mark_status === 'settled' ? 'settled' : px(p.mark) + (p.mark_status === 'estimated' ? ' est.' : '')) : '—';
    $('ledger-table').tBodies[0].innerHTML = rows.length ? rows.map(r => '<tr>' + cell(sd(r.date)) + cell(px(r.close)) + cashCell(r.cash) + cell(r.cash_reserved ? money0(r.cash_reserved) : '—') + cell(num(r.shares)) + cell(r.shares ? px(r.basis) : '—') + cell(pos(r.short_put)) + cell(mk(r.short_put), r.short_put && r.short_put.mark_status === 'estimated' ? 'est' : '') + cell(pos(r.short_call)) + cell(mk(r.short_call), r.short_call && r.short_call.mark_status === 'estimated' ? 'est' : '') + cashCell(r.stock_mv) + cashCell(r.option_mv) + cashCell(r.nav) + cashCell(r.bh_nav) + cell(r.events) + '</tr>').join('') : '<tr><td colspan="15" class="empty">No days match.</td></tr>';
    text('lg-caption', `${rows.length} of ${L.length} trading days shown. Reserved is the cash that backs the open put (strike × contracts × 100); it is part of Cash, not extra. Option liability is the mid price of the open short options times contracts times 100, shown negative. Account value = Cash + Stock value + Option liability.`);
  };
  $('lg-filter').addEventListener('change', renderLedger); renderLedger();

  // ---------- fills ----------
  const stats = [];
  if (hasBA) {
    stats.push(['Near-the-money front-week contract-days', num(ev.near_money_front_week_rows)]);
    stats.push(['…with a two-sided closing quote', pct(ev.two_sided_share)]);
    stats.push(['Median bid-ask spread', px(ev.median_spread)]);
    stats.push(['Median spread as % of mid', pct(ev.median_rel_spread)]);
    stats.push(['…with a trade print as well', num(ev.trade_pairs)]);
    stats.push(['Trades inside the closing quote', pct(ev.trade_inside_quote_share)]);
    stats.push(['Trades at or below the bid', pct(ev.trade_at_or_below_bid_share)]);
    stats.push(['R² of trade on mid', fin(ev.r2_mid_vs_trade) ? ev.r2_mid_vs_trade.toFixed(3) : '—']);
    text('fill-text', `Most of these weekly options had a tight two-sided market at the close, and when they traded, the last trade was usually inside the quote. Selling at the bid means I assume I hit the standing bid rather than waiting at the mid; ${pct(ev.trade_at_or_below_bid_share)} of the printed trades were at or below the bid of that closing quote, so even the bid is not a guarantee, which is why the stress table below also takes 5 and 10 cents off every fill. The last trade and the closing quote are not from the same instant, so take this as a rough check rather than a guarantee.`);
  } else {
    stats.push(['Contract-days with a mid and a trade', num(ev.trade_pairs)]);
    stats.push(['R² of trade on mid', fin(ev.r2_mid_vs_trade) ? ev.r2_mid_vs_trade.toFixed(3) : '—']);
    stats.push(['Median |trade − mid|', px(ev.median_abs_gap)]);
    stats.push(['Trades below the mid', pct(ev.share_trade_below_mid)]);
    stats.push(['Contract-days with a mid but no trade', num(ev.mid_only_rows)]);
    text('fill-text', 'This source only has the closing mid and the last trade, no bid and ask. The trade sits close to the mid when there is one, but many contract-days have no trade at all, so a mid fill is optimistic here. The stress rows below take 5 and 10 cents off every sale.');
  }
  $('fill-stats').innerHTML = stats.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('');
  const sold = ev.sold_contracts || [];
  $('sold').tBodies[0].innerHTML = sold.length ? sold.map(s => '<tr>' + cell(sd(s.date)) + cell(s.ric) + cell(fin(s.bid) ? px(s.bid) : '—') + cell(fin(s.ask) ? px(s.ask) : '—') + cell(px(s.fill)) + cell(fin(s.trade_print) ? px(s.trade_print) : 'no trade that day') + cell(fin(s.trade_print) ? (s.fill - s.trade_print >= 0 ? '+' : '−') + '$' + Math.abs(s.fill - s.trade_print).toFixed(2) : '—') + '</tr>').join('') : '<tr><td colspan="7" class="empty">No options sold.</td></tr>';
  const vLabels = {base: ['Base case (this page)', 'as described above'], no_basis_floor: ['Calls at the nearest strike above spot', 'ignore my cost basis when picking the call strike; sells calls below basis'], haircut_5c: ['Fills 5¢ worse', 'every option sold for $0.05 less than the quote'], haircut_10c: ['Fills 10¢ worse', 'every option sold for $0.10 less'], put_otm_97: ['Puts 3% out of the money', 'closer put strike, more premium, more assignments'], put_otm_92: ['Puts 8% out of the money', 'further put strike, less premium, fewer assignments']};
  const vRows = Object.entries(variants).map(([k, v]) => { const w = v.wheel, lab = vLabels[k] || [k, '']; return '<tr>' + cell(lab[0]) + cashCell(w.end) + cell(pct2(w.total_return)) + cell(fin(w.sharpe_rf0) ? w.sharpe_rf0.toFixed(2) : '—') + cell(pct(w.max_drawdown)) + cell(v.puts_sold) + cell(v.puts_assigned) + cell(v.calls_sold) + cell(v.calls_called_away) + cell(v.weeks_skipped + v.weeks_holding_without_call) + cell(lab[1]) + '</tr>'; });
  $('stress').tBodies[0].innerHTML = vRows.join('') || '<tr><td colspan="11" class="empty">variants.js not loaded.</td></tr>';
  const h5 = variants.haircut_5c, h10 = variants.haircut_10c;
  text('stress-caption', h5 && h10 ? `Taking 5 cents off every fill costs ${money(W.end - h5.wheel.end)} over the sample and 10 cents costs ${money(W.end - h10.wheel.end)}. ${W.end - h10.wheel.end < Math.abs(S.net_pnl) ? 'The result does not hinge on the fill assumption.' : 'The fill assumption matters here: a dime per contract changes the sign of the result.'} I ran each rule variant once after the base case and kept whatever came out, better or worse.` : '');

  // ---------- data ----------
  text('d-pull', `${prov.provider}${prov.library ? ', ' + prov.library : ''}. Daily ${hasBA ? 'BID, ASK, MID_PRICE, TRDPRC_1 and ACVOL_UNS' : 'MID_PRICE and TRDPRC_1'} for every weekly ${name} put and call in a strike band around each week's price range, plus the stock's daily OHLC. ${prov.fetched_at ? 'Pulled ' + prov.fetched_at.slice(0, 10) + '.' : ''} wheel_fetch_codebook.py is the script that ran in CodeBook; it saves wheel_source.json with every response and a request audit.`);
  text('d-check', `The engine reconciles cash on every row: cash only changes on blotter events, and account value is recomputed from positions each day. ${audit ? `${num(audit.request_failed)} requests failed, so no week was skipped because of a data problem. Contracts that returned nothing are strikes that most likely were never listed; the request audit lists every one.` : ''} ${S.estimated_marks ? `${S.estimated_marks} estimated marks are flagged.` : 'No marks were estimated.'}`);
})();
