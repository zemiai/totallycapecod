/* Totally Cape Cod — live upcoming events for static pages.
 * Renders real, scraped events (data/events.json + data/curated.json) into any
 * element with data-live-events. Every card credits its source and links to it.
 *   <div data-live-events data-limit="6"></div>
 *   data-group="day"  → group cards under date headings (events page)
 *   data-match="christmas|stroll"  → only events whose title/tag/venue matches (regex, case-insensitive)
 *   data-from="2026-11-20" data-to="2026-12-31"  → only events on these ET dates (inclusive)
 *   data-town="Chatham|Harwich"   → only these towns (regex)
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
      '<div style="font-size:12px;font-weight:700;color:var(--coral-soft,#c0563f);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px;">' + esc(e.tag || e.category || 'Event') + '</div>' +
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
  function render(el, events) {
    var limit = parseInt(el.getAttribute('data-limit') || '6', 10);
    var group = el.getAttribute('data-group') === 'day';
    var match = safeRe(el.getAttribute('data-match'));
    var townRe = safeRe(el.getAttribute('data-town'));
    var from = el.getAttribute('data-from') || '', to = el.getAttribute('data-to') || '';
    var list = events.filter(function (e) {
      var day = eventDay(e);
      if (from && day < from) return false;
      if (to && day > to) return false;
      if (townRe && !townRe.test(e.town || '')) return false;
      if (match && !match.test([e.title, e.tag, e.venue, e.info].join(' '))) return false;
      return true;
    }).slice(0, limit);
    if (!list.length) {
      el.innerHTML = '<p style="color:var(--text-secondary,#6b6b6b);">No upcoming events are listed right now — check back soon, or open the app for tonight\'s picks.</p>';
      return;
    }
    if (!group) { el.innerHTML = '<div class="grid-3">' + list.map(card).join('') + '</div>'; return; }
    var html = '', cur = '';
    list.forEach(function (e) {
      var k = eventDay(e);
      if (k !== cur) {
        if (cur) html += '</div></section>';
        cur = k;
        html += '<section class="section"><h2 class="section-title">' + esc(dayLabel(k)) + '</h2><div class="grid-3">';
      }
      html += card(e);
    });
    el.innerHTML = html + '</div></section>';
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
        if (isDateOnly(e) ? day < today : t < cutoff) return;
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
      for (var i = 0; i < els.length; i++) render(els[i], out);
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
