/* Totally Cape Cod — live upcoming events for static pages.
 * Renders real, scraped events (data/events.json + data/curated.json) into any
 * element with data-live-events. Every card credits its source and links to it.
 *   <div data-live-events data-limit="6"></div>
 *   data-group="day"  → group cards under date headings (events page)
 *   data-match="christmas|stroll"  → only events whose title/tag/venue matches (regex, case-insensitive)
 *   data-from="2026-11-20" data-to="2026-12-31"  → only events on these ET dates (inclusive)
 *   data-town="Chatham|Harwich"   → only these towns (regex)
 *   data-controls      → date controls (Today / This weekend / Next 7 days / pick a date);
 *                        the page URL keeps the choice (?date=2026-12-12 or ?when=weekend)
 */
(function () {
  var params = new URLSearchParams(location.search);
  var branch = params.get('preview');
  if (!branch || !/^[A-Za-z0-9._\/-]+$/.test(branch)) branch = 'main';
  var BASE = 'https://raw.githubusercontent.com/zemiai/totallycapecod/' + branch + '/data/';
  var TZ = 'America/New_York';

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
  // Date-only listings arrive as midnight UTC ("2026-10-31T00:00:00+00:00"), which is the
  // evening BEFORE in Eastern time — treat those as all-day events on their own date.
  function isDateOnly(e) { return /T00:00(:00)?(\.0+)?(Z|\+00:00)$/.test(String(e.start || '')); }
  function eventDay(e) { return isDateOnly(e) ? String(e.start).slice(0, 10) : dayKey(new Date(e.start)); }
  // Last day of a multi-day listing (its own day when there's no end time).
  function endDay(e) { var t = e.end ? Date.parse(e.end) : NaN; return isNaN(t) ? eventDay(e) : dayKey(new Date(t)); }
  function eventSortTime(e) { return isDateOnly(e) ? Date.parse(String(e.start).slice(0, 10) + 'T12:00:00Z') : Date.parse(e.start); }
  function norm(t) { return String(t || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim(); }
  function dayKey(d) {
    return new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
  }
  function dayLabel(k) {
    var today = dayKey(new Date()), tmr = dayKey(new Date(Date.now() + 864e5));
    var d = new Date(k + 'T12:00:00Z');
    var pretty = new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', weekday: 'long', month: 'long', day: 'numeric' }).format(d);
    return k === today ? 'Today · ' + pretty : k === tmr ? 'Tomorrow · ' + pretty : pretty;
  }
  function timeLabel(e) {
    var t = String(e.time || '').split('·').pop().trim();
    if (/AM|PM/.test(t)) return t;
    var k = eventDay(e);
    return new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', weekday: 'short', month: 'short', day: 'numeric' }).format(new Date(k + 'T12:00:00Z'));
  }
  // Credit where it's due: full organization names for each calendar we pull from.
  var CREDIT = {
    'Provincetown': 'Provincetown Chamber of Commerce', 'Eastham': 'Eastham Chamber of Commerce',
    'Orleans': 'Orleans Chamber of Commerce', 'Brewster': 'Brewster Chamber of Commerce',
    'Chatham': 'Chatham Chamber of Commerce', 'Harwich': 'Harwich Chamber of Commerce',
    'Dennis': 'Dennis Chamber of Commerce', 'Yarmouth': 'Yarmouth Chamber of Commerce',
    'Hyannis': 'Hyannis Area Chamber of Commerce', 'Mashpee': 'Mashpee Chamber of Commerce',
    'Bourne': 'Cape Cod Canal Region Chamber of Commerce', 'Provincetown Events': 'Ptownie.com',
    'Heritage Museums': 'Heritage Museums & Gardens', 'Highfield Hall': 'Highfield Hall & Gardens',
    'Payomet': 'Payomet Performing Arts Center', 'Melody Tent': 'Cape Cod Melody Tent'
  };
  function card(e) {
    var where = [e.venue, e.town].filter(Boolean).map(esc).join(' · ');
    var src = safeUrl(e.source_url);
    var who = e.credit || CREDIT[e.source] || e.source;
    var credit = who ? (src
      ? 'via <a href="' + esc(src) + '" target="_blank" rel="noopener">' + esc(who) + '</a>'
      : 'via ' + esc(who)) : '';
    return '<div class="card live-ev" style="padding:18px;">' +
      '<div style="font-size:12px;font-weight:700;color:var(--coral-soft,#c0563f);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px;">' + esc(String(e.tag || e.category || 'Event').replace(/📅\s*/g, '')) + '</div>' +
      '<h3 style="font-weight:700;font-size:16px;margin:0 0 4px;line-height:1.3;">' + (src ? '<a href="' + esc(src) + '" target="_blank" rel="noopener" style="color:inherit;text-decoration:none;">' + esc(e.title) + '</a>' : esc(e.title)) + '</h3>' +
      '<p style="font-size:13px;color:var(--text-secondary,#6b6b6b);margin:0 0 8px;">' + where + (where ? ' · ' : '') + esc(timeLabel(e)) + '</p>' +
      (e.price ? '<p style="font-size:13px;margin:0 0 8px;">🎟️ ' + esc(e.price) + '</p>' : '') +
      (credit ? '<p style="font-size:12px;color:var(--text-secondary,#6b6b6b);margin:0;">' + credit + '</p>' : '') +
      '</div>';
  }
  function safeRe(src) {
    if (!src) return null;
    try { return new RegExp(src, 'i'); } catch (e) { return null; }
  }
  function shiftDay(k, n) { var d = new Date(k + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); }
  // Ranges for the date controls, as ET calendar dates [from, to].
  function rangeFor(when) {
    var today = dayKey(new Date());
    if (/^\d{4}-\d{2}-\d{2}$/.test(when || '')) return [when, when];
    if (when === 'today') return [today, today];
    if (when === 'week') return [today, shiftDay(today, 6)];
    if (when === 'weekend') {
      var dow = new Date(today + 'T12:00:00Z').getUTCDay();          // 0 Sun … 6 Sat
      if (dow === 0) return [today, today];                           // Sunday: just today
      if (dow === 6) return [today, shiftDay(today, 1)];              // Saturday: Sat–Sun
      var fri = shiftDay(today, 5 - dow);                             // Mon–Fri: this Fri–Sun
      return [fri, shiftDay(fri, 2)];
    }
    return ['', ''];
  }
  function render(el, events) {
    var limit = parseInt(el.getAttribute('data-limit') || '6', 10);
    var group = el.getAttribute('data-group') === 'day';
    var match = safeRe(el.getAttribute('data-match'));
    var townRe = safeRe(el.getAttribute('data-town'));
    var from = el.getAttribute('data-from') || '', to = el.getAttribute('data-to') || '';
    var when = el.getAttribute('data-when') || '';
    if (when) { var r = rangeFor(when); if (r[0] > from) from = r[0]; if (!to || (r[1] && r[1] < to)) to = r[1] || to; }
    var lastDay = events.length ? eventDay(events[events.length - 1]) : '';
    var list = events.filter(function (e) {
      var day = eventDay(e);
      if (from && endDay(e) < from) return false;     // multi-day events count on every day they run
      if (to && day > to) return false;
      if (townRe && !townRe.test(e.town || '')) return false;
      if (match && !match.test([e.title, e.tag, e.venue, e.info].join(' '))) return false;
      return true;
    }).slice(0, limit);
    if (!list.length) {
      var msg = when
        ? 'Nothing is listed for ' + esc(from === to ? dayLabel(from) : dayLabel(from) + ' – ' + dayLabel(to)) + ' yet.' +
          (lastDay && from > lastDay ? ' Our calendar currently runs through ' + esc(dayLabel(lastDay)) + '.' : '') +
          ' For holiday strolls and parades with confirmed dates, see our <a href="/guides/cape-cod-holiday-events-2026/">holiday events guide</a>.'
        : 'No upcoming events are listed right now — check back soon, or open the app for tonight\'s picks.';
      el.innerHTML = '<p style="color:var(--text-secondary,#6b6b6b);">' + msg + '</p>';
      return;
    }
    if (!group) { el.innerHTML = '<div class="grid-3">' + list.map(card).join('') + '</div>'; return; }
    var html = '', cur = '', today = dayKey(new Date());
    var floor = from && from > today ? from : today;
    // Ongoing multi-day events go under the first day shown (e.g. Today), not their past start date.
    function groupDay(e) { var k = eventDay(e); return (k < floor && endDay(e) >= floor) ? floor : k; }
    // Say so when nothing is listed for today, instead of silently starting tomorrow.
    if ((!from || from <= today) && (!to || to >= today) && groupDay(list[0]) > today) {
      html += '<section class="section"><h2 class="section-title">' + esc(dayLabel(today)) + '</h2>' +
        '<p style="color:var(--text-secondary,#6b6b6b);">Nothing is listed for today. Next up: ' + esc(dayLabel(groupDay(list[0])).replace(/^Tomorrow · /, 'tomorrow, ')) + '.</p></section>';
    }
    list.forEach(function (e) {
      var k = groupDay(e);
      if (k !== cur) {
        if (cur) html += '</div></section>';
        cur = k;
        html += '<section class="section"><h2 class="section-title">' + esc(dayLabel(k)) + '</h2><div class="grid-3">';
      }
      html += card(e);
    });
    el.innerHTML = html + '</div></section>';
  }
  function controls(el, events) {
    var bar = document.createElement('div');
    bar.className = 'ev-controls';
    var last = events.length ? eventDay(events[events.length - 1]) : '';
    var today = dayKey(new Date());
    var opts = [['', 'All upcoming'], ['today', 'Today'], ['weekend', 'This weekend'], ['week', 'Next 7 days']];
    bar.innerHTML = opts.map(function (o) {
      return '<button type="button" class="ev-chip" data-when="' + o[0] + '">' + o[1] + '</button>';
    }).join('') +
      '<label class="ev-date">Pick a date <input type="date" min="' + today + '"' + (last ? ' max="' + last + '"' : '') + '></label>' +
      (last ? '<span class="ev-range">Listings run through ' + esc(dayLabel(last).replace(/^(Today|Tomorrow) · /, '')) + '</span>' : '');
    var input = bar.querySelector('input');
    function apply(when, push) {
      if (when) el.setAttribute('data-when', when); else el.removeAttribute('data-when');
      var chips = bar.querySelectorAll('.ev-chip');
      for (var i = 0; i < chips.length; i++) {
        var on = chips[i].getAttribute('data-when') === (when || '') && !/^\d{4}/.test(when || '');
        chips[i].classList.toggle('on', on);
        chips[i].setAttribute('aria-pressed', on ? 'true' : 'false');
      }
      input.value = /^\d{4}-\d{2}-\d{2}$/.test(when || '') ? when : '';
      if (push) {
        try {
          var q = new URLSearchParams(location.search);
          q.delete('date'); q.delete('when');
          if (/^\d{4}/.test(when || '')) q.set('date', when); else if (when) q.set('when', when);
          history.replaceState(null, '', location.pathname + (q.toString() ? '?' + q : '') + location.hash);
        } catch (e) {}
      }
      render(el, events);
    }
    bar.addEventListener('click', function (ev) {
      var b = ev.target.closest('.ev-chip');
      if (b) apply(b.getAttribute('data-when'), true);
    });
    input.addEventListener('change', function () { apply(input.value, true); });
    el.parentNode.insertBefore(bar, el);
    var start = params.get('date') || params.get('when') || '';
    if (!/^(\d{4}-\d{2}-\d{2}|today|weekend|week)$/.test(start)) start = '';
    apply(start, false);
  }
  function addStyles() {
    if (document.getElementById('ev-controls-css')) return;
    var st = document.createElement('style');
    st.id = 'ev-controls-css';
    st.textContent = '.ev-controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0 4px}' +
      '.ev-chip{min-height:44px;padding:0 16px;border-radius:999px;border:1px solid var(--divider,#e6dccf);background:#fff;color:var(--text,#4a4038);font:inherit;font-weight:600;cursor:pointer}' +
      '.ev-chip.on{background:var(--cape-navy,#1A3A6C);border-color:var(--cape-navy,#1A3A6C);color:#fff}' +
      '.ev-date{display:inline-flex;align-items:center;gap:8px;font-weight:600;color:var(--text,#4a4038)}' +
      '.ev-date input{min-height:44px;font-size:16px;padding:0 10px;border:1px solid var(--divider,#e6dccf);border-radius:12px;background:#fff;color:inherit}' +
      '.ev-range{font-size:14px;color:var(--text-secondary,#6b6b6b);width:100%}';
    document.head.appendChild(st);
  }
  function init() {
    var els = document.querySelectorAll('[data-live-events]');
    if (!els.length) return;
    Promise.all([getJSON('events.json'), getJSON('curated.json')]).then(function (res) {
      var all = [].concat((res[0] && res[0].events) || [], (res[1] && res[1].events) || []);
      var cutoff = Date.now() - 2 * 3600 * 1000, today = dayKey(new Date()), seenId = {}, byDay = {}, out = [];
      all.forEach(function (e) {
        if (!e || !e.start || !e.title) return;
        var t = Date.parse(e.start);
        if (isNaN(t)) return;
        var day = eventDay(e);
        var endT = e.end ? Date.parse(e.end) : NaN;
        if (!isNaN(endT) ? endT < Date.now() : (isDateOnly(e) ? day < today : t < cutoff)) return;
        // Same event listed twice (two chambers, or an id-less repeat) → keep one.
        var n = norm(e.title), seen = byDay[day] || (byDay[day] = []);
        if ((e.id && seenId[e.id]) || seen.some(function (s) {
          return s === n || (Math.min(s.length, n.length) >= 12 && (s.indexOf(n) >= 0 || n.indexOf(s) >= 0));
        })) return;
        if (e.id) seenId[e.id] = 1;
        seen.push(n);
        out.push(e);
      });
      out.sort(function (a, b) { return eventSortTime(a) - eventSortTime(b); });
      for (var i = 0; i < els.length; i++) {
        if (els[i].hasAttribute('data-controls')) { addStyles(); controls(els[i], out); }
        else render(els[i], out);
      }
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
