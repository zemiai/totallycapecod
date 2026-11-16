/* Totally Cape Cod: "My list". One list for the whole site, kept on this device only.
 * No accounts, no network calls, no third-party scripts. Include in <head> (it is small).
 *
 * An item is {id, type, name, town, address, url, detail?, stub?}.
 *   id      "<type>:<stable slug>", for example "beach:nauset-beach" or "shop:brewster-book-store"
 *   type    shop | event | beach | eat | stay | experience
 *   url     a path on this site that leads back to the listing (never an outside address)
 *   detail  optional one line from the listing (an event's date and place)
 *   stub    a shop carried over from the gift guide's older storage key, name not known yet;
 *           the gift guide fills it in the next time it is opened
 *
 * Buttons: any <button class="ml-add" data-ml-id=... data-ml-type=... data-ml-name=...
 * data-ml-town=... data-ml-address=... data-ml-url=... data-ml-detail=...> is a toggle.
 * TCCList.btnHtml(item) makes one (hidden until this script has switched it on, so pages
 * without JavaScript show nothing). Buttons added to the page later are found automatically.
 */
(function () {
  'use strict';
  if (window.TCCList) return;

  var KEY = 'tcc-mylist-v1';
  var OLD_GIFT_KEY = 'tcc-gift-shops-2026-list';
  var GIFT_GUIDE = '/guides/cape-cod-holiday-gift-shops-2026/';
  var TYPES = ['shop', 'event', 'beach', 'eat', 'stay', 'experience'];
  var LABELS = { shop: 'Shops', event: 'Events', beach: 'Beaches', eat: 'Places to eat', stay: 'Places to stay', experience: 'Experiences' };
  var MAX_ITEMS = 200;

  var items = [];
  var migrated = false;
  var persistent = true;
  var listeners = [];

  /* ---- storage (every access guarded: if it is blocked the list lasts for this visit) ---- */
  function readRaw(key) {
    try { return window.localStorage.getItem(key); } catch (e) { persistent = false; return null; }
  }
  function writeRaw(key, val) {
    try { window.localStorage.setItem(key, val); } catch (e) { persistent = false; }
  }
  function str(v, max) { return typeof v === 'string' ? v.replace(/\s+/g, ' ').trim().slice(0, max) : ''; }

  function clean(o) {
    if (!o || typeof o !== 'object') return null;
    var type = str(o.type, 20);
    if (TYPES.indexOf(type) < 0) return null;
    var id = str(o.id, 160);
    if (id.indexOf(type + ':') !== 0 || id.length === type.length + 1) return null;
    var url = str(o.url, 300);
    if (url && (url.charAt(0) !== '/' || url.charAt(1) === '/' || url.indexOf('\\') > -1)) url = '';
    var it = { id: id, type: type, name: str(o.name, 160), town: str(o.town, 120), address: str(o.address, 200), url: url };
    var detail = str(o.detail, 240);
    if (detail) it.detail = detail;
    if (o.stub === true && !it.name) it.stub = true;
    if (!it.name && !it.stub) return null;
    return it;
  }

  function indexOf(id) {
    for (var i = 0; i < items.length; i++) if (items[i].id === id) return i;
    return -1;
  }

  function load() {
    items = [];
    migrated = false;
    var raw = readRaw(KEY), data = null;
    if (raw) { try { data = JSON.parse(raw); } catch (e) { data = null; } }
    if (data && Array.isArray(data.items)) {
      data.items.forEach(function (o) {
        var it = clean(o);
        if (it && indexOf(it.id) < 0 && items.length < MAX_ITEMS) items.push(it);
      });
    }
    migrated = !!(data && data.mig);
  }

  function save() {
    writeRaw(KEY, JSON.stringify({ v: 1, mig: migrated ? 1 : 0, items: items }));
  }

  /* Shops saved in the gift guide before the shared list existed: carry them over once. */
  function migrate() {
    if (migrated) return;
    var raw = readRaw(OLD_GIFT_KEY), ids = null;
    if (raw === null) return;
    try { ids = JSON.parse(raw); } catch (e) { ids = null; }
    migrated = true;
    if (Array.isArray(ids)) {
      ids.forEach(function (a) {
        if (typeof a !== 'string' || !/^[a-z0-9-]{1,100}$/.test(a)) return;
        var it = clean({ id: 'shop:' + a, type: 'shop', name: '', url: GIFT_GUIDE + '#' + a, stub: true });
        if (it && indexOf(it.id) < 0 && items.length < MAX_ITEMS) items.push(it);
      });
    }
    save();
  }

  /* ---- change notification ---- */
  function changed() {
    save();
    notify();
  }
  function notify() {
    listeners.slice().forEach(function (fn) { try { fn(); } catch (e) { /* a page's handler must not break the list */ } });
    updateNav();
    paint();
  }

  /* ---- the list ---- */
  var api = {
    TYPES: TYPES,
    LABELS: LABELS,
    get persistent() { return persistent; },
    items: function () { return items.map(function (i) { return clean(i) || i; }); },
    count: function () { return items.length; },
    has: function (id) { return indexOf(id) > -1; },
    add: function (o) {
      var it = clean(o);
      if (!it || it.stub) return false;
      if (indexOf(it.id) > -1 || items.length >= MAX_ITEMS) return false;
      items.push(it);
      changed();
      return true;
    },
    addMany: function (list) {
      var n = 0;
      (list || []).forEach(function (o) {
        var it = clean(o);
        if (it && !it.stub && indexOf(it.id) < 0 && items.length < MAX_ITEMS) { items.push(it); n++; }
      });
      if (n) changed();
      return n;
    },
    remove: function (id) {
      var i = indexOf(id);
      if (i < 0) return false;
      items.splice(i, 1);
      changed();
      return true;
    },
    toggle: function (o) {
      var id = o && o.id;
      if (indexOf(id) > -1) { api.remove(id); return false; }
      return api.add(o);
    },
    /* Update an item already on the list with what a listing page says now (also fills in a stub). */
    refresh: function (o) {
      var it = clean(o);
      if (!it || it.stub) return false;
      var i = indexOf(it.id);
      if (i < 0) return false;
      if (JSON.stringify(items[i]) === JSON.stringify(it)) return false;
      items[i] = it;
      changed();
      return true;
    },
    /* Take a stub off the list (the guide it came from no longer has that shop). */
    drop: function (id) {
      var i = indexOf(id);
      if (i < 0 || !items[i].stub) return false;
      items.splice(i, 1);
      changed();
      return true;
    },
    clear: function () {
      if (!items.length) return;
      items = [];
      changed();
    },
    onChange: function (fn) { if (typeof fn === 'function') listeners.push(fn); },

    /* Google Maps directions through the listed places that have an address:
       the last one is the destination, up to 8 more are waypoints (Maps takes 9 in all here). */
    mapsInfo: function (list) {
      var withAddr = (list || []).filter(function (i) { return i.address && !i.stub; });
      var shown = withAddr.slice(0, 10);
      var url = '';
      if (shown.length) {
        var enc = encodeURIComponent;
        var q = function (i) { return enc(i.name + ' ' + i.address); };
        var last = shown[shown.length - 1];
        var way = shown.slice(0, -1).map(q);
        url = 'https://www.google.com/maps/dir/?api=1&destination=' + q(last) + (way.length ? '&waypoints=' + way.join('%7C') : '');
      }
      return { url: url, shown: shown.length, withAddress: withAddr.length, total: (list || []).length };
    },

    /* A link that carries the items themselves (no server holds anything). */
    pack: function (list) {
      var rows = (list || []).filter(function (i) { return !i.stub; }).map(function (i) {
        return [i.id, i.name, i.town, i.address, i.url, i.detail || ''];
      });
      var b = window.btoa(unescape(encodeURIComponent(JSON.stringify(rows))));
      return '1.' + b.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    },
    /* Anything that arrives in a link is untrusted: every field is checked again. */
    unpack: function (s) {
      var out = [];
      try {
        if (typeof s !== 'string' || s.slice(0, 2) !== '1.' || s.length > 60000 || !/^[A-Za-z0-9_-]+$/.test(s.slice(2))) return out;
        var b = s.slice(2).replace(/-/g, '+').replace(/_/g, '/');
        while (b.length % 4) b += '=';
        var rows = JSON.parse(decodeURIComponent(escape(window.atob(b))));
        if (!Array.isArray(rows)) return out;
        rows.slice(0, MAX_ITEMS).forEach(function (r) {
          if (!Array.isArray(r) || typeof r[0] !== 'string') return;
          var type = r[0].split(':')[0];
          var it = clean({ id: r[0], type: type, name: r[1], town: r[2], address: r[3], url: r[4], detail: r[5] });
          if (it && !it.stub && !out.some(function (x) { return x.id === it.id; })) out.push(it);
        });
      } catch (e) { return []; }
      return out;
    },

    /* The markup for an "Add to my list" toggle. Hidden until this script switches it on. */
    btnHtml: function (o) {
      var it = clean(o);
      if (!it) return '';
      function e(s) { return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
      return '<button class="ml-add" type="button" aria-pressed="false" hidden' +
        ' data-ml-id="' + e(it.id) + '" data-ml-type="' + e(it.type) + '" data-ml-name="' + e(it.name) + '"' +
        ' data-ml-town="' + e(it.town) + '" data-ml-address="' + e(it.address) + '" data-ml-url="' + e(it.url) + '"' +
        ' data-ml-detail="' + e(it.detail || '') + '" aria-label="Add to my list: ' + e(it.name) + '">' +
        '<svg width="22" height="22" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M12 20S5 15.6 5 10a4 4 0 0 1 7-2.600A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/></svg>' +
        '<span>Add to my list</span></button>';
    },
    /* Add a toggle to a card that was written without one. Safe to call again. */
    attach: function (host, o) {
      if (!host || host.querySelector('.ml-add')) return null;
      var html = api.btnHtml(o);
      if (!html) return null;
      var wrap = document.createElement('div');
      wrap.className = 'ml-row';
      wrap.innerHTML = html;
      host.appendChild(wrap);
      paint(wrap);
      return wrap;
    },
    slug: function (s) {
      return String(s || '').toLowerCase().replace(/[‘’'`]/g, '').replace(/&/g, ' and ').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
    }
  };

  function itemFromButton(b) {
    var d = b.dataset;
    return { id: d.mlId, type: d.mlType, name: d.mlName, town: d.mlTown, address: d.mlAddress, url: d.mlUrl, detail: d.mlDetail };
  }

  /* ---- buttons on the page ---- */
  function paint(root) {
    var list = (root || document).querySelectorAll ? (root || document).querySelectorAll('.ml-add') : [];
    for (var n = 0; n < list.length; n++) {
      var b = list[n], id = b.getAttribute('data-ml-id');
      if (!id) continue;
      var on = indexOf(id) > -1;
      if (on && items[indexOf(id)].stub) api.refresh(itemFromButton(b));
      b.hidden = false;
      var pressed = on ? 'true' : 'false';
      if (b.getAttribute('aria-pressed') !== pressed) b.setAttribute('aria-pressed', pressed);
      var label = b.lastElementChild;
      var text = on ? 'On my list' : 'Add to my list';
      if (label && label.textContent !== text) label.textContent = text;
    }
  }

  /* ---- the "My list" link in the site header and menu ---- */
  function updateNav() {
    var n = items.length;
    var counts = document.querySelectorAll('.mylist-count');
    for (var i = 0; i < counts.length; i++) {
      var c = counts[i];
      c.textContent = n ? String(n) : '';
      c.hidden = !n;
      var a = c.parentNode;
      if (a && a.setAttribute) {
        if (n) a.setAttribute('aria-label', 'My list, ' + n + (n === 1 ? ' item' : ' items'));
        else a.removeAttribute('aria-label');
      }
    }
  }

  document.addEventListener('click', function (ev) {
    var t = ev.target;
    var b = t && t.closest ? t.closest('.ml-add') : null;
    if (!b || !b.getAttribute('data-ml-id')) return;
    ev.preventDefault();
    api.toggle(itemFromButton(b));
  });

  function ready() {
    updateNav();
    paint();
    if (window.MutationObserver) {
      var queued = false;
      new MutationObserver(function (recs) {
        var found = false;
        for (var i = 0; i < recs.length && !found; i++) {
          for (var j = 0; j < recs[i].addedNodes.length; j++) {
            var nd = recs[i].addedNodes[j];
            if (nd.nodeType === 1 && (nd.classList.contains('ml-add') || nd.querySelector('.ml-add'))) { found = true; break; }
          }
        }
        if (!found || queued) return;
        queued = true;
        var go = function () { queued = false; paint(); };
        if (window.requestAnimationFrame) window.requestAnimationFrame(go); else setTimeout(go, 0);
      }).observe(document.documentElement, { childList: true, subtree: true });
    }
  }

  load();
  migrate();
  window.TCCList = api;

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready); else ready();

  /* the list changed in another tab */
  window.addEventListener('storage', function (ev) {
    if (ev.key !== KEY) return;
    load();
    notify();
  });
})();
