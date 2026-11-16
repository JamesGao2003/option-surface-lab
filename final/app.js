'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fin = v => typeof v === 'number' && Number.isFinite(v);
  const px = v => fin(v) ? '$' + v.toFixed(2) : '—';
  const pct = v => fin(v) ? (100 * v).toFixed(1) + '%' : '—';
  const cell = (v, cls='') => `<td${cls ? ` class="${cls}"` : ''}>${esc(v)}</td>`;
  const text = (id, v) => { const el = $(id); if (el) el.textContent = v; };
  const get = async (url, fallback) => { try { const r = await fetch(url, {cache: 'no-store'}); if (!r.ok) throw new Error(r.status); return url.endsWith('.json') ? await r.json() : await r.text(); } catch (e) { return fallback; } };
  const meaning = {id: 'My order id. Carries the session date, so a second run the same night cannot fill it twice.', for: 'The session this order belongs to, YYYY-MM-DD. A late run must not fill it on the wrong day.', order_type: 'lmt = limit order; needs lmt_prc. mkt would fill at the open.', action: 'SHT = sell to open. Writing a put or a covered call is SHT.', qty: 'Contracts. Always a positive integer.', underlying: "Interactive Brokers' conid for Apple, copied from price_history.json, not a ticker.", contract: 'put, call or underlying.', expiry: 'A listed expiry date. Friday of the session week, or next Friday if that is under three days away.', strike: 'pct:-N = the open times (1 − N/100), snapped to the nearest listed strike, ties further out of the money. A bare number is that strike.', ref: 'Which print the strike token is measured from. open = tomorrow\'s open.', lmt_prc: 'mid = midpoint of the resolved contract\'s bid and ask at the open.'};

  (async () => {
    const [orders, log, history, hist, yaml] = await Promise.all([
      get('../open_orders.json', null), get('run_log.json', null), get('order_history.json', []), get('../price_history.json', null), get('nightly-orders.yml', '')
    ]);
    if (!log) { $('status').className = 'notice warning'; $('status').innerHTML = '<span class="status-dot"></span><div><strong>No run log yet</strong><p>The Action has not run, or run_log.json is missing.</p></div>'; return; }
    const ok = Array.isArray(orders);
    text('h-last', log.run_at_ny + ' NY');
    $('status').className = 'notice' + (ok ? '' : ' warning');
    $('status').innerHTML = `<span class="status-dot"></span><div><strong>Last run ${esc(log.run_at_ny)} New York: ${esc(log.decision)}.</strong><p>${esc(log.reason || '')} ${ok ? `open_orders.json holds ${orders.length} order${orders.length === 1 ? '' : 's'} for ${esc(log.session)}.` : 'open_orders.json could not be read.'} ${(log.notes || []).map(esc).join(' ')}</p></div>`;
    text('m-decision', log.decision || '—'); text('m-reason', log.reason || '');
    text('m-session', log.session || '—'); text('m-expiry', log.expiry ? 'option expiry ' + log.expiry : '');
    text('m-close', px(log.last_close)); text('m-bar', log.last_bar ? `bar of ${log.last_bar} · ${log.bars_used} bars on file` : '');
    text('m-sigma', pct(log.weekly_sigma)); text('m-sigma-note', fin(log.daily_sigma) ? `daily ${pct(log.daily_sigma)} over ${log.config?.sigma_window} sessions, × √5` : '');
    $('order-json').textContent = ok ? JSON.stringify(orders, null, 2) : 'unreadable';
    text('order-pill', ok ? `${orders.length} order${orders.length === 1 ? '' : 's'}` : 'error');
    const rows = [];
    (ok ? orders : []).forEach((o, i) => { Object.entries(o).forEach(([k, v]) => rows.push('<tr>' + cell((orders.length > 1 ? `#${i + 1} ` : '') + k) + cell(typeof v === 'string' ? v : JSON.stringify(v)) + cell(meaning[k] || '') + '</tr>')); });
    $('order-table').tBodies[0].innerHTML = rows.join('') || '<tr><td colspan="3" class="empty">No order tonight. See the decision above.</td></tr>';
    const inputs = [['Price source', log.price_source], ['Last bar', log.last_bar], ['Last close', px(log.last_close)], ['Bars used', log.bars_used], ['Daily sigma (20 sessions)', pct(log.daily_sigma)], ['Weekly sigma', pct(log.weekly_sigma)], ['10-session return', pct(log['ret_10d'])], ['Book source', log.book?.source], ['Cash', fin(log.book?.cash) ? '$' + log.book.cash.toLocaleString() : '—'], ['Shares', log.book?.shares], ['Basis', log.book?.basis ?? '—'], ['Open short puts / calls', `${log.book?.short_puts ?? 0} / ${log.book?.short_calls ?? 0}`], ['Fills on file', log.fills_seen], ['Put distance rule', `${log.config?.put_sigma_mult} × weekly sigma, clamped ${log.config?.put_pct_floor}% to ${log.config?.put_pct_cap}%`], ['Crash filter', `skip if ${log.config?.crash_lookback}-session return ≤ ${pct(log.config?.crash_threshold)}`]];
    $('inputs').tBodies[0].innerHTML = inputs.map(([k, v]) => '<tr>' + cell(k) + cell(v ?? '—') + '</tr>').join('');
    $('wf-yaml').textContent = yaml || 'nightly-orders.yml not found';
    text('wf-pill', 'cron 0 3 * * * (UTC)');
    // history
    const H = (history || []).slice().reverse();
    $('hist').tBodies[0].innerHTML = H.length ? H.map(h => { const o = (h.orders || [])[0] || {}; return '<tr>' + cell(h.run_at_ny) + `<td><span class="side ${o.id ? 'SELL' : 'EXPIRE'}">${esc(h.decision)}</span></td>` + cell(o.id || '—') + cell(o.for || '—') + cell(o.contract || '—') + cell(o.expiry || '—') + cell(o.strike ?? '—') + cell(o.qty ?? '—') + cell(px(h.last_close)) + cell(pct(h.weekly_sigma)) + cell(h.reason || '') + '</tr>'; }).join('') : '<tr><td colspan="11" class="empty">No runs yet.</td></tr>';
    text('hist-caption', `${H.length} run${H.length === 1 ? '' : 's'} recorded. Manual runs from the Actions tab show up here too.`);
    // chart
    const entry = hist && hist[String(log.config?.conid)] ? hist[String(log.config.conid)] : null;
    const draw = () => {
      if (typeof Plotly === 'undefined') { setTimeout(draw, 100); return; }
      if (!entry) { $('px-chart').innerHTML = '<div class="chart-empty">price_history.json not available.</div>'; return; }
      const dates = Object.keys(entry.price_history).sort(); const closes = dates.map(d => entry.price_history[d].close);
      const w = log.config?.sigma_window || 20, mult = log.config?.put_sigma_mult || 1.3, lo = log.config?.put_pct_floor || 3, hi = log.config?.put_pct_cap || 10;
      const band = closes.map((c, i) => { if (i < w) return null; const r = []; for (let k = i - w + 1; k <= i; k++) r.push(Math.log(closes[k] / closes[k - 1])); const m = r.reduce((a, b) => a + b, 0) / r.length; const sd = Math.sqrt(r.reduce((a, b) => a + (b - m) ** 2, 0) / r.length) * Math.sqrt(5); let p = mult * sd * 100; p = Math.min(hi, Math.max(lo, Math.round(p))); return c * (1 - p / 100); });
      Plotly.newPlot('px-chart', [
        {x: dates, y: closes, mode: 'lines', name: 'AAPL close (server bars)', line: {color: '#17644e', width: 2}, hovertemplate: '%{x|%b %d}<br>close %{y:$.2f}<extra></extra>'},
        {x: dates, y: band, mode: 'lines', name: 'Put strike the rule would write', line: {color: '#ae7a35', width: 1.5, dash: 'dot'}, hovertemplate: '%{x|%b %d}<br>put band %{y:$.2f}<extra></extra>'}
      ], {margin: {l: 60, r: 20, t: 10, b: 45}, paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: {family: 'Inter, system-ui, sans-serif', size: 11, color: '#5d6e67'}, legend: {orientation: 'h', y: -0.18}, hovermode: 'x unified', xaxis: {gridcolor: '#e6e9e3'}, yaxis: {gridcolor: '#e6e9e3', tickprefix: '$'}}, {displayModeBar: false, responsive: true});
    };
    draw();
  })();
})();
