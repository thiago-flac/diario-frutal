/**
 * Diário de Frutal — resumo na hora sem expor a chave.
 *
 * A chave do Gemini fica aqui, no Worker, como secret da Cloudflare. O app chama
 * esta URL; a chave nunca chega ao celular de ninguém.
 *
 * Como um colega usa: ele abre o app, e o app já vem com a URL deste Worker e o
 * código de acesso configurados. Nada de chave, nada de conta no Google.
 *
 * Variáveis (Settings → Variables and secrets deste Worker):
 *   GEMINI_API_KEY  (secret)  a chave do AI Studio
 *   CODIGO          (secret)  a palavra que os colegas recebem
 *   LIMITE_DIARIO   (texto)   quantas chamadas por dia, padrão 250
 *   USO             (KV)      opcional: namespace para contar o consumo do dia
 *
 * Rota: POST /v1beta/models/<modelo>:generateContent  (mesmo formato do Google)
 */

const ORIGENS = [
  "https://thiago-flac.github.io",
  "http://127.0.0.1:8090",
  "http://localhost:8090",
];

const MODELOS = new Set([
  "gemini-3.5-flash",
  "gemini-flash-lite-latest",
  "gemini-3.1-flash-lite",
  "gemini-3.8-flash",
]);

const GOOGLE = "https://generativelanguage.googleapis.com";
const CORPO_MAX = 12_000_000; // ~12 MB: o app manda até 12 páginas em JPEG e já vi 3,8 MB

function cors(origem) {
  const ok = ORIGENS.includes(origem) || origem.endsWith(".thiago-flac.github.io");
  return {
    "Access-Control-Allow-Origin": ok ? origem : ORIGENS[0],
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "content-type, x-codigo-acesso",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

function json(dados, status, origem) {
  return new Response(JSON.stringify(dados), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...cors(origem) },
  });
}

function igual(a, b) {
  // comparação de tempo constante; o tamanho ainda vaza, e tudo bem
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

// dia no fuso de Brasília: o teto diário vira à meia-noite daqui, não às 21h
function diaLocal() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Sao_Paulo",
    year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date());
}

async function contarUso(env) {
  const limite = parseInt(env.LIMITE_DIARIO || "250", 10);
  if (!env.USO) return { excedeu: false, usados: 0, limite, contando: false };
  const dia = diaLocal();
  const chave = `uso:${dia}`;
  const usados = parseInt((await env.USO.get(chave)) || "0", 10);
  if (usados >= limite) return { excedeu: true, usados, limite, contando: true };
  await env.USO.put(chave, String(usados + 1), { expirationTtl: 172800 });
  return { excedeu: false, usados: usados + 1, limite, contando: true };
}

export default {
  async fetch(req, env) {
    const origem = req.headers.get("Origin") || "";

    if (req.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors(origem) });
    }

    const url = new URL(req.url);

    // diagnóstico: GET /status com o código mostra o consumo do dia
    if (req.method === "GET" && url.pathname === "/status") {
      if (!env.CODIGO) return json({ erro: "CODIGO não configurado no Worker" }, 500, origem);
      if (!igual(req.headers.get("x-codigo-acesso") || "", env.CODIGO)) {
        return json({ erro: "código de acesso inválido" }, 401, origem);
      }
      const limite = parseInt(env.LIMITE_DIARIO || "250", 10);
      const dia = diaLocal();
      const usados = env.USO ? parseInt((await env.USO.get(`uso:${dia}`)) || "0", 10) : 0;
      return json({ dia, usados, limite, contando: Boolean(env.USO) }, 200, origem);
    }

    // o site do diário não manda CORS; aqui o PDF passa pelo Worker para o app poder ler
    if (req.method === "GET" && url.pathname === "/pdf") {
      const alvo = url.searchParams.get("u") || "";
      if (!/^https:\/\/frutal\.publicabrasil\.net\//.test(alvo)) {
        return json({ erro: "endereço não permitido" }, 400, origem);
      }
      const r = await fetch(alvo, { redirect: "follow" });
      if (!r.ok) return json({ erro: `o site respondeu ${r.status}` }, 502, origem);
      const tipo = r.headers.get("Content-Type") || "application/pdf";
      return new Response(r.body, {
        status: 200,
        headers: {
          "Content-Type": tipo,
          "Cache-Control": "public, max-age=86400",
          "Access-Control-Allow-Origin": origem || "*",
          "Vary": "Origin",
        },
      });
    }

    if (req.method !== "POST") return json({ erro: "use POST" }, 405, origem);

    if (!env.CODIGO) return json({ erro: "CODIGO não configurado no Worker" }, 500, origem);
    if (!igual(req.headers.get("x-codigo-acesso") || "", env.CODIGO)) {
      return json({ erro: "código de acesso inválido — peça o código a quem te passou o app" }, 401, origem);
    }
    if (!env.GEMINI_API_KEY) return json({ erro: "GEMINI_API_KEY não configurada no Worker" }, 500, origem);

    const m = /^\/v1beta\/models\/([a-z0-9.\-]+):generateContent$/.exec(url.pathname);
    if (!m) return json({ erro: "rota não suportada" }, 404, origem);
    if (!MODELOS.has(m[1])) return json({ erro: `modelo ${m[1]} não permitido` }, 400, origem);

    const corpo = await req.text();
    if (!corpo) return json({ erro: "corpo vazio" }, 400, origem);
    if (corpo.length > CORPO_MAX) return json({ erro: `documento grande demais (${corpo.length} bytes); o limite é ${CORPO_MAX}` }, 413, origem);

    const uso = await contarUso(env);
    if (uso.excedeu) {
      return json(
        { erro: "limite diário de resumos atingido", usados: uso.usados, limite: uso.limite },
        429,
        origem,
      );
    }

    let resposta;
    try {
      resposta = await fetch(`${GOOGLE}/v1beta/models/${m[1]}:generateContent`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-goog-api-key": env.GEMINI_API_KEY },
        body: corpo,
      });
    } catch (e) {
      return json({ erro: "falha ao falar com o Google", detalhe: String(e) }, 502, origem);
    }

    const texto = await resposta.text();
    return new Response(texto, {
      status: resposta.status,
      headers: {
        "Content-Type": resposta.headers.get("Content-Type") || "application/json",
        "X-Uso-Dia": `${uso.usados}/${uso.limite}`,
        ...cors(origem),
      },
    });
  },
};
