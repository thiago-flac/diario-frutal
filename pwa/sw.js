// Casca do app em cache: abre mesmo sem rede. O conteúdo (edições, resumos) vive
// no IndexedDB, não aqui.
const CASCA = "diario-pwa-v5";
const ARQUIVOS = ["./", "index.html", "styles.css", "fontes.css", "app.js", "manifest.json",
                  "icone-192.png", "icone-512.png", "icone-180.png",
                  "fontes/ebgaramond-var-lat.woff2", "fontes/crimsontext-400-lat.woff2",
                  "fontes/crimsontext-600-lat.woff2", "fontes/crimsontext-400-i-lat.woff2"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CASCA).then((c) => c.addAll(ARQUIVOS)).then(() => self.skipWaiting()));
});

// O app avisa quando encontrou versão nova: assume já, sem esperar a aba fechar.
self.addEventListener("message", (e) => {
  if (e.data && e.data.tipo === "assumir") self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((ks) => Promise.all(ks.filter((k) => k !== CASCA).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  // API da prefeitura e Gemini sempre vão na rede.
  if (url.hostname.includes("publicabrasil") || url.hostname.includes("googleapis")) return;

  // dados/ muda todo dia: rede primeiro, cache só como reserva.
  if (url.origin === location.origin && url.pathname.includes("/dados/")) {
    e.respondWith(fetch(e.request).then((resp) => {
      const copia = resp.clone();
      caches.open(CASCA).then((c) => c.put(e.request, copia));
      return resp;
    }).catch(() => caches.match(e.request)));
    return;
  }

  // a casca também é rede-primeiro: assim atualização do app chega no próximo
  // abrir, e o cache só entra quando não há rede.
  if (url.origin === location.origin) {
    e.respondWith(fetch(e.request).then((resp) => {
      const copia = resp.clone();
      caches.open(CASCA).then((c) => c.put(e.request, copia));
      return resp;
    }).catch(() => caches.match(e.request).then((r) => r || caches.match("index.html"))));
  }
});
