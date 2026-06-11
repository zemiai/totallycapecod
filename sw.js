/**
 * Totally Cape Cod — Service Worker (push notifications only)
 * Served from /sw.js (repo root).
 *
 * Handles:
 *   - push: display notification from server-sent payload
 *   - notificationclick: focus existing tab or open /app/
 *   - install / activate: immediate takeover, no caching
 *
 * NO fetch handler — we must not serve stale data.
 */

// ── Install: skip waiting so the new SW activates immediately ────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting());
});

// ── Activate: claim all clients right away ───────────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// ── Push: parse payload and show notification ────────────────────────────────
self.addEventListener('push', (event) => {
  let data = {};
  if (event.data) {
    try {
      data = event.data.json();
    } catch {
      // Malformed payload — use defaults
    }
  }

  const title = data.title || 'Totally Cape Cod';
  const options = {
    body:   data.body  || '',
    icon:   '/icon-192.png',
    badge:  '/favicon-32.png',
    tag:    data.tag   || 'tcc-default',
    data:   { url: data.url || '/app/' },
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

// ── Notification click: focus existing tab or open a new one ─────────────────
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const targetUrl = (event.notification.data && event.notification.data.url)
    ? event.notification.data.url
    : '/app/';

  event.waitUntil(
    self.clients
      .matchAll({ type: 'window', includeUncontrolled: true })
      .then((clientList) => {
        // Try to focus an already-open tab whose URL starts with our origin + targetUrl
        for (const client of clientList) {
          const clientUrl = new URL(client.url);
          const target   = new URL(targetUrl, self.location.origin);
          if (clientUrl.origin === target.origin && clientUrl.pathname === target.pathname) {
            return client.focus();
          }
        }
        // No matching tab — open a new one
        return self.clients.openWindow(targetUrl);
      })
  );
});
