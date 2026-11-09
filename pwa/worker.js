// Cloudflare Worker: 15 linhas para resolver o CORS do PDF.
// O site da prefeitura serve o PDF sem cabeçalho de CORS, então o navegador não
// pode baixá-lo. Este Worker busca e devolve com o cabeçalho liberado.
//
// Publicar: dash.cloudflare.com → Workers → Create → colar → Deploy.
// No app, em Ajustes, informe:  https://SEU-WORKER.workers.dev/?u={url}
export default {
  async fetch(pedido) {
    const alvo = new URL(pedido.url).searchParams.get("u");
    if (!alvo) return new Response("uso: ?u=<url do pdf>", { status: 400 });
    if (!/^https:\/\/frutal\.publicabrasil\.net\//.test(alvo))
      return new Response("domínio não permitido", { status: 403 });

    const r = await fetch(alvo, { headers: { "User-Agent": "DiarioFrutalPWA/1.0" } });
    const copia = new Response(r.body, r);
    copia.headers.set("Access-Control-Allow-Origin", "*");
    copia.headers.set("Cache-Control", "public, max-age=86400");
    return copia;
  },
};
