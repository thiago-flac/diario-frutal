# Diário de Frutal

Leitor com resumo do Diário Oficial Eletrônico da Prefeitura de Frutal/MG
(<https://frutal.publicabrasil.net/>). O coletor baixa as edições novas sozinho,
extrai o texto (com OCR nas páginas escaneadas), resume com o Gemini no plano
gratuito e serve tudo numa interface local: lista do que saiu, resumo por edição,
busca full-text e o PDF original a um clique.

## Rodar

```bash
cd diario-lab
python3 run.py                 # sobe em http://127.0.0.1:5000
python3 run.py --backfill 10   # baixa e extrai as 10 edições mais recentes antes
python3 run.py --resumir 3     # resume as 3 mais recentes (gasta cota)
python3 run.py --porta 8080
```

A chave do Gemini fica em `chave.env` (ou `.env`, ou `GEMINI_API_KEY`):

```
GEMINI_API_KEY=AQ....
```
Aceita também o arquivo com a chave solta, sem nome.

## O que ele faz de hora em hora

1. Consulta a API do site e compara com a última edição guardada.
2. Baixando algo novo: salva o PDF em `data/pdfs/`, extrai o texto página por
   página — `pdftotext` quando a página tem camada de texto, OCR
   (`pdftoppm` 300 dpi + `tesseract -l por`) quando é imagem.
3. Indexa no SQLite/FTS5 (`remove_diacritics` — "licitacao" acha "licitação").
4. Enfileira o resumo, que roda em segundo plano e sobrevive a fechar o app.

## Interface

| rota | o que é |
|---|---|
| `/` | edições, mais novas primeiro, com resumo curto |
| `/edicao/<n>` | resumo completo, destaques com página, texto extraído, PDF embutido |
| `/busca?q=` | busca no acervo inteiro com trecho destacado |
| `/painel` | estado do coletor, fila de resumos, falhas |

## Estrutura

```
diario-lab/
  run.py              entrada: worker + agendador + servidor
  app/
    config.py         caminhos, chave, modelos, parâmetros
    db.py             SQLite + FTS5, fila de jobs
    extract.py        texto nativo e OCR por página
    llm.py            Gemini com cadeia de fallback e merge de blocos
    collector.py      API do site -> PDF -> texto -> índice
    worker.py         thread da fila + agendador horário
    web.py            rotas Flask
    templates/        base, index, edicao, busca, painel
    static/style.css
  data/               banco, PDFs e textos extraídos
```

## Notas

- Modelos em ordem: `gemini-3.5-flash` → `gemini-flash-lite-latest` →
  `gemini-3.1-flash-lite` → `gemini-3.8-flash`. O `3.8` responde 503 com
  frequência e o `2.5-flash` responde 404 para chaves novas; a cadeia cobre isso.
- Edição longa é quebrada em blocos de ~90k caracteres por marcador de página e
  os resumos parciais são fundidos num só.
- Cota gratuita reseta à meia-noite do Pacífico (4h/5h de Brasília).

## Pôr no ar para os colegas

Ver `DEPLOY.md` (VPS, domínio, HTTPS, backup). O jeito curto:

```bash
cp .env.exemplo .env   # chave do Gemini, senha do portal, segredo
docker compose up -d --build
```

## No celular (Android / iPhone)

O app já é responsivo e instalável. Com ele rodando na máquina:

```bash
python3 run.py --host 0.0.0.0
```

O terminal mostra o endereço da rede local, por exemplo `http://192.168.1.10:5000`.
Abrindo isso no celular (mesmo Wi-Fi), o app funciona igual ao desktop.

**Instalar como app:** no Chrome do Android, menu ⋮ → *Adicionar à tela inicial*.
O ícone entra na gaveta de apps e abre em tela cheia, sem barra de endereço.
O mesmo vale no iPhone: botão Compartilhar → *Adicionar à Tela de Início*.

### HTTPS: o que muda

Service worker (e o "instalar app" completo do Chrome) só funciona em **https** ou
**localhost**. Em `http://192.168.x.x` o Android cria um atalho comum, que funciona
normalmente — só não guarda páginas para leitura offline.

Para ter https de verdade, sem mexer em certificado:

```bash
# instalar o cloudflared e expor o app por um túnel com URL https
cloudflared tunnel --url http://localhost:5000

# com senha (recomendado quando exposto na internet)
DIARIO_USUARIO=algo DIARIO_SENHA=outracoisa python3 run.py
```

Com o endereço `https://...trycloudflare.com` o Chrome oferece "Instalar app" de
verdade, e o app funciona fora de casa. Sem `DIARIO_USUARIO`, qualquer pessoa com
o link entra — o túnel é público.

O trabalho pesado (download, OCR, resumo) continua na máquina; o celular é só a janela.

## Publicar

O app final é o PWA em `pwa/`, alimentado por um robô do GitHub Actions.
Siga [COMO_PUBLICAR.md](COMO_PUBLICAR.md).
