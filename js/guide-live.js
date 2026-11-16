/* Totally Cape Cod: "live strip" for guide pages. An enhancement only.
 * The page ships a single static line; this script replaces it with up to three parts, each only when
 * its data file loads and is current. Nothing is shown from memory or as a placeholder.
 *   <section class="gl" data-gl data-towns='["Chatham","Orleans"]'>…static line…</section>
 * Data: data/events.json + data/curated.json, data/bridges.json, data/conditions.json (same raw GitHub
 * location and ?preview=branch switch as js/live-events.js).
 * Rules reused from existing pages:
 *   events      live-events.js (date-only listings are all-day on their own Eastern date; same de-duplication)
 *   bridges     app (an hour or older: dimmed, shown with the reading time; the reading time is the file's updated_at)
 *   conditions  home page (the file's date must be today's Cape Cod date)
 * Added here, on purpose: a bridge reading older than 24 hours is not shown at all.
 */
(function () {
  var root = document.querySelector('[data-gl]');
  if (!root) return;
  var params = new URLSearchParams(location.search);
  var branch = params.get('preview');
  if (!branch || !/^[A-Za-z0-9._\/-]+$/.test(branch)) branch = 'main';
  var BASE = 'https://raw.githubusercontent.com/zemiai/totallycapecod/' + branch + '/data/';
  var TZ = 'America/New_York';
  var towns = [];
  try { towns = JSON.parse(root.getAttribute('data-towns') || '[]'); } catch (e) { towns = []; }
  if (!Array.isArray(towns)) towns = [];

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function safeUrl(u) { return /^https?:\/\//i.test(String(u || '')) ? String(u) : ''; }
  function getJSON(name) {
    return fetch(BASE + name, { cache: 'no-cache' }).then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }
  function dayKey(d) {
    return new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
  }
  function shiftDay(k, n) { var d = new Date(k + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); }
  function clock(t) {
    return new Intl.DateTimeFormat('en-US', { timeZone: TZ, hour: 'numeric', minute: '2-digit' }).format(new Date(t)).replace(/[\u202f\u00a0]/g, ' ');
  }
  function shortDay(k) {
    return new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', weekday: 'short', month: 'short', day: 'numeric' }).format(new Date(k + 'T12:00:00Z'));
  }
  function longDay(k) {
    return new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', weekday: 'long', month: 'long', day: 'numeric' }).format(new Date(k + 'T12:00:00Z'));
  }

  /* ---------- events (rules from live-events.js) ---------- */
  function isDateOnly(e) { return /T00:00(:00)?(\.0+)?(Z|\+00:00)$/.test(String(e.start || '')); }
  function eventDay(e) { return isDateOnly(e) ? String(e.start).slice(0, 10) : dayKey(new Date(e.start)); }
  function endDay(e) { var t = e.end ? Date.parse(e.end) : NaN; return isNaN(t) ? eventDay(e) : dayKey(new Date(t)); }
  function sortTime(e) { return isDateOnly(e) ? Date.parse(String(e.start).slice(0, 10) + 'T12:00:00Z') : Date.parse(e.start); }
  function norm(t) { return String(t || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim(); }
  function timeText(e) {
    var t = String(e.time || '').split('·').pop().trim();
    if (/AM|PM/.test(t)) return t.replace(/\s*[\u2013\u2014-]\s*/g, ' to ').replace(/(\d:\d\d) to (\d)/, '$1 to $2');
    if (!isDateOnly(e) && !isNaN(Date.parse(e.start))) return clock(Date.parse(e.start));
    return '';
  }
  function townOk(t) {
    if (!towns.length) return true;
    t = String(t || '').toLowerCase().trim();
    return towns.some(function (g) {
      g = String(g).toLowerCase().trim();
      // village names count for their town ("South Dennis" for Dennis, "Yarmouth Port" for Yarmouth)
      return t === g || t.indexOf(g + ' ') === 0 || t.slice(-(g.length + 1)) === ' ' + g;
    });
  }
  function upcoming(res) {
    var all = [].concat((res[0] && res[0].events) || [], (res[1] && res[1].events) || []);
    var now = Date.now(), cutoff = now - 2 * 3600 * 1000, today = dayKey(new Date(now)), seenId = {}, byDay = {}, out = [];
    all.forEach(function (e) {
      if (!e || !e.start || !e.title) return;
      var t = Date.parse(e.start);
      if (isNaN(t) || !townOk(e.town)) return;
      var day = eventDay(e), endT = e.end ? Date.parse(e.end) : NaN;
      if (!isNaN(endT) ? endT < now : (isDateOnly(e) ? day < today : t < cutoff)) return;
      var n = norm(e.title), seen = byDay[day] || (byDay[day] = []);
      if ((e.id && seenId[e.id]) || seen.some(function (s) {
        return s === n || (Math.min(s.length, n.length) >= 12 && (s.indexOf(n) >= 0 || n.indexOf(s) >= 0));
      })) return;
      if (e.id) seenId[e.id] = 1;
      seen.push(n);
      out.push(e);
    });
    out.sort(function (a, b) { return sortTime(a) - sortTime(b); });
    return out;
  }
  function eventsPart(res) {
    var list = upcoming(res);
    if (!list.length) return null;
    var today = dayKey(new Date()), dow = new Date(today + 'T12:00:00Z').getUTCDay();
    var weekend = dow === 5 || dow === 6 || dow === 0;          // Friday to Sunday: look at the weekend
    var to = !weekend ? today : dow === 0 ? today : dow === 6 ? shiftDay(today, 1) : shiftDay(today, 2);
    var heading = weekend ? 'On this weekend' : 'On today';
    var inRange = list.filter(function (e) { return endDay(e) >= today && eventDay(e) <= to; });
    // Events that started earlier are shown on today; ones starting today come first.
    inRange.sort(function (a, b) { return (eventDay(b) < today ? 0 : 1) - (eventDay(a) < today ? 0 : 1) || 0; });
    var shown = inRange.length ? inRange : list.filter(function (e) { return eventDay(e) > to; });
    var lead = '';
    if (!inRange.length) {
      lead = '<p class="gl-m">Nothing is listed for ' + (weekend ? 'this weekend' : 'today') + '. Next up:</p>';
    }
        var more = shown.length ? (inRange.length ? inRange.length : shown.filter(function (e) { return eventDay(e) === eventDay(shown[0]); }).length) - 1 : 0;
    shown = shown.slice(0, 3);
    if (!shown.length) return null;
    var tomorrow = shiftDay(today, 1);
    var compact = '';
    var items = shown.map(function (e, i) {
      var k = eventDay(e); if (k < today) k = today;
      var label = k === today ? 'Today' : k === tomorrow ? 'Tomorrow' : shortDay(k);
      var tm = timeText(e);
      var src = safeUrl(e.source_url), ext = !!src;
      var href = src || '/events?date=' + k;
      var where = e.town ? String(e.town) : '';
      var meta = label + (tm ? ', ' + tm : '') + (where ? ', ' + where : '');
      var credit = e.credit ? 'Via ' + e.credit : '';
      if (i === 0) {
        var lab = inRange.length ? (weekend ? 'This weekend' : 'On today') : 'Next up';
        var tx = (inRange.length ? '' : (weekend ? 'Nothing listed this weekend, next up: ' : 'Nothing listed today, next up: ')) + e.title +
          (inRange.length && label !== 'Today' ? ', ' + label : (inRange.length ? '' : ', ' + label)) + (tm ? ', ' + tm : '') + (where ? ', ' + where : '') +
          (more > 0 ? ', and ' + more + ' more' : '');
        compact = '<a class="gl-r" href="' + esc(more > 0 ? '/events?date=' + k : href) + '"' + (more <= 0 && ext ? ' target="_blank" rel="noopener"' : '') +
          '><span class="gl-lab">' + heading + '</span><span class="gl-tx">' + esc(tx) + '</span></a>';
      }
      return '<li><a class="gl-ev" href="' + esc(href) + '"' + (ext ? ' target="_blank" rel="noopener"' : '') + '><b>' + esc(e.title) + '</b>' +
        '<span>' + esc(meta) + '</span>' + (credit ? '<span class="gl-src">' + esc(credit) + '</span>' : '') + '</a></li>';
    }).join('');
    return { full: '<div class="gl-col gl-evs"><h3>' + heading + '</h3>' + lead + '<ul>' + items + '</ul></div>', compact: compact, src: 'event organizers' };
  }

  /* ---------- bridges (app rule: an hour or older is dimmed, with the reading time) ---------- */
  function bridgeLine(b, label) {
    if (!b || typeof b.current_delay_min !== 'number' || isNaN(b.current_delay_min)) return '';
    var m = b.current_delay_min;
    return '<p class="gl-row"><b>' + esc(label) + '</b> ' + (m <= 0 ? 'no added delay' : esc(m) + (m === 1 ? ' minute' : ' minutes')) + '</p>';
  }
  function bridgesPart(d) {
    var cur = d && d.current, t = d ? Date.parse(d.updated_at || '') : NaN;
    if (!cur || isNaN(t)) return null;
    var age = Date.now() - t;
    if (age > 24 * 3600 * 1000 || age < -5 * 60 * 1000) return null;
    var rows = bridgeLine(cur.sagamore, 'Sagamore') + bridgeLine(cur.bourne, 'Bourne');
    if (!rows) return null;
    var old = age >= 3600 * 1000;
    var when = clock(t) + (dayKey(new Date(t)) === dayKey(new Date()) ? '' : ', ' + shortDay(dayKey(new Date(t))));
    var dir = (cur.sagamore && cur.sagamore.direction === 'off_cape' && cur.bourne && cur.bourne.direction === 'off_cape') ? 'Leaving the Cape. ' : '';
    function ph(b) { var m = b.current_delay_min; return m <= 0 ? 'no added delay' : m + ' min'; }
    var sg = bridgeLine(cur.sagamore, 'x') ? cur.sagamore : null, bo = bridgeLine(cur.bourne, 'x') ? cur.bourne : null, said;
    if (sg && bo) said = (ph(sg) === ph(bo)) ? (sg.current_delay_min <= 0 ? 'No added delay at either bridge' : ph(sg) + ' at either bridge') : 'Sagamore ' + ph(sg) + ', Bourne ' + ph(bo);
    else said = (sg ? 'Sagamore ' + ph(sg) : 'Bourne ' + ph(bo));
    var ctext = said + ', ' + when + ' reading' + (old ? ', more than an hour old' : '');
    var compact = '<a class="gl-r' + (old ? ' gl-dim' : '') + '" href="/cape-cod-bridge-traffic.html"><span class="gl-lab">Bridges now</span><span class="gl-tx">' + esc(ctext) + '</span></a>';
    return { compact: compact, src: 'Google Maps traffic', full: '<div class="gl-col' + (old ? ' gl-dim' : '') + '"><h3>Bridges now</h3>' + rows +
      '<p class="gl-m">' + dir + 'Google Maps traffic, ' + (old ? 'reading from ' + esc(when) + ', more than an hour old' : 'checked ' + esc(when)) + '.</p>' +
      '<a class="gl-go" href="/cape-cod-bridge-traffic.html">Bridge traffic details</a></div>' };
  }

  /* ---------- conditions (home page rule: only the file's own date, today in Cape Cod) ---------- */
  function conditionsPart(d) {
    var t = d && d.today, upd = d ? Date.parse(d.updated_at || '') : NaN;
    if (!t || t.date !== dayKey(new Date()) || isNaN(upd)) return null;
    var w = t.weather || {}, s = t.sun || {}, rows = '', src = [];
    var hi = typeof w.temp_high === 'number', lo = typeof w.temp_low === 'number';
    if (hi) {
      rows += '<p class="gl-row"><b>Air</b> high ' + esc(Math.round(w.temp_high)) + '°F' + (lo ? ', low ' + esc(Math.round(w.temp_low)) + '°F' : '') + '</p>';
      if (t.weather_source) src.push('Weather: ' + String(t.weather_source).replace(/\s*\(.*\)\s*$/, ''));
    }
    if (typeof s.sunset === 'string' && /\d/.test(s.sunset)) {
      rows += '<p class="gl-row"><b>Sunset</b> ' + esc(s.sunset) + '</p>';
      if (s.source) src.push('sunset: ' + s.source);
    }
    if (!rows) return null;
    var ctx = [hi ? 'High ' + Math.round(w.temp_high) + '°F' + (lo ? ', low ' + Math.round(w.temp_low) + '°F' : '') : '', (typeof s.sunset === 'string' && /\d/.test(s.sunset)) ? (hi ? 'sunset ' : 'Sunset ') + s.sunset : ''].filter(Boolean).join(', ');
    var by = src.length ? src.join('; ').replace(/^./, function (c) { return c.toUpperCase(); }) + '. ' : '';
    return { compact: '<a class="gl-r" href="/app/"><span class="gl-lab">Today</span><span class="gl-tx">' + esc(ctx) + '</span></a>',
      src: src.map(function (x) { return x.replace(/^(Weather|sunset): /i, ''); }), checked: clock(upd),
      full: '<div class="gl-col"><h3>Today\'s conditions</h3>' + rows +
      '<p class="gl-m">' + esc(by) + 'Checked ' + esc(clock(upd)) + '.</p>' +
      '<a class="gl-go" href="/app/">Tides and more in the app</a></div>' };
  }

  function run() {
    Promise.all([getJSON('events.json'), getJSON('curated.json'), getJSON('bridges.json'), getJSON('conditions.json')]).then(function (r) {
      var got = [];
      [function () { return eventsPart([r[0], r[1]]); }, function () { return bridgesPart(r[2]); }, function () { return conditionsPart(r[3]); }]
        .forEach(function (f) { try { var x = f(); if (x) got.push(x); } catch (e) {} });
      if (!got.length) { root.className += ' gl-none'; return; }   // keep the static line, no reserved gap
      var srcs = [], checked = '';
      got.forEach(function (g) { srcs = srcs.concat(g.src); if (g.checked) checked = g.checked; });
      root.innerHTML = '<div class="gl-cols">' + got.map(function (g) { return g.full; }).join('') + '</div>' +
        '<div class="gl-compact">' + got.map(function (g) { return g.compact; }).join('') +
        '<p class="gl-m gl-srcs">Sources: ' + esc(srcs.join(', ')) + '.' + (checked ? ' Checked ' + esc(checked) + '.' : '') + '</p></div>' +
        '<p class="gl-all"><a href="/events?when=week">See everything on this week</a></p>';
      root.setAttribute('data-gl-ready', '1');
    });
  }
  // After first paint, never during it.
  if (window.requestAnimationFrame) requestAnimationFrame(function () { setTimeout(run, 0); });
  else setTimeout(run, 0);
})();
