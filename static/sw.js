// A.P.O.L.O. Service Worker — PWA offline + cache
const CACHE = 'apolo-v5';
const STATIC = [
  '/',
  '/apolo-icon.svg',
  '/manifest.json',
  'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css',
  'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js',
  'https://cdn.jsdelivr.net/npm/marked/marked.min.js',
  'https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(STATIC)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // SSE e API de streaming — sempre rede, nunca cachear
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(
      fetch(e.request).catch(() =>
        new Response(JSON.stringify({ error: 'offline' }), {
          headers: { 'Content-Type': 'application/json' }
        })
      )
    );
    return;
  }

  // Código do próprio app (HTML + nosso JS/CSS) — network-first: o app é
  // atualizado com frequência e cache-first mostrava a UI/código VELHOS depois
  // de cada update. Desde que o JS/CSS saiu para arquivos externos (Épico 1.2),
  // eles precisam do mesmo tratamento que o HTML — senão o SW serve app.js
  // desatualizado para sempre. O servidor é local (latência ~0), então buscar da
  // rede não custa nada; o cache vira só o fallback offline.
  const sameOrigin = url.origin === self.location.origin;
  const isAppCode = sameOrigin && (url.pathname.endsWith('.js') || url.pathname.endsWith('.css'));
  if (e.request.mode === 'navigate' || url.pathname === '/' ||
      url.pathname.endsWith('.html') || isAppCode) {
    e.respondWith(
      fetch(e.request).then(res => {
        if (res.ok) {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return res;
      }).catch(() => caches.match(e.request).then(c => c || caches.match('/')))
    );
    return;
  }

  // Assets estáticos — cache-first
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request).then(res => {
        // Cacheia apenas respostas OK de origens permitidas
        if (res.ok && (url.origin === self.location.origin ||
            url.hostname.includes('cloudflare') ||
            url.hostname.includes('jsdelivr'))) {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return res;
      }).catch(() => {
        // Offline fallback para navegação
        if (e.request.mode === 'navigate') {
          return caches.match('/');
        }
      });
    })
  );
});
