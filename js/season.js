/* Totally Cape Cod — season switch (summer ⇄ off-season).
 *
 * ONE place controls the season for the whole site: data/season.json
 *   "mode": "auto"      → summer between auto_summer_start and auto_summer_end (MM-DD), off-season otherwise
 *   "mode": "summer"    → force summer mode (lifeguard/parking info, beach-first Today screen, summer copy)
 *   "mode": "offseason" → force off-season mode
 * The file is read live from GitHub raw, so flipping it needs no deploy.
 * Preview either mode on any page with ?season=summer or ?season=offseason.
 *
 * Markup hooks (CSS added below):
 *   class="s-summer"      shown only in summer mode
 *   class="s-off"         shown only in off-season mode
 *   data-season-label     text replaced with "Summer 2027" / "Off-Season 2026–27"
 * JS: TCCSeason.isOff(), TCCSeason.pick(summerValue, offValue), TCCSeason.label()
 *     document.addEventListener('tcc:season', e => …)  — fires when the mode changes after load.
 */
(function () {
  var root = document.documentElement;
  var KEY = 'tcc_season';
  var DEF_START = '05-22', DEF_END = '09-14';
  var params = new URLSearchParams(location.search);
  var forced = params.get('season');
  if (forced !== 'summer' && forced !== 'offseason') forced = null;
  var branch = params.get('preview');
  if (!branch || !/^[A-Za-z0-9._\/-]+$/.test(branch)) branch = 'main';
  var RAW = 'https://raw.githubusercontent.com/zemiai/totallycapecod/' + branch + '/data/season.json';

  function md(s, fallback) {
    var m = /^(\d{1,2})-(\d{1,2})$/.exec(String(s || ''));
    return m ? (+m[1]) * 100 + (+m[2]) : md(fallback, '01-01');
  }
  function byDate(d, start, end) {
    var x = (d.getMonth() + 1) * 100 + d.getDate();
    var a = md(start, DEF_START), b = md(end, DEF_END);
    return (x >= a && x <= b) ? 'summer' : 'offseason';
  }
  function resolve(cfg, now) {
    now = now || new Date();
    var m = cfg && cfg.mode;
    if (m === 'summer' || m === 'offseason') return m;
    return byDate(now, cfg && cfg.auto_summer_start, cfg && cfg.auto_summer_end);
  }
  function label(mode, now) {
    now = now || new Date();
    mode = mode || root.dataset.season;
    var y = now.getFullYear();
    if (mode === 'summer') return 'Summer ' + y;
    var s = now.getMonth() >= 6 ? y : y - 1;          // Jul–Dec → this year's off-season
    return 'Off-Season ' + s + '–' + String((s + 1) % 100).padStart(2, '0');
  }
  function paintLabels() {
    var els = document.querySelectorAll('[data-season-label]');
    for (var i = 0; i < els.length; i++) els[i].textContent = label();
  }
  function set(mode, fromConfig) {
    var prev = root.dataset.season;
    root.dataset.season = mode;
    if (!forced) { try { localStorage.setItem(KEY, mode); } catch (e) {} }
    paintLabels();
    if (prev !== mode && fromConfig) {
      try { document.dispatchEvent(new CustomEvent('tcc:season', { detail: { mode: mode } })); } catch (e) {}
    }
  }

  // 1) Paint immediately: URL override → last known mode → date default. No flash on repeat visits.
  var cached = null;
  try { cached = localStorage.getItem(KEY); } catch (e) {}
  root.dataset.season = forced || ((cached === 'summer' || cached === 'offseason') ? cached : byDate(new Date()));

  // 2) Visibility rules for the two kinds of copy.
  var st = document.createElement('style');
  st.textContent = 'html[data-season="offseason"] .s-summer{display:none!important}' +
                   'html:not([data-season="offseason"]) .s-off{display:none!important}';
  (document.head || root).appendChild(st);

  // 3) Confirm against data/season.json (the one switch).
  window.TCCSeason = {
    mode: function () { return root.dataset.season; },
    isOff: function () { return root.dataset.season === 'offseason'; },
    pick: function (summerVal, offVal) { return root.dataset.season === 'offseason' ? offVal : summerVal; },
    label: label, resolve: resolve, config: null
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', paintLabels);
  else paintLabels();
  if (!forced && window.fetch) {
    fetch(RAW, { cache: 'no-cache' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (cfg) { if (cfg) { window.TCCSeason.config = cfg; set(resolve(cfg), true); } })
      .catch(function () {});
  }
})();
