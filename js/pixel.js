/* Meta Pixel — site-wide loader.
   To activate: paste the Pixel ID from Events Manager (business.facebook.com/events_manager)
   into PIXEL_ID below. Empty ID = this file safely does nothing.
   The app additionally mirrors funnel events (InitiateCheckout, Purchase, etc.)
   through its tccT() wrapper. */
(function () {
  var PIXEL_ID = '2064543030941405';
  if (!PIXEL_ID) return;
  !function (f, b, e, v, n, t, s) {
    if (f.fbq) return; n = f.fbq = function () {
      n.callMethod ? n.callMethod.apply(n, arguments) : n.queue.push(arguments);
    };
    if (!f._fbq) f._fbq = n; n.push = n; n.loaded = !0; n.version = '2.0';
    n.queue = []; t = b.createElement(e); t.async = !0;
    t.src = v; s = b.getElementsByTagName(e)[0];
    s.parentNode.insertBefore(t, s);
  }(window, document, 'script', 'https://connect.facebook.net/en_US/fbevents.js');
  fbq('init', PIXEL_ID);
  fbq('track', 'PageView');
})();
