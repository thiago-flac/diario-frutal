// Diário de Frutal — PWA sem servidor.
// Lista as edições pela API do site da prefeitura (que libera CORS), guarda tudo
// no IndexedDB do aparelho e resume no próprio celular chamando o Gemini.

const API = "https://frutal.publicabrasil.net/wp-json/wp/v2/lsvr_document";
const CAMPOS = "id,date,title,content,link";
const MODELOS = ["gemini-3.5-flash", "gemini-flash-lite-latest", "gemini-3.1-flash-lite"];
const MAX_IMAGENS = 12;          // páginas escaneadas por requisição
const MIN_TEXTO_UTIL = 220;      // abaixo disso a página é tratada como imagem
const LARGURA_PAGINA = 1400;     // px; o suficiente para o OCR do modelo ler

const $ = (s) => document.querySelector(s);
const app = $("#app");
const aviso = $("#aviso");

// ---------------------------------------------------------------- configuração
const cfg = {
  get(chave, padrao = "") {
    const v = localStorage.getItem("diario." + chave);
    return v === null ? padrao : v;
  },
  set(chave, valor) {
    localStorage.setItem("diario." + chave, valor);
  },
};
const chaveGemini = () => cfg.get("chave").trim();
const proxy = () => cfg.get("proxy").trim();

let telaAvisoTimer;
function avisar(msg, ms = 4000) {
  aviso.textContent = String(msg).slice(0, 180);
  aviso.hidden = false;
  clearTimeout(telaAvisoTimer);
  telaAvisoTimer = setTimeout(() => (aviso.hidden = true), ms);
}

// ------------------------------------------------------------------ IndexedDB
function abrirBanco() {
  return new Promise((ok, erro) => {
    const req = indexedDB.open("diario-frutal", 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains("edicoes")) db.createObjectStore("edicoes", { keyPath: "numero" });
      if (!db.objectStoreNames.contains("paginas")) db.createObjectStore("paginas", { keyPath: "id" });
      if (!db.objectStoreNames.contains("resumos")) db.createObjectStore("resumos", { keyPath: "numero" });
    };
    req.onsuccess = () => ok(req.result);
    req.onerror = () => erro(req.error);
  });
}

async function guardar(store, itens) {
  const db = await abrirBanco();
  return new Promise((ok, erro) => {
    const tx = db.transaction(store, "readwrite");
    for (const it of [].concat(itens)) tx.objectStore(store).put(it);
    tx.oncomplete = () => ok();
    tx.onerror = () => erro(tx.error);
  });
}

async function ler(store, chave) {
  const db = await abrirBanco();
  return new Promise((ok, erro) => {
    const req = (chave === undefined)
      ? db.transaction(store).objectStore(store).getAll()
      : db.transaction(store).objectStore(store).get(chave);
    req.onsuccess = () => ok(req.result);
    req.onerror = () => erro(req.error);
  });
}

// ---------------------------------------------------------------- coleta (API)
function numeroDoTitulo(titulo) {
  const m = /(?:EDI[ÇC][ÃA]O|EDICAO)\s*0*(\d+)/i.exec(titulo || "");
  return m ? parseInt(m[1], 10) : null;
}

function limparHtml(txt) {
  const d = document.createElement("div");
  d.innerHTML = txt || "";
  return d.textContent.trim();
}

function linkDoArquivo(html) {
  const m = /href="([^"]+\.(?:pdf|docx?|odt))"/i.exec(html || "");
  return m ? m[1] : null;
}

async function sincronizar(progresso, maxPaginas = 6) {
  const edicoes = [];
  for (let pagina = 1; pagina <= maxPaginas; pagina++) {
    const r = await fetch(`${API}?per_page=100&page=${pagina}&orderby=date&order=desc&_fields=${CAMPOS}`);
    if (r.status === 400 || r.status === 404) break;   // passou da última página
    if (!r.ok) throw new Error("A API respondeu " + r.status);
    const posts = await r.json();
    if (!Array.isArray(posts) || !posts.length) break;
    progresso?.(edicoes.length + posts.length);
    for (const p of posts) {
    const numero = numeroDoTitulo(limparHtml(p.title?.rendered));
    if (!numero) continue;
      edicoes.push({
        numero,
        data: (p.date || "").slice(0, 10),
        titulo: limparHtml(p.title?.rendered),
        arquivo: linkDoArquivo(p.content?.rendered),
        post: p.id,
      });
    }
    if (posts.length < 100) break;
  }
  await guardar("edicoes", edicoes);
  return edicoes;
}

function guardarRetrato(edicoes, resumos) {
  try {
    localStorage.setItem("diario.retrato", JSON.stringify({
      quando: Date.now(),
      edicoes: edicoes.slice(0, 60),
      resumos: (resumos || []).slice(0, 60),
    }));
  } catch (e) { /* cota do navegador cheia: o retrato é só conveniência */ }
}

function lerRetrato() {
  try { return JSON.parse(localStorage.getItem("diario.retrato") || "null"); }
  catch (e) { return null; }
}

async function todasAsEdicoes() {
  const locais = await ler("edicoes");
  return (locais || []).sort((a, b) => b.numero - a.numero);
}

// ------------------------------------------------------------------- utilidade
const dataBR = (iso) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : "—");
const escapar = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ------------------------------------------------- resumos gerados no GitHub
// O robô do repositório (GitHub Actions) resume as edições novas e commita
// pwa/dados/resumos.json. O app só lê; quem baixar o app vê o resumo pronto,
// sem chave e sem proxy.
async function importarResumosProntos() {
  try {
    const r = await fetch("dados/resumos.json", { cache: "no-cache" });
    if (!r.ok) return 0;
    const lista = await r.json();
    if (!Array.isArray(lista) || !lista.length) return 0;

    const locais = await ler("resumos");
    const mapa = new Map((locais || []).map((x) => [x.numero, x]));
    const vindos = [];
    for (const item of lista) {
      const atual = mapa.get(item.numero);
      if (atual && atual.fonte !== "github") continue;   // resumo feito no aparelho manda
      vindos.push({ ...item, fonte: "github" });
    }
    if (vindos.length) await guardar("resumos", vindos);
    return vindos.length;
  } catch (e) {
    return 0;
  }
}

// O texto de cada página vem em dados/textos/<numero>.txt. É o que devolve
// a busca em edições resumidas pelo robô (inclusive as que passaram por OCR).
async function garantirTextos(limite = 40) {
  const resumos = await ler("resumos");
  const paginas = await ler("paginas");
  const comTexto = new Set((paginas || []).map((p) => p.numero));
  const faltando = (resumos || [])
    .filter((r) => r.fonte === "github" && !comTexto.has(r.numero))
    .sort((a, b) => b.numero - a.numero)
    .slice(0, limite);

  for (const r of faltando) {
    try {
      const resp = await fetch(`dados/textos/${r.numero}.txt`);
      if (!resp.ok) continue;
      const itens = [];
      const re = /\[PAGINA (\d+)\]\s*([\s\S]*?)(?=\[PAGINA |$)/g;
      let m;
      const txt = await resp.text();
      while ((m = re.exec(txt)) !== null) {
        const corpo = m[2].trim();
        if (corpo) itens.push({ id: `${r.numero}-${m[1]}`, numero: r.numero, n: +m[1], texto: corpo, ocr: 0, fonte: "github" });
      }
      if (itens.length) await guardar("paginas", itens);
    } catch (e) { /* arquivo ausente: segue sem ele */ }
  }
  return faltando.length;
}

// ------------------------------------------------------------------ telas
async function telaLista() {
  marcarNav("lista");
  const edicoes = await todasAsEdicoes();
  const resumos = await ler("resumos");
  guardarRetrato(edicoes, resumos);
  pintarLista(edicoes, resumos);
}

function pintarLista(edicoes, resumos) {
  const mapa = new Map((resumos || []).map((r) => [r.numero, r]));
  const vistoAte = parseInt(cfg.get("vistoAte", "0"), 10);

  if (!edicoes.length) {
    app.innerHTML = `<p class="vazio">Nada guardado ainda. Toque em <b>Atualizar</b> para buscar as edições no site da prefeitura.</p>
      <button class="botao primario" id="btn-atualizar">Atualizar agora</button>`;
    $("#btn-atualizar").onclick = () => atualizarComAviso();
    return;
  }

  const primeiraVez = !vistoAte;
  const novas = primeiraVez ? 0 : edicoes.filter((e) => e.numero > vistoAte).length;
  app.innerHTML = `
    <h1>Edições</h1>
    <p class="meta">${edicoes.length} guardadas · ${mapa.size} resumidas${novas ? ` · <span style="color:var(--accent);font-weight:600">${novas} nova(s)</span>` : ""}</p>
    <div id="lista">${edicoes.map((e) => cartao(e, mapa.get(e.numero), !primeiraVez && e.numero > vistoAte)).join("")}</div>
    <div class="barra"><button class="botao" id="btn-atualizar">Atualizar</button></div>`;

  $("#btn-atualizar").onclick = () => atualizarComAviso();
  cfg.set("vistoAte", String(Math.max(...edicoes.map((e) => e.numero))));
}

function cartao(ed, resumo, nova) {
  const prazo = resumo?.prazo ? `<div class="prazo"><b>prazo</b>${escapar(resumo.prazo)}</div>` : "";
  const corpo = resumo?.resumo
    ? `<p class="resumo-curto">${escapar(resumo.resumo)}</p>${prazo}`
    : `<p class="meta" style="margin-top:8px">toque para abrir ou resumir</p>`;
  return `<article class="card">
    <div class="meta">
      ${nova ? '<span class="tag nova">nova</span>' : ""}
      ${resumo?.resumo ? '<span class="tag resumo">resumida</span>' : ""}
      <span>${dataBR(ed.data)}</span>
    </div>
    <h3><a href="#/edicao/${ed.numero}">Edição ${ed.numero}</a></h3>
    ${corpo}
  </article>`;
}

async function telaEdicao(numero) {
  marcarNav("lista");
  const edicoes = await todasAsEdicoes();
  const ed = edicoes.find((e) => e.numero === numero);
  if (!ed) {
    app.innerHTML = `<p class="vazio">Edição ${numero} não está guardada. Atualize a lista.</p>`;
    return;
  }
  const resumo = await ler("resumos", numero);
  const paginas = (await ler("paginas"))
    .filter((p) => p.numero === numero && (p.texto || "").trim().length > 0)
    .sort((a, b) => a.n - b.n);

  app.innerHTML = `
    <p class="meta"><span>${dataBR(ed.data)}</span>${paginas.length ? ` · ${paginas.length} páginas` : ""}</p>
    <h1>Edição ${ed.numero}</h1>
    ${ed.arquivo
      ? `<div class="linha-botoes"><a class="botao primario" href="${escapar(ed.arquivo)}" target="_blank" rel="noopener">Abrir PDF</a></div>`
      : `<p class="meta">esta edição não tem arquivo publicado</p>`}
    ${resumo ? blocoResumo(resumo) : `<p class="vazio">Sem resumo neste aparelho.</p>`}
    <div class="linha-botoes">
      <button class="botao" id="btn-resumir">${resumo ? "Gerar de novo" : "Resumir agora"}</button>
    </div>
    <p class="ajuda" id="progresso"></p>
    ${paginas.length ? `<h2>Texto extraído</h2><div class="lista-paginas">${paginas
      .map((p) => `<details class="pagina"><summary>página ${p.n}${p.ocr ? " · OCR" : ""} · ${p.texto.length} caracteres</summary><pre>${escapar(p.texto)}</pre></details>`)
      .join("")}</div>` : ""}
    <p class="rodape">Fonte oficial: <a href="https://frutal.publicabrasil.net/" target="_blank" rel="noopener">Diário Oficial de Frutal/MG</a>. Resumo automático — confira o PDF.</p>`;

  $("#btn-resumir").onclick = () => resumirEdicao(ed);
}

function blocoResumo(r) {
  const destaques = (r.destaques || []).map((d) => `
    <div class="destaque">
      <h4>${escapar(d.titulo)}</h4>
      <p>${escapar(d.texto)}</p>
      <small>página ${d.pagina || "?"}${d.categoria ? " · " + escapar(d.categoria) : ""}</small>
    </div>`).join("");
  const chips = (r.orgaos || []).map((o) => `<span class="chip">${escapar(o)}</span>`).join("");
  return `<h2>Resumo</h2>
    <p style="font-size:15.5px">${escapar(r.resumo)}</p>
    <p class="meta">${escapar(r.tipo || "")}${r.relevancia != null ? ` · relevância ${r.relevancia}/3` : ""}${r.fonte === "github" ? " · gerado pelo robô do acervo" : ""}</p>
    ${chips ? `<div class="chips">${chips}</div>` : ""}
    ${r.prazo ? `<div class="prazo"><b>prazo</b>${escapar(r.prazo)}</div>` : ""}
    ${destaques ? `<h2>O que saiu</h2>${destaques}` : ""}`;
}

async function telaBusca(termo) {
  marcarNav("busca");
  const alvo = (termo || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  const edicoes = await todasAsEdicoes();
  const mapa = new Map(edicoes.map((e) => [e.numero, e]));
  const faltavam = await garantirTextos(alvo.length >= 2 ? 40 : 0);
  if (faltavam) { await telaBusca(termo); return; }
  const paginas = await ler("paginas");
  const achados = [];

  if (alvo.length >= 2) {
    for (const p of paginas) {
      const texto = (p.texto || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
      const i = texto.indexOf(alvo);
      if (i >= 0) achados.push({ ...p, trecho: p.texto.slice(Math.max(0, i - 70), i + 110) });
    }
  }

  app.innerHTML = `
    <h1>Busca</h1>
    <p class="meta">${paginas.length} páginas já baixadas e guardadas no aparelho</p>
    <input type="search" id="q" placeholder="licitação, saúde, decreto…" value="${escapar(termo || "")}">
    <div id="resultados">${alvo.length < 2 ? `<p class="vazio">Digite ao menos duas letras.</p>`
      : achados.length ? achados.slice(0, 40).map((a) => `
        <article class="card">
          <div class="meta"><span>Edição ${a.numero}</span><span>página ${a.n}</span></div>
          <p style="margin:8px 0 0;font-size:14.5px">…${escapar(a.trecho)}…</p>
          <p class="meta" style="margin-top:8px"><a href="#/edicao/${a.numero}">abrir edição</a></p>
        </article>`).join("")
        : `<p class="vazio">Nada encontrado.</p>`}</div>
    <p class="rodape">A busca cobre só o que já foi baixado neste aparelho — o texto é extraído quando você abre uma edição e pede o resumo.</p>`;

  const campo = $("#q");
  campo.oninput = debounce(() => telaBusca(campo.value), 350);
  campo.focus();
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

async function telaAjustes() {
  marcarNav("ajustes");
  const edicoes = await todasAsEdicoes();
  app.innerHTML = `
    <h1>Ajustes</h1>
    <p class="meta">${edicoes.length} edições guardadas neste aparelho</p>

    <label for="chave">Chave do Gemini</label>
    <input type="password" id="chave" placeholder="AIza… ou AQ.…" value="${escapar(cfg.get("chave"))}">
    <p class="ajuda">Grátis no <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">Google AI Studio</a>.
      Fica só no seu aparelho. Sem ela o app lista as edições e abre o PDF, mas não resume.</p>

    <label for="proxy">Endereço do proxy (opcional)</label>
    <input type="url" id="proxy" placeholder="https://seu-worker.workers.dev/?u={url}" value="${escapar(cfg.get("proxy"))}">
    <p class="ajuda">O site da prefeitura não deixa o navegador baixar o PDF direto (falta CORS).
      Com um proxy de 15 linhas — o arquivo <code>worker.js</code> que veio junto — o app baixa e resume.
      Sem proxy, dá para resumir escolhendo o PDF já baixado no aparelho.</p>

    <label for="arquivo">Resumir um PDF do aparelho</label>
    <input type="file" id="arquivo" accept="application/pdf">
    <p class="ajuda">Baixe o PDF pelo botão “Abrir PDF” e escolha aqui: o texto e o resumo ficam guardados.</p>

    <div class="linha-botoes"><button class="botao" id="btn-salvar">Salvar</button></div>
    <div class="linha-botoes"><button class="botao" id="btn-limpar">Apagar tudo do aparelho</button></div>
    <p class="rodape">Diário de Frutal · app instalável, funciona offline para o que já foi baixado.</p>`;

  $("#btn-salvar").onclick = () => {
    cfg.set("chave", $("#chave").value.trim());
    cfg.set("proxy", $("#proxy").value.trim());
    avisar("Ajustes salvos.");
    telaAjustes();
  };
  $("#btn-limpar").onclick = async () => {
    if (!confirm("Apagar edições, resumos e textos deste aparelho?")) return;
    indexedDB.deleteDatabase("diario-frutal");
    localStorage.clear();
    avisar("Apagado.");
    setTimeout(() => location.reload(), 600);
  };
  $("#arquivo").onchange = async (ev) => {
    const f = ev.target.files?.[0];
    if (!f) return;
    const numero = parseInt(prompt("Número da edição deste PDF?") || "0", 10);
    if (!numero) return;
    await guardar("edicoes", { numero, data: "", titulo: `Edição ${numero}`, arquivo: "", post: null });
    await processarPdf(new Uint8Array(await f.arrayBuffer()), numero);
  };
}

// -------------------------------------------------------------- resumo no app
async function resumirEdicao(ed) {
  const progresso = $("#progresso");
  const dizer = (t) => { if (progresso) progresso.textContent = t; };
  try {
    if (!chaveGemini()) { avisar("Falta a chave do Gemini em Ajustes."); return; }
    let bytes;

    if (proxy()) {
      dizer("baixando o PDF…");
      const alvo = proxy().replace("{url}", encodeURIComponent(ed.arquivo));
      const r = await fetch(alvo);
      if (!r.ok) throw new Error("proxy respondeu " + r.status);
      bytes = new Uint8Array(await r.arrayBuffer());
    } else {
      avisar("Sem proxy configurado. Baixe o PDF e use “Resumir um PDF do aparelho”.", 6000);
      return;
    }
    await processarPdf(bytes, ed.numero, dizer);
    avisar("Resumo pronto.");
    telaEdicao(ed.numero);
  } catch (e) {
    dizer("");
    avisar("Deu erro: " + e.message, 6000);
  }
}

// Cabeçalho, rodapé e assinatura digital aparecem em toda página e somam ~300
// caracteres de texto inútil. Sem tirar isso, uma página escaneada passaria como
// "já tem texto" e o modelo receberia só o brasão.
const LIXO = [
  /prefeitura de frutal[\s\S]{0,40}?di[aá]rio oficial eletr[oô]nico/gi,
  /vers[aã]o eletr[oô]nica dispon[ií]vel[^\n]{0,120}/gi,
  /documento assinado digitalmente[^\n]{0,200}/gi,
  /frutal\/mg,\s*\d{1,2} de [a-zç]+ de \d{4}[^\n]{0,80}/gi,
  /ano\s+[ivxlc]+\s*\|\s*n[º°]\s*\d+/gi,
  /www\.frutal\.mg\.gov\.br/gi,
];

function textoUtil(t) {
  let s = t;
  for (const r of LIXO) s = s.replace(r, " ");
  s = s.replace(/\s+/g, " ").trim();
  // página que virou só pontuação/números depois da limpeza não conta
  return s.replace(/[\s\d.,;:/()\-–—|°ºª]/g, "").length >= 40 ? s : "";
}

async function carregarPdfjs() {
  const pdfjs = await import("https://cdn.jsdelivr.net/npm/pdfjs-dist@4.10.38/build/pdf.min.mjs");
  pdfjs.GlobalWorkerOptions.workerSrc = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.10.38/build/pdf.worker.min.mjs";
  return pdfjs;
}

async function processarPdf(bytes, numero, dizer = () => {}) {
  const pdfjs = await carregarPdfjs();
  dizer("abrindo o documento…");
  const doc = await pdfjs.getDocument({ data: bytes }).promise;
  const paginas = [];
  const imagens = [];

  for (let n = 1; n <= doc.numPages; n++) {
    dizer(`lendo página ${n}/${doc.numPages}…`);
    const page = await doc.getPage(n);
    const conteudo = await page.getTextContent();
    const texto = conteudo.items.map((i) => i.str).join(" ").replace(/\s+/g, " ").trim();

    const util = textoUtil(texto);
    if (util.length > MIN_TEXTO_UTIL) {
      paginas.push({ id: `${numero}-${n}`, numero, n, texto: util, ocr: 0 });
    } else {
      const jpeg = await renderizar(page);
      imagens.push({ n, jpeg });
      paginas.push({ id: `${numero}-${n}`, numero, n, texto: "", ocr: 1 });
    }
  }
  await guardar("paginas", paginas);

  dizer("pedindo o resumo ao modelo…");
  const resumo = await pedirResumo(paginas, imagens);
  resumo.numero = numero;
  resumo.criado = new Date().toISOString();
  await guardar("resumos", resumo);
  dizer("");
  return resumo;
}

async function renderizar(page) {
  const escala = LARGURA_PAGINA / page.getViewport({ scale: 1 }).width;
  const vp = page.getViewport({ scale: escala });
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(vp.width);
  canvas.height = Math.round(vp.height);
  await page.render({ canvasContext: canvas.getContext("2d"), viewport: vp }).promise;
  const dataUrl = canvas.toDataURL("image/jpeg", 0.72);
  return dataUrl.split(",")[1];       // base64 puro
}

const ESQUEMA = {
  type: "object",
  properties: {
    resumo: { type: "string" },
    tipo: { type: "string" },
    prazo: { type: "string" },
    relevancia: { type: "integer" },
    orgaos: { type: "array", items: { type: "string" } },
    destaques: {
      type: "array",
      items: {
        type: "object",
        properties: {
          titulo: { type: "string" },
          texto: { type: "string" },
          pagina: { type: "integer" },
          categoria: { type: "string" },
        },
        required: ["titulo", "texto"],
      },
    },
  },
  required: ["resumo", "destaques"],
};

function instrucao(total, escaneadas) {
  return `Você é um leitor experiente de diários oficiais municipais brasileiros.
Leia o conteúdo do Diário Oficial Eletrônico da Prefeitura de Frutal/MG (${total} páginas;
${escaneadas} delas são imagem e vêm em anexo como foto).

Devolva JSON com:
- resumo: 2 a 4 frases, em português claro, dizendo o que a edição trata de mais importante;
- tipo: "licitação", "decreto", "portaria", "edital", "pessoal", "orçamento", "misto"…
- prazo: a data limite mais relevante citada (formato dd/mm/aaaa), ou "" se não houver;
- relevancia: 0 a 3 (3 = muda a vida do cidadão ou de um servidor agora);
- orgaos: secretarias/órgãos citados;
- destaques: até 8 objetos {titulo, texto (1-2 frases), pagina, categoria}. Título curto e concreto,
  nada de "informações gerais". Se um ato tiver prazo próprio, diga no texto.

Nunca invente. Se um trecho estiver ilegível, ignore-o. Responda em português do Brasil.`;
}

async function pedirResumo(paginas, imagens) {
  const blocosTexto = paginas
    .filter((p) => p.texto)
    .map((p) => `[PAGINA ${p.n}]\n${p.texto}`)
    .join("\n\n");

  const partes = [{ text: instrucao(paginas.length, imagens.length) }];
  if (blocosTexto) partes.push({ text: "TEXTO EXTRAÍDO:\n\n" + blocosTexto.slice(0, 220000) });
  for (const img of imagens.slice(0, MAX_IMAGENS)) {
    partes.push({ text: `PÁGINA ${img.n} (imagem):` });
    partes.push({ inline_data: { mime_type: "image/jpeg", data: img.jpeg } });
  }
  if (imagens.length > MAX_IMAGENS) {
    partes.push({ text: `(as ${imagens.length - MAX_IMAGENS} últimas páginas em imagem foram omitidas)` });
  }
  return chamarGemini(partes);
}

async function chamarGemini(partes) {
  let ultimoErro;
  for (const modelo of MODELOS) {
    try {
      const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${modelo}:generateContent`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-goog-api-key": chaveGemini() },
        body: JSON.stringify({
          contents: [{ role: "user", parts: partes }],
          generationConfig: { temperature: 0.2, responseMimeType: "application/json", responseSchema: ESQUEMA },
        }),
      });
      if (!r.ok) { ultimoErro = new Error(`${modelo}: HTTP ${r.status}`); continue; }
      const dados = await r.json();
      const texto = dados.candidates?.[0]?.content?.parts?.map((p) => p.text).join("") || "";
      const json = JSON.parse(texto.replace(/^```(?:json)?|```$/g, "").trim());
      if (!json.resumo) throw new Error("resumo vazio");
      json.modelo = modelo;
      return json;
    } catch (e) {
      ultimoErro = e;
    }
  }
  throw ultimoErro || new Error("nenhum modelo respondeu");
}

// ---------------------------------------------------------------- navegação
async function atualizarComAviso() {
  avisar("buscando as edições no site…", 8000);
  try {
    const edicoes = await sincronizar((n) => avisar(`conferindo… ${n} edições`), 8);
    avisar(`${edicoes.length} edições conferidas.`);
    await rotear();
  } catch (e) {
    avisar("Não consegui falar com o site: " + e.message, 6000);
  }
}

function marcarNav(qual) {
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("on", a.dataset.nav === qual));
}

async function rotear() {
  const hash = location.hash.replace(/^#\/?/, "");
  const [rota, param] = hash.split("/");
  try {
    if (rota === "edicao" && param) return await telaEdicao(parseInt(param, 10));
    if (rota === "busca") return await telaBusca(decodeURIComponent(location.hash.split("?q=")[1] || ""));
    if (rota === "ajustes") return await telaAjustes();
    return await telaLista();
  } catch (e) {
    app.innerHTML = `<p class="vazio">Algo falhou: ${escapar(e.message)}</p>`;
  }
}

// pinta o último retrato na hora, sem esperar IndexedDB nem rede
(function pintarRetrato() {
  if (location.hash && !location.hash.startsWith("#/")) return;
  if (location.hash.startsWith("#/edicao") || location.hash.startsWith("#/ajustes")) return;
  const r = lerRetrato();
  if (r && r.edicoes?.length) pintarLista(r.edicoes, r.resumos);
})();

window.addEventListener("hashchange", rotear);
window.addEventListener("DOMContentLoaded", async () => {
  await rotear();
  const importados = await importarResumosProntos();
  if (importados) await rotear();
  if (!(await todasAsEdicoes()).length) atualizarComAviso();
  if ("serviceWorker" in navigator && window.isSecureContext) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
});
