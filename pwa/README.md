# Diário de Frutal — PWA

App de celular que mostra as edições do Diário Oficial de Frutal/MG e resume cada
uma. **Não tem servidor**: é um site estático que você instala na tela inicial, e o
trabalho de baixar, ler e resumir acontece no próprio aparelho.

Funciona em Android e iPhone. Offline para tudo o que já foi baixado.

## Instalar

1. Hospede a pasta em qualquer lugar com HTTPS. O caminho mais barato é o GitHub:
   crie um repositório, suba estes arquivos e ligue o GitHub Pages (Settings → Pages →
   branch `main`, pasta `/root`). Qualquer Netlify/Cloudflare Pages também serve.
2. Abra o endereço no celular.
   - **Android/Chrome:** menu ⋮ → *Instalar app* (ou *Adicionar à tela inicial*).
   - **iPhone/Safari:** botão compartilhar → *Adicionar à Tela de Início*.
3. Abra o app, vá em **Ajustes**, cole a chave do Gemini (grátis em
   [aistudio.google.com/apikey](https://aistudio.google.com/apikey)).
4. Em **Ajustes**, cole o endereço do proxy (próximo item) se quiser resumos.

## O proxy de 15 linhas

O site da prefeitura entrega o PDF **sem cabeçalho de CORS** — verificado: o navegador
não consegue baixar o arquivo, só abrir numa aba. A lista de edições, essa sim, vem
liberada e funciona sem nada.

Para o app conseguir ler o PDF, publique o `worker.js` (gratuito, 100 mil
requisições/dia):

1. [dash.cloudflare.com](https://dash.cloudflare.com) → Workers & Pages → Create → Worker.
2. Cole o conteúdo de `worker.js`, Deploy.
3. Copie a URL (`https://algo.alguem.workers.dev`) e use em Ajustes como
   `https://algo.alguem.workers.dev/?u={url}`.

O `{url}` é trocado pelo endereço do PDF. O Worker só aceita o domínio da prefeitura.

Sem proxy, ainda dá para resumir: baixe o PDF pelo botão *Abrir PDF* e escolha o
arquivo em **Ajustes → Resumir um PDF do aparelho**.

## Quem resume por você

O repositório também tem um robô: o GitHub Actions roda todo dia às 17h30 (Brasília),
baixa o diário novo, passa OCR, resume e commita `dados/resumos.json` e
`dados/textos/<numero>.txt`. O app lê esses arquivos — é por isso que abrir o app
mostra resumo pronto, sem chave e sem proxy.

A chave e o proxy servem só para **resumir na hora**, no seu aparelho.

Veja `../COMO_PUBLICAR.md` para ligar tudo.

## O que o app faz

- Lê a lista pela API do WordPress do site (mais recente primeiro), guarda no
  IndexedDB e marca o que é novo desde a última visita.
- Ao pedir resumo: pdf.js abre o PDF, extrai o texto de cada página e, nas páginas
  escaneadas (só cabeçalho digital, corpo em imagem), renderiza em JPEG e manda como
  imagem — o Gemini lê a imagem e resume, sem precisar de Tesseract.
- Guarda resumo, destaques, prazo, órgãos e o texto das páginas digitais.
- Busca local no texto já baixado (ignora acentos).

## Limites, ditos sem enfeite

- **Atualização em segundo plano:** Android permite sincronização periódica em PWA
  instalado, mas o Chrome só concede depois de algum uso; iPhone não permite nada.
  Na prática o app confere quando você abre. Para saber sozinho todos os dias, sem
  abrir, é preciso app nativo (WorkManager) ou um servidor.
- **Chave por pessoa:** cada servidor que instalar põe a própria chave do Gemini.
  Chave embutida no código seria abuso do free tier e vazaria no primeiro print.
- **Busca:** cobre as páginas com texto digital. As páginas que o modelo resumiu por
  imagem não guardam transcrição, então não entram na busca.
- **Documento grande:** 60+ páginas escaneadas viram várias requisições e alguns
  minutos. O resumo é por edição e fica salvo; não se paga duas vezes.

## Arquivos

| arquivo | função |
|---|---|
| `index.html` | casca do app |
| `app.js` | lista, leitura, resumo e busca |
| `styles.css` | visual (papel creme, verde, serifa) |
| `sw.js` | cache da casca para abrir offline |
| `manifest.webmanifest` | identidade do app instalado |
| `worker.js` | proxy de CORS para o Cloudflare Workers |
| `icone-*.png` | ícones |

## Rodar localmente

```bash
python3 -m http.server 8090 --bind 127.0.0.1
# abra http://127.0.0.1:8090
```

`127.0.0.1` conta como contexto seguro, então o service worker e o IndexedDB
funcionam no teste.
