/* GateWay shared insights renderer.
 *
 * One renderer for the command board, the kitchen screen and the driver hub, so
 * "what does my data say" looks and behaves the same everywhere.
 *
 * The rule this file enforces visually: a number without enough evidence behind
 * it NEVER gets drawn like a fact. The server marks each figure
 * ok / rough / insufficient, and this renders those three states differently —
 * confident, hedged, or an honest "not yet, here's what's missing". A greyed
 * "needs 12 more orders" is more useful than a bold number that's wrong.
 */
(function () {
  if (window.gwInsights) return;

  function money(c) { return '$' + (Math.max(0, c || 0) / 100).toFixed(2); }
  function money0(c) { return '$' + Math.round(Math.max(0, c || 0) / 100).toLocaleString(); }
  function esc(x) { var d = document.createElement('div'); d.textContent = x == null ? '' : x; return d.innerHTML; }
  function hour12(h) { return ((h % 12) || 12) + (h < 12 ? 'am' : 'pm'); }

  var CSS = [
    '.gwi-sec{font-family:"IBM Plex Mono",monospace;font-size:.6rem;letter-spacing:.11em;',
    'text-transform:uppercase;color:#8b93a7;margin:18px 0 9px}',
    '.gwi-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(96px,1fr));gap:9px}',
    '.gwi-kpi{background:var(--gwi-card,#fff);border:1.5px solid var(--gwi-line,#e2e7f1);',
    'border-radius:13px;padding:12px 13px}',
    '.gwi-kpi b{display:block;font-size:1.3rem;font-weight:900;line-height:1.1;color:var(--gwi-ink,#16337a)}',
    '.gwi-kpi span{display:block;font-size:.63rem;text-transform:uppercase;letter-spacing:.05em;',
    'color:#8b93a7;font-weight:700;margin-top:3px}',
    '.gwi-thin{font-size:.78rem;color:#9199a8;line-height:1.5;background:var(--gwi-soft,#f5f7fb);',
    'border:1px dashed var(--gwi-line,#dfe4ee);border-radius:11px;padding:10px 13px}',
    '.gwi-bars{display:flex;align-items:flex-end;gap:3px;height:74px;margin-top:4px}',
    '.gwi-bar{flex:1;min-width:2px;background:linear-gradient(180deg,#2f6fe0,#16337a);',
    'border-radius:3px 3px 0 0;position:relative}',
    '.gwi-bar.zero{background:var(--gwi-line,#e2e7f1)}',
    '.gwi-axis{display:flex;justify-content:space-between;font-size:.6rem;color:#9199a8;margin-top:5px}',
    '.gwi-row{display:flex;justify-content:space-between;gap:10px;padding:7px 0;',
    'border-bottom:1px solid var(--gwi-line,#eef0f5);font-size:.85rem}',
    '.gwi-row:last-child{border-bottom:none}',
    '.gwi-trend{display:inline-block;font-weight:800;font-size:.78rem;padding:3px 9px;border-radius:20px}',
    '.gwi-up{background:#e6f5ec;color:#1a7f4b}.gwi-down{background:#fdecec;color:#a83c3c}',
    '.gwi-flat{background:#eef2fc;color:#16337a}',
    '.gwi-proj{background:var(--gwi-soft,#f5f7fb);border:1.5px solid var(--gwi-line,#e2e7f1);',
    'border-radius:13px;padding:13px 15px}',
    '.gwi-proj b{font-size:1.15rem;color:var(--gwi-ink,#16337a)}',
    '.gwi-note{font-size:.7rem;color:#9199a8;margin-top:5px;line-height:1.45}'
  ].join('');

  function ensureCss() {
    if (document.getElementById('gwi-css')) return;
    var s = document.createElement('style');
    s.id = 'gwi-css';
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function thin(msg) { return '<div class="gwi-thin">' + msg + '</div>'; }

  function sparkline(series) {
    if (!series || !series.length) return '';
    var max = Math.max.apply(null, series.map(function (d) { return d.orders; }));
    if (max <= 0) return thin('No orders in this window yet.');
    var bars = series.map(function (d) {
      var h = d.orders ? Math.max(6, Math.round(d.orders / max * 74)) : 3;
      return '<div class="gwi-bar' + (d.orders ? '' : ' zero') + '" style="height:' + h +
             'px" title="' + esc(d.date) + ': ' + d.orders + ' orders"></div>';
    }).join('');
    return '<div class="gwi-bars">' + bars + '</div>' +
           '<div class="gwi-axis"><span>' + esc(series[0].date.slice(5)) +
           '</span><span>' + esc(series[series.length - 1].date.slice(5)) + '</span></div>';
  }

  function trendBlock(t) {
    if (!t || t.confidence !== 'ok') {
      return thin('Trend needs more history — ' +
                  esc((t && (t.reason || '')) || 'keep going') +
                  (t && t.have != null ? ' (have ' + t.have + ')' : '') + '.');
    }
    var cls = t.direction === 'up' ? 'gwi-up' : t.direction === 'down' ? 'gwi-down' : 'gwi-flat';
    var arrow = t.direction === 'up' ? '▲' : t.direction === 'down' ? '▼' : '▬';
    var pct = t.orders_change_pct;
    return '<div class="gwi-row"><span>Orders this week</span>' +
           '<span><b>' + t.orders_this_week + '</b> vs ' + t.orders_last_week +
           ' <span class="gwi-trend ' + cls + '">' + arrow +
           (pct == null ? '' : ' ' + Math.abs(pct) + '%') + '</span></span></div>' +
           '<div class="gwi-row"><span>Revenue this week</span><span><b>' +
           money0(t.revenue_this_week_cents) + '</b> vs ' + money0(t.revenue_last_week_cents) +
           '</span></div>';
  }

  function projectionBlock(p) {
    if (!p || p.confidence === 'insufficient') {
      return thin('Not enough steady history to project yet — ' +
                  esc((p && p.reason) || '') +
                  (p && p.have != null ? ' (have ' + p.have + ')' : '') + '.');
    }
    var rough = p.confidence === 'rough';
    return '<div class="gwi-proj"><b>~' + p.projected_orders + ' orders</b> and <b>' +
           money0(p.projected_revenue_cents) + '</b> over the next ' + p.horizon_days +
           ' days' +
           '<div class="gwi-note">Based on your last ' + p.basis_days + ' days (about ' +
           p.per_day_orders + ' a day). ' +
           (rough ? 'Your day-to-day swings a lot right now, so treat this as a rough guide, not a promise.'
                  : 'Your days have been steady, so this should track closely.') +
           '</div></div>';
  }

  function render(el, d, opts) {
    ensureCss();
    opts = opts || {};
    var s = d.summary || {};
    var out = '';

    out += '<div class="gwi-kpis">';
    out += '<div class="gwi-kpi"><b>' + (s.orders_completed || 0) + '</b><span>Delivered</span></div>';
    if (!opts.hideRevenue) {
      out += '<div class="gwi-kpi"><b>' + money0(s.revenue_cents) + '</b><span>Revenue</span></div>';
    }
    if (opts.showTips) {
      out += '<div class="gwi-kpi"><b>' + money0(s.tips_cents) + '</b><span>Tips</span></div>';
    }
    out += '<div class="gwi-kpi"><b>' +
           (s.avg_order_cents == null ? '—' : money(s.avg_order_cents)) +
           '</b><span>Avg order</span></div>';
    out += '</div>';
    if (s.avg_order_cents == null && s.avg_order_needs) {
      out += '<div class="gwi-note">Average order needs ' + s.avg_order_needs +
             ' more to be meaningful.</div>';
    }

    out += '<div class="gwi-sec">Last 30 days</div>' + sparkline(d.series);
    out += '<div class="gwi-sec">Week over week</div>' + trendBlock(d.trend);
    out += '<div class="gwi-sec">Looking ahead</div>' + projectionBlock(d.projection);

    var bh = d.busiest_hours || {};
    out += '<div class="gwi-sec">When you\'re busiest</div>';
    if (bh.confidence === 'ok' && bh.hours.length) {
      out += bh.hours.map(function (h) {
        return '<div class="gwi-row"><span>' + hour12(h.hour) + '</span><b>' +
               h.orders + ' orders</b></div>';
      }).join('');
      var bd = d.busiest_days || {};
      if (bd.confidence === 'ok') {
        out += bd.days.map(function (x) {
          return '<div class="gwi-row"><span>' + esc(x.day) + '</span><b>' +
                 x.orders + ' orders</b></div>';
        }).join('');
      }
    } else {
      out += thin('Needs about ' + (bh.needs || 'a few') +
                  ' more orders before a real rush hour shows up.');
    }

    if (d.top_items && d.top_items.length) {
      out += '<div class="gwi-sec">Best sellers</div>';
      out += d.top_items.map(function (i, n) {
        return '<div class="gwi-row"><span>' + (n + 1) + '. ' + esc(i.name) +
               '</span><b>' + i.qty + '×</b></div>';
      }).join('');
    }

    var rp = d.repeat || {};
    out += '<div class="gwi-sec">Neighbors coming back</div>';
    if (rp.confidence === 'ok') {
      out += '<div class="gwi-row"><span>' + rp.returning + ' of ' + rp.customers +
             ' ordered more than once</span><b>' + rp.repeat_pct + '%</b></div>';
    } else {
      out += thin('Needs ' + (rp.needs || 'a few') +
                  ' more customers before repeat rate means anything.');
    }

    if (d.by_partner && d.by_partner.length) {
      out += '<div class="gwi-sec">By kitchen</div>';
      out += d.by_partner.map(function (p) {
        return '<div class="gwi-row"><span>' + esc(p.partner) + '</span><b>' +
               p.orders + ' · ' + money0(p.revenue_cents) + '</b></div>';
      }).join('');
    }

    el.innerHTML = out;
  }

  window.gwInsights = { render: render };
})();
