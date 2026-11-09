// Service worker do Diário de Frutal.
// Objetivo: abrir instantâneo, e não morrer com a tela branca quando o celular
// perde o sinal do servidor (a rede local cai, o notebook dorme, essas coisas).
const CASCA = "diario-casca-v1";
const ARQUIVOS = [
  "/static/style.css",
  "/static/icone-192.png",
  "/static/icone-512.png",
  "/manifest.webmanifest",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CASCA).then((c) => c.addAll(ARQUIVOS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((chaves) =>
      Promise.all(chaves.filter((k) => k !== CASCA).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  // PDF, API e painel sempre vão na rede: dado vivo não pode vir de cache.
  if (url.pathname.startsWith("/pdf") || url.pathname.startsWith("/api")) return;

  if (ARQUIVOS.includes(url.pathname)) {
    // estático: cache primeiro
    e.respondWith(
      caches.match(e.request).then((r) => r || fetch(e.request).then((resp) => {
        const copia = resp.clone();
        caches.open(CASCA).then((c) => c.put(e.request, copia));
        return resp;
      }))
    );
    return;
  }

  // páginas: rede primeiro, cache como rede de segurança
  e.respondWith(
    fetch(e.request)
      .then((resp) => {
        const copia = resp.clone();
        caches.open(CASCA).then((c) => c.put(e.request, copia));
        return resp;
      })
      .catch(() => caches.match(e.request).then((r) => r || caches.match("/")))
  );
});
