# Pôr o Diário de Frutal no ar, fora da sua máquina

Este documento existe porque o app deixou de ser pessoal: colegas de trabalho vão
acessar. Isso muda requisitos — endereço fixo, HTTPS, senha, backup, e um processo
que roda sozinho todos os dias.

## O que a aplicação precisa de um servidor

| Recurso | Quanto | Por quê |
|---|---|---|
| CPU | 2 vCPU | OCR é o gargalo (Tesseract puxa CPU, não GPU) |
| RAM | 2 GB | OCR + LibreOffice esporádico |
| Disco | 20 GB | ~70 MB de PDFs recentes + ~1,5 GB de texto, busca e logs |
| HTTPS | domínio + certificado | o Caddy resolve sozinho |
| Porta | 80/443 | |

Nada de banco externo, Redis, fila gerenciada. É um processo Python e um SQLite.

## Caminho recomendado: VPS pequena

Custa entre R$ 25 e R$ 45 por mês. Serve Hetzner (Alemanha, o mais barato),
DigitalOcean, Vultr, ou uma máquina brasileira se o jurídico exigir dado em território
nacional. Todas com Ubuntu 24.04.

```bash
# no servidor
apt update && apt install -y docker.io docker-compose-v2 git
git clone <seu-repo> diario && cd diario
cp .env.exemplo .env      # chave do Gemini, senha do portal, segredo da sessão
nano Caddyfile            # trocar pelo domínio real
docker compose up -d --build
```

O Caddy pega o certificado no primeiro acesso. O `docker compose logs -f coletor`
mostra a fila andando.

### Alternativa gratuita: Oracle Cloud Always Free

A VM ARM de 4 núcleos e 24 GB de RAM do plano gratuito sobra para isso e não cobra
mensalidade. O preço é a burocracia: cartão para validar, instâncias que somem se
ficarem ociosas (dá para contornar), e o console deles é o que é.

### O que NÃO serve

- **Render/Railway/Fly no plano grátis:** o disco não persiste ou a máquina dorme.
  Um portal que apaga o banco quando ninguém acessa não é um portal.
- **Cloudflare Pages/Vercel:** não rodam Python nem OCR.
- **GitHub Actions como cron:** funciona para coletar de hora em hora, mas não serve
  como site, e o timeout de 6 horas mataria o backfill.

## Sistema que não reinicia sozinho

Enquanto for Docker, `restart: unless-stopped` resolve. Sem Docker, dois serviços
systemd — um para a interface, outro para a fila — para que reiniciar a interface
nunca duplique OCR.

## Backup (o item que todo mundo esquece)

O banco é um arquivo. Backup de verdade é cópia fora da máquina:

```bash
# no cron da VPS, todo dia às 3h
sqlite3 /var/lib/docker/volumes/diario_dados/_data/diario.db \
  ".backup '/var/backups/diario-$(date +%F).db'"
find /var/backups -name 'diario-*.db' -mtime +30 -delete
```

O texto de tudo que foi publicado está nesse arquivo. Os PDFs são recuperáveis do site
da prefeitura a qualquer momento, então não precisam de backup.

## Cota do Gemini, agora que são várias pessoas

O resumo é **por edição**, não por pessoa: alguém pede, todos leem o mesmo. Isso
mantém o consumo baixíssimo — uma edição por dia útil, ~10 mil tokens. O free tier
aguenta com folga. Se o portal crescer, o caminho é uma chave paga (alguns centavos
por edição) e não um plano maior.

## Antes de abrir para os colegas

- [ ] Senha definida (`DIARIO_SENHA`) e avisada por canal interno, não por e-mail geral.
- [ ] `X-Robots-Tag: noindex` no Caddy — o portal não precisa aparecer no Google.
- [ ] Aviso fixo no rodapé: os resumos são gerados por IA a partir de OCR; o PDF oficial é a fonte.
- [ ] Combinar com o jurídico/Comunicação se o portal pode ter o brasão ou o nome da prefeitura.
      Publicar resumo de ato oficial em site não oficial tem implicação — o rodapé com
      link para a fonte original é o mínimo.
- [ ] Domínio: `diario.frutal.mg.gov.br` (institucional) ou um domínio próprio
      (mais rápido de subir, menos "oficial").

## Rodando sem Docker (se preferir)

```bash
apt install -y python3 python3-venv tesseract-ocr tesseract-ocr-por poppler-utils
python3 -m venv .venv && . .venv/bin/activate
pip install flask gunicorn

# interface
DIARIO_SENHA=... GEMINI_API_KEY=... gunicorn -b 127.0.0.1:8000 -w 1 --threads 8 wsgi:app
# fila, noutro terminal ou noutro serviço
DIARIO_SENHA=... GEMINI_API_KEY=... python run.py --so-worker
```

O `Caddyfile` continua valendo na frente, na porta 443.
