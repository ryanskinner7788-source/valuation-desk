// ============================================================================
// Valuation Desk — frontend
// Fetches /api/analyze/{ticker} and renders every panel. No build step, no
// framework — plain DOM + Chart.js, so it stays fast to load on mobile data.
// ============================================================================

const els = {
  form: document.getElementById('cmd-form'),
  input: document.getElementById('ticker-input'),
  peersToggle: document.getElementById('peers-toggle'),
  peersRow: document.getElementById('peers-row'),
  peersInput: document.getElementById('peers-input'),
  empty: document.getElementById('empty-state'),
  loading: document.getElementById('loading-state'),
  loadingMsg: document.getElementById('loading-msg'),
  error: document.getElementById('error-state'),
  errorMsg: document.getElementById('error-msg'),
  errorRetry: document.getElementById('error-retry'),
  results: document.getElementById('results'),
  updatedLine: document.getElementById('updated-line'),
};

let charts = { summary: null, price: null };
let lastTicker = null;

// ---------------------------------------------------------------- formatting

function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function fmtCurrency(value, currency) {
  if (value == null || isNaN(value)) return '—';
  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency', currency: currency || 'USD',
      maximumFractionDigits: 2, minimumFractionDigits: 2,
    }).format(value);
  } catch (e) {
    return '$' + Number(value).toFixed(2);
  }
}

function fmtCompact(value) {
  if (value == null || isNaN(value)) return '—';
  const sign = value < 0 ? '-' : '';
  const abs = Math.abs(value);
  if (abs >= 1e12) return sign + (abs / 1e12).toFixed(2) + 'T';
  if (abs >= 1e9) return sign + (abs / 1e9).toFixed(2) + 'B';
  if (abs >= 1e6) return sign + (abs / 1e6).toFixed(2) + 'M';
  if (abs >= 1e3) return sign + (abs / 1e3).toFixed(1) + 'K';
  return sign + abs.toFixed(2);
}

function fmtPctAlready(value, decimals) {
  if (value == null || isNaN(value)) return '—';
  decimals = decimals == null ? 2 : decimals;
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(decimals)}%`;
}

function fmtPctFraction(value, decimals) {
  if (value == null || isNaN(value)) return '—';
  return fmtPctAlready(value * 100, decimals == null ? 1 : decimals);
}

function fmtNum(value, decimals) {
  if (value == null || isNaN(value)) return '—';
  return Number(value).toFixed(decimals == null ? 2 : decimals);
}

function timeAgo(ts) {
  if (!ts) return '';
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.round(diff / 60) + 'm ago';
  if (diff < 86400) return Math.round(diff / 3600) + 'h ago';
  return Math.round(diff / 86400) + 'd ago';
}

function upDownClass(value) {
  if (value == null) return '';
  return value >= 0 ? 'up' : 'down';
}

// ---------------------------------------------------------------- UI states

function showState(name) {
  els.empty.classList.toggle('hidden', name !== 'empty');
  els.loading.classList.toggle('hidden', name !== 'loading');
  els.error.classList.toggle('hidden', name !== 'error');
  els.results.classList.toggle('hidden', name !== 'results');
}

const LOADING_MESSAGES = [
  'Fetching {t}…', 'Pulling financial statements…', 'Running the DCF…', 'Almost there…'
];

function cycleLoadingMessages(ticker) {
  let i = 0;
  els.loadingMsg.textContent = LOADING_MESSAGES[0].replace('{t}', ticker);
  return setInterval(() => {
    i = (i + 1) % LOADING_MESSAGES.length;
    els.loadingMsg.textContent = LOADING_MESSAGES[i].replace('{t}', ticker);
  }, 3500);
}

// ---------------------------------------------------------------- panel: snapshot

function renderSnapshotPanel(s) {
  const change = s.change;
  const changePct = s.change_pct;
  const cls = upDownClass(change);
  const arrow = change == null ? '' : (change >= 0 ? '▲' : '▼');
  return `
  <div class="panel">
    <div class="panel-eyebrow"><span class="panel-code">DES</span><span class="panel-title">Snapshot</span></div>
    <div class="snap-head">
      <div>
        <div class="snap-name">${escapeHtml(s.name || s.symbol)}</div>
        <div class="snap-sub">${escapeHtml(s.symbol)} · ${escapeHtml(s.exchange || '')} · ${escapeHtml(s.sector || 'Sector n/a')}</div>
      </div>
      <div class="snap-price-block">
        <div class="snap-price">${fmtCurrency(s.current_price, s.currency)}</div>
        <div class="snap-change ${cls}">${arrow} ${fmtCurrency(Math.abs(change || 0), s.currency)} (${fmtPctAlready(changePct)})</div>
      </div>
    </div>
    <div class="snap-meta">
      <div class="meta-item"><span class="meta-label">MKT CAP</span><span class="meta-value">${fmtCompact(s.market_cap)}</span></div>
      <div class="meta-item"><span class="meta-label">BETA</span><span class="meta-value">${fmtNum(s.beta)}</span></div>
      <div class="meta-item"><span class="meta-label">TRAIL P/E</span><span class="meta-value">${fmtNum(s.trailing_pe)}</span></div>
      <div class="meta-item"><span class="meta-label">FWD P/E</span><span class="meta-value">${fmtNum(s.forward_pe)}</span></div>
      <div class="meta-item"><span class="meta-label">DIV YIELD</span><span class="meta-value">${s.dividend_yield != null ? fmtPctFraction(s.dividend_yield) : '—'}</span></div>
    </div>
  </div>`;
}

// ---------------------------------------------------------------- panel: valuation summary chart

function buildSummaryCategories(vs) {
  const cats = [];
  if (vs.current_price != null) cats.push({ label: 'Current', value: vs.current_price, color: '#c7ccd6' });
  if (vs.dcf_fair_value != null) cats.push({ label: 'DCF', value: vs.dcf_fair_value, color: '#e3a857' });
  if (vs.ddm_fair_value != null) cats.push({ label: 'DDM', value: vs.ddm_fair_value, color: '#5ec8c2' });
  if (vs.analyst_low_target != null) cats.push({ label: 'Analyst Low', value: vs.analyst_low_target, color: '#9b8afb99' });
  if (vs.analyst_mean_target != null) cats.push({ label: 'Analyst Mean', value: vs.analyst_mean_target, color: '#9b8afb' });
  if (vs.analyst_high_target != null) cats.push({ label: 'Analyst High', value: vs.analyst_high_target, color: '#9b8afb99' });
  return cats;
}

function renderSummaryPanel(vs, currency) {
  const cats = buildSummaryCategories(vs);
  if (cats.length < 2) return '';
  return `
  <div class="panel">
    <div class="panel-eyebrow"><span class="panel-code">CMP</span><span class="panel-title">Where the price sits</span></div>
    <div class="chart-wrap"><canvas id="chart-summary"></canvas></div>
  </div>`;
}

function drawSummaryChart(vs, currency) {
  const canvas = document.getElementById('chart-summary');
  if (!canvas) return;
  const cats = buildSummaryCategories(vs);
  if (charts.summary) charts.summary.destroy();
  charts.summary = new Chart(canvas, {
    type: 'bar',
    data: {
      labels: cats.map(c => c.label),
      datasets: [{
        data: cats.map(c => c.value),
        backgroundColor: cats.map(c => c.color),
        borderRadius: 6,
        maxBarThickness: 42,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: { label: (ctx) => fmtCurrency(ctx.raw, currency) },
        },
      },
      scales: {
        x: { ticks: { color: '#8a93a6', font: { family: 'IBM Plex Mono', size: 10 } }, grid: { display: false } },
        y: { ticks: { color: '#8a93a6', font: { family: 'IBM Plex Mono', size: 10 }, callback: (v) => fmtCompact(v) },
             grid: { color: '#232b3a' } },
      },
    },
  });
}

// ---------------------------------------------------------------- panel: analyst targets

function renderTargetsPanel(t, currentPrice, currency) {
  if (!t.available) {
    return `
    <div class="panel">
      <div class="panel-eyebrow"><span class="panel-code">ANR</span><span class="panel-title">Analyst Targets</span></div>
      <p class="unavailable">No analyst coverage found for this ticker.</p>
    </div>`;
  }
  const upside = (t.mean != null && currentPrice) ? (t.mean - currentPrice) / currentPrice : null;
  let rangeHtml = '';
  if (t.low != null && t.high != null && t.high > t.low) {
    const clamp = (v) => Math.max(0, Math.min(100, v));
    const pct = (v) => clamp(((v - t.low) / (t.high - t.low)) * 100);
    const curPct = currentPrice != null ? pct(currentPrice) : null;
    const meanPct = t.mean != null ? pct(t.mean) : null;
    rangeHtml = `
    <div class="target-range">
      <div class="target-track">
        <div class="target-fill" style="width:100%"></div>
        ${curPct != null ? `<div class="target-marker" style="left:${curPct}%;background:#e7eaf0" title="Current"></div>` : ''}
        ${meanPct != null ? `<div class="target-marker" style="left:${meanPct}%;background:#e3a857" title="Mean target"></div>` : ''}
      </div>
      <div class="target-labels"><span>${fmtCurrency(t.low, currency)}</span><span>${fmtCurrency(t.high, currency)}</span></div>
    </div>`;
  }
  return `
  <div class="panel">
    <div class="panel-eyebrow"><span class="panel-code">ANR</span><span class="panel-title">Analyst Targets</span></div>
    <div class="fv-row">
      <span class="fv-label">MEAN TARGET</span>
      <span class="fv-value">${fmtCurrency(t.mean, currency)}</span>
    </div>
    ${upside != null ? `<div class="fv-delta ${upDownClass(upside)}">${fmtPctFraction(upside)} to mean</div>` : ''}
    ${rangeHtml}
    <table class="data-table" style="margin-top:12px">
      <tr><td>Median target</td><td>${fmtCurrency(t.median, currency)}</td></tr>
      <tr><td>Analyst count</td><td>${t.num_analysts != null ? t.num_analysts : '—'}</td></tr>
      <tr><td>Consensus</td><td>${t.recommendation ? escapeHtml(t.recommendation).toUpperCase() : '—'}</td></tr>
    </table>
  </div>`;
}

// ---------------------------------------------------------------- panel: DCF

function renderDcfPanel(dcf, currentPrice, currency, caveat) {
  if (!dcf.available) {
    return `
    <div class="panel">
      <div class="panel-eyebrow"><span class="panel-code">DCF</span><span class="panel-title">Discounted Cash Flow</span></div>
      <p class="unavailable">${escapeHtml(dcf.reason || 'Not enough data to build a DCF for this ticker.')}</p>
    </div>`;
  }
  const upside = currentPrice ? (dcf.fair_value_per_share - currentPrice) / currentPrice : null;
  return `
  <div class="panel">
    <div class="panel-eyebrow"><span class="panel-code">DCF</span><span class="panel-title">Discounted Cash Flow</span></div>
    ${caveat ? `<p class="caveat">${escapeHtml(caveat)}</p>` : ''}
    <div class="fv-row">
      <span class="fv-label">FAIR VALUE / SHARE</span>
      <span class="fv-value">${fmtCurrency(dcf.fair_value_per_share, currency)}</span>
    </div>
    ${upside != null ? `<div class="fv-delta ${upDownClass(upside)}">${fmtPctFraction(upside)} vs current price</div>` : ''}
    ${dcf.gap_note ? `<p class="caveat">${escapeHtml(dcf.gap_note)}</p>` : ''}
    <details class="assumptions">
      <summary>Assumptions</summary>
      <table class="data-table">
        <tr><td>Discount rate (WACC)</td><td>${fmtPctFraction(dcf.discount_rate)}</td></tr>
        <tr><td>Year-1 FCF growth</td><td>${fmtPctFraction(dcf.growth_year1)}</td></tr>
        <tr><td>Terminal growth</td><td>${fmtPctFraction(dcf.terminal_growth)}</td></tr>
        <tr><td>Enterprise value</td><td>${fmtCompact(dcf.enterprise_value)}</td></tr>
        <tr><td>Equity value</td><td>${fmtCompact(dcf.equity_value)}</td></tr>
      </table>
    </details>
  </div>`;
}

// ---------------------------------------------------------------- panel: DDM

function renderDdmPanel(ddm, currentPrice, currency, caveat) {
  if (!ddm.available) {
    return `
    <div class="panel">
      <div class="panel-eyebrow"><span class="panel-code">DDM</span><span class="panel-title">Dividend Discount Model</span></div>
      <p class="unavailable">${escapeHtml(ddm.reason || 'Dividend discount model not applicable.')}</p>
    </div>`;
  }
  const upside = currentPrice ? (ddm.fair_value_per_share - currentPrice) / currentPrice : null;
  return `
  <div class="panel">
    <div class="panel-eyebrow"><span class="panel-code">DDM</span><span class="panel-title">Dividend Discount Model</span></div>
    ${caveat ? `<p class="caveat">${escapeHtml(caveat)}</p>` : ''}
    <div class="fv-row">
      <span class="fv-label">FAIR VALUE / SHARE</span>
      <span class="fv-value">${fmtCurrency(ddm.fair_value_per_share, currency)}</span>
    </div>
    ${upside != null ? `<div class="fv-delta ${upDownClass(upside)}">${fmtPctFraction(upside)} vs current price</div>` : ''}
    ${ddm.gap_note ? `<p class="caveat">${escapeHtml(ddm.gap_note)}</p>` : ''}
    <details class="assumptions">
      <summary>Assumptions</summary>
      <table class="data-table">
        <tr><td>Dividend growth</td><td>${fmtPctFraction(ddm.dividend_growth)}</td></tr>
        <tr><td>Required return</td><td>${fmtPctFraction(ddm.required_return)}</td></tr>
      </table>
    </details>
  </div>`;
}

// ---------------------------------------------------------------- panel: relative valuation

function renderRelValPanel(rv, currency) {
  const m = rv.multiples || {};
  let rangeHtml = '';
  if (rv.fifty_two_week_low != null && rv.fifty_two_week_high != null && rv.fifty_two_week_high > rv.fifty_two_week_low) {
    const clamp = (v) => Math.max(0, Math.min(100, v));
    const pct = clamp(((rv.current_price - rv.fifty_two_week_low) / (rv.fifty_two_week_high - rv.fifty_two_week_low)) * 100);
    rangeHtml = `
    <div class="range-bar">
      <div class="range-dot" style="left:${pct}%"></div>
    </div>
    <div class="range-labels"><span>${fmtCurrency(rv.fifty_two_week_low, currency)}</span><span>52-week range</span><span>${fmtCurrency(rv.fifty_two_week_high, currency)}</span></div>`;
  }
  let peerHtml = '';
  if (rv.peers && rv.peers.length) {
    peerHtml = `
    <div class="peer-table-wrap">
      <table class="peer-table">
        <thead><tr><th>Ticker</th><th>P/E</th><th>Fwd P/E</th><th>EV/EBITDA</th><th>P/S</th></tr></thead>
        <tbody>
          <tr class="self"><td>${escapeHtml(rv.self_symbol || '')}</td><td>${fmtNum(m.trailing_pe)}</td><td>${fmtNum(m.forward_pe)}</td><td>${fmtNum(m.ev_to_ebitda)}</td><td>${fmtNum(m.price_to_sales)}</td></tr>
          ${rv.peers.map(p => `<tr><td>${escapeHtml(p.symbol)}</td><td>${fmtNum(p.trailing_pe)}</td><td>${fmtNum(p.forward_pe)}</td><td>${fmtNum(p.ev_to_ebitda)}</td><td>${fmtNum(p.price_to_sales)}</td></tr>`).join('')}
        </tbody>
      </table>
    </div>`;
  }
  return `
  <div class="panel">
    <div class="panel-eyebrow"><span class="panel-code">RV</span><span class="panel-title">Relative Valuation</span></div>
    <table class="data-table">
      <tr><td>Trailing P/E</td><td>${fmtNum(m.trailing_pe)}</td></tr>
      <tr><td>Forward P/E</td><td>${fmtNum(m.forward_pe)}</td></tr>
      <tr><td>EV / EBITDA</td><td>${fmtNum(m.ev_to_ebitda)}</td></tr>
      <tr><td>Price / Sales</td><td>${fmtNum(m.price_to_sales)}</td></tr>
      <tr><td>Price / Book</td><td>${fmtNum(m.price_to_book)}</td></tr>
      <tr><td>PEG ratio</td><td>${fmtNum(m.peg_ratio)}</td></tr>
    </table>
    ${rangeHtml}
    ${peerHtml}
  </div>`;
}

// ---------------------------------------------------------------- panel: price chart

function renderPriceChartPanel(points) {
  if (!points || points.length < 5) {
    return `
    <div class="panel">
      <div class="panel-eyebrow"><span class="panel-code">GP</span><span class="panel-title">Price Chart</span></div>
      <p class="unavailable">Not enough price history to chart.</p>
    </div>`;
  }
  return `
  <div class="panel">
    <div class="panel-eyebrow"><span class="panel-code">GP</span><span class="panel-title">Price Chart · 1Y</span></div>
    <div class="chart-wrap"><canvas id="chart-price"></canvas></div>
    <div class="chart-legend">
      <span><span class="legend-dot" style="background:#5ec8c2"></span>Close</span>
      <span><span class="legend-dot" style="background:#e3a857"></span>SMA 50</span>
      <span><span class="legend-dot" style="background:#8a93a6"></span>SMA 200</span>
    </div>
  </div>`;
}

function drawPriceChart(points) {
  const canvas = document.getElementById('chart-price');
  if (!canvas || !points || points.length < 5) return;
  if (charts.price) charts.price.destroy();
  const step = Math.max(1, Math.floor(points.length / 6));
  charts.price = new Chart(canvas, {
    type: 'line',
    data: {
      labels: points.map(p => p.date),
      datasets: [
        { label: 'Close', data: points.map(p => p.close), borderColor: '#5ec8c2', borderWidth: 2, pointRadius: 0, tension: 0.15 },
        { label: 'SMA 50', data: points.map(p => p.sma50), borderColor: '#e3a857', borderWidth: 1.5, pointRadius: 0, tension: 0.15 },
        { label: 'SMA 200', data: points.map(p => p.sma200), borderColor: '#8a93a6', borderWidth: 1.5, pointRadius: 0, tension: 0.15 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { intersect: false, mode: 'index' },
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: '#8a93a6', maxTicksLimit: 6, font: { family: 'IBM Plex Mono', size: 10 } }, grid: { display: false } },
        y: { ticks: { color: '#8a93a6', font: { family: 'IBM Plex Mono', size: 10 } }, grid: { color: '#232b3a' } },
      },
    },
  });
}

// ---------------------------------------------------------------- panel: news

function renderNewsPanel(news) {
  if (!news || !news.length) {
    return `
    <div class="panel">
      <div class="panel-eyebrow"><span class="panel-code">CN</span><span class="panel-title">Company News</span></div>
      <p class="unavailable">No recent news found.</p>
    </div>`;
  }
  return `
  <div class="panel">
    <div class="panel-eyebrow"><span class="panel-code">CN</span><span class="panel-title">Company News</span></div>
    ${news.map(n => `
      <a class="news-item" href="${escapeHtml(n.link)}" target="_blank" rel="noopener">
        <div class="news-title">${escapeHtml(n.title)}</div>
        <div class="news-meta">${escapeHtml(n.publisher)} · ${timeAgo(n.published_at)}</div>
      </a>`).join('')}
  </div>`;
}

// ---------------------------------------------------------------- orchestration

async function runAnalysis(ticker, peers) {
  ticker = (ticker || '').trim().toUpperCase();
  if (!ticker) return;
  lastTicker = ticker;
  showState('loading');
  const msgTimer = cycleLoadingMessages(ticker);

  const url = new URL('/api/analyze/' + encodeURIComponent(ticker), window.location.origin);
  if (peers) url.searchParams.set('peers', peers);

  let resp;
  try {
    resp = await fetch(url.toString());
  } catch (err) {
    clearInterval(msgTimer);
    showState('error');
    els.errorMsg.textContent = 'Could not reach the server. Check your connection and try again.';
    return;
  }
  clearInterval(msgTimer);

  if (!resp.ok) {
    let detail = 'Something went wrong fetching that ticker.';
    try { const body = await resp.json(); if (body && body.detail) detail = body.detail; } catch (e) {}
    showState('error');
    els.errorMsg.textContent = detail;
    return;
  }

  let data;
  try {
    data = await resp.json();
  } catch (err) {
    showState('error');
    els.errorMsg.textContent = 'The server answered but sent something the browser could not read (parse error: ' + err.message + ').';
    console.error('Response parsing failed:', err);
    return;
  }

  try {
    renderResults(data);
  } catch (err) {
    showState('error');
    els.errorMsg.textContent = 'Got the data back, but hit a bug displaying it: ' + err.message;
    console.error('renderResults failed:', err);
    return;
  }

  showState('results');
  const d = new Date(data.generated_at);
  els.updatedLine.textContent = 'Updated ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function renderResults(data) {
  const currency = data.snapshot.currency || 'USD';
  data.relative_valuation.self_symbol = data.symbol;

  const html = [
    renderSnapshotPanel(data.snapshot),
    renderSummaryPanel(data.valuation_summary, currency),
    renderTargetsPanel(data.analyst_targets, data.snapshot.current_price, currency),
    renderDcfPanel(data.dcf, data.snapshot.current_price, currency, data.snapshot.dcf_caveat),
    renderDdmPanel(data.ddm, data.snapshot.current_price, currency, data.snapshot.ddm_caveat),
    renderRelValPanel(data.relative_valuation, currency),
    renderPriceChartPanel(data.price_chart),
    renderNewsPanel(data.news),
  ].join('');

  els.results.innerHTML = html;
  drawSummaryChart(data.valuation_summary, currency);
  drawPriceChart(data.price_chart);
}

// ---------------------------------------------------------------- wiring

els.form.addEventListener('submit', (e) => {
  e.preventDefault();
  runAnalysis(els.input.value, els.peersInput.value);
  els.input.blur();
});

els.peersToggle.addEventListener('click', () => {
  const willShow = els.peersRow.classList.contains('hidden');
  els.peersRow.classList.toggle('hidden');
  els.peersToggle.setAttribute('aria-expanded', String(willShow));
  els.peersToggle.textContent = willShow ? '− compare peers' : '+ compare peers';
  if (willShow) els.peersInput.focus();
});

els.errorRetry.addEventListener('click', () => {
  if (lastTicker) runAnalysis(lastTicker, els.peersInput.value);
});

// Support /?ticker=AAPL for future Shortcuts / bookmark integration
window.addEventListener('DOMContentLoaded', () => {
  const params = new URLSearchParams(window.location.search);
  const t = params.get('ticker');
  if (t) {
    els.input.value = t.toUpperCase();
    runAnalysis(t, params.get('peers'));
  }
});
