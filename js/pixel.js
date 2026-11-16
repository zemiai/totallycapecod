/* Meta Pixel + Google tag — site-wide deferred loader.
   Pages keep tiny inline stubs (window.dataLayer / gtag() for Google; the fbq queue below for
   Meta) so every call made before the real scripts arrive is queued in order and replayed by
   them. The real scripts (gtag.js and fbevents.js) are injected once, on the first user
   interaction (pointerdown, keydown, scroll, touchstart) or after 5 seconds, whichever
   comes first.
   Empty PIXEL_ID = no Meta pixel. Google loads only on pages whose inline stub created
   window.dataLayer, and is skipped if the page still has its own gtag.js tag.
   The app additionally mirrors funnel events (InitiateCheckout, Purchase, etc.)
   through its tccT() wrapper. */
(function () {
  var PIXEL_ID = '2064543030941405';
  var GA_ID = 'G-Q0YM9WQLWK';
  var FB_SRC = 'https://connect.facebook.net/en_US/fbevents.js';
  var GA_SRC = 'https://www.googletagmanager.com/gtag/js?id=' + GA_ID;
  var DELAY_MS = 5000;

  // Meta stub: same queue as Meta's snippet, minus the script injection (done in load()).
  if (PIXEL_ID) {
    !function (f, n) {
      if (f.fbq) return; n = f.fbq = function () {
        n.callMethod ? n.callMethod.apply(n, arguments) : n.queue.push(arguments);
      };
      if (!f._fbq) f._fbq = n; n.push = n; n.loaded = !0; n.version = '2.0';
      n.queue = [];
    }(window);
    fbq('init', PIXEL_ID);
    fbq('track', 'PageView');
  }

  var started = false, timer;
  var EVENTS = ['pointerdown', 'keydown', 'scroll', 'touchstart'];

  function has(part) {
    var s = document.getElementsByTagName('script');
    for (var i = 0; i < s.length; i++) if ((s[i].src || '').indexOf(part) !== -1) return true;
    return false;
  }
  function inject(src) {
    var t = document.createElement('script');
    t.async = true; t.src = src;
    var first = document.getElementsByTagName('script')[0];
    (first && first.parentNode ? first.parentNode : document.head).insertBefore(t, first || null);
  }
  function load() {
    if (started) return;
    started = true;
    clearTimeout(timer);
    for (var i = 0; i < EVENTS.length; i++) window.removeEventListener(EVENTS[i], load, true);
    if (window.dataLayer && !has('googletagmanager.com/gtag/js')) inject(GA_SRC);
    if (PIXEL_ID && !has('connect.facebook.net/en_US/fbevents.js')) inject(FB_SRC);
  }

  for (var i = 0; i < EVENTS.length; i++) window.addEventListener(EVENTS[i], load, { capture: true, passive: true });
  timer = setTimeout(load, DELAY_MS);
})();
