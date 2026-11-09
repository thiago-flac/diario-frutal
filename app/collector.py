"""Coleta: descobre edições novas na API do site, baixa e extrai o texto."""
import os
import re
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from . import config, db, extract

UA = {"User-Agent": "Mozilla/5.0 (diario-frutal/1.0; uso pessoal)"}


class SemArquivo(Exception):
    """Post do site sem nenhum arquivo anexado — não há o que extrair."""


RE_NUM = re.compile(r"EDI[ÇC][ÃA]O\s*0*(\d+)", re.I)


def _get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def listar(pagina: int = 1, por_pagina: int = 100) -> list[dict]:
    url = (f"{config.API}?per_page={por_pagina}&page={pagina}"
           f"&orderby=date&order=desc&_fields=id,date,title,content,link")
    posts = []
    for p in __import__("json").loads(_get(url)):
        titulo = re.sub("<[^>]+>", "", p["title"]["rendered"]).strip()
        m = RE_NUM.search(titulo)
        if not m:
            continue
        anexos = re.findall(r'href="([^"]+\.(?:pdf|docx?|odt))"', p["content"]["rendered"], re.I)
        posts.append({"id": p["id"], "numero": int(m.group(1)), "titulo": titulo,
                      "data": p["date"], "url_pdf": anexos[0] if anexos else None})
    return posts


def caminho_pdf(numero: int):
    return config.PDFS / f"ed{numero:04d}.pdf"


def _converter_para_pdf(origem: Path) -> Path:
    """Word/ODT -> PDF pelo LibreOffice, para entrar no mesmo pipeline."""
    destino = origem.with_suffix(".pdf")
    if destino.exists():
        return destino
    env = dict(os.environ, HOME=str(origem.parent))
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf",
                    "--outdir", str(origem.parent), str(origem)],
                   check=True, capture_output=True, timeout=240, env=env)
    if not destino.exists():
        raise RuntimeError("não consegui converter para PDF")
    return destino


def baixar_pdf(numero: int, url: str | None = None) -> Path:
    """Garante o PDF em disco; baixa (e converte Word/ODT) quando falta."""
    pdf = caminho_pdf(numero)
    if pdf.exists():
        return pdf
    if not url:
        ed = db.edicao(numero)
        url = ed["url_pdf"] if ed else None
    if not url:
        raise SemArquivo(f"edição {numero} não tem arquivo publicado no site")
    ext = url.rsplit(".", 1)[-1].lower().split("?")[0]
    if ext == "pdf":
        pdf.write_bytes(_get(url, timeout=180))
        return pdf
    bruto = config.PDFS / f"ed{numero:04d}.{ext}"
    bruto.write_bytes(_get(url, timeout=180))
    return _converter_para_pdf(bruto)


def aplicar_retencao(log=None) -> int:
    """Apaga PDFs antigos (o texto já está indexado). Libera gigabytes sem perder acesso."""
    recentes = db.numeros_recentes(config.GUARDAR_PDF_RECENTES)
    if not recentes:
        return 0
    corte = min(recentes)
    apagados = 0
    for f in config.PDFS.glob("ed*.*"):
        m = re.search(r"ed(\d+)", f.name)
        if m and int(m.group(1)) < corte:
            f.unlink(missing_ok=True)
            apagados += 1
    if apagados and log:
        log(f"  retenção: {apagados} PDFs antigos removidos (texto preservado)")
    return apagados


def processar(post: dict, baixar_ocr: bool = True) -> dict:
    """Baixa o PDF, extrai o texto, grava páginas + índice de busca."""
    numero = post["numero"]
    url = post.get("url_pdf")
    if not url:
        raise SemArquivo(f"edição {numero} não tem arquivo publicado no site")
    pdf = baixar_pdf(numero, url)

    db.salvar_edicao({
        "id": post["id"], "numero": numero, "data_pub": post["data"],
        "titulo": post["titulo"], "url_pdf": post["url_pdf"], "status": "baixada",
        "paginas": extract.contar_paginas(pdf), "chars": 0, "paginas_ocr": [], "erro": None,
    })

    if baixar_ocr:
        paginas, ocr = extract.extrair(pdf)
    else:
        paginas, ocr = [""] * extract.contar_paginas(pdf), []

    texto = extract.texto_marcado(paginas)
    (config.TEXTOS / f"ed{numero:04d}.txt").write_text(texto, encoding="utf-8")
    db.salvar_paginas(post["id"], numero, paginas, ocr)
    db.salvar_edicao({
        "id": post["id"], "numero": numero, "data_pub": post["data"],
        "titulo": post["titulo"], "url_pdf": post["url_pdf"], "status": "extraida",
        "paginas": len(paginas), "chars": len(texto), "paginas_ocr": ocr, "erro": None,
    })
    return {"numero": numero, "paginas": len(paginas), "chars": len(texto), "ocr": len(ocr)}


def coletar(limite: int = 10, resumir_novas: int = 3, log=print) -> int:
    """Baixa e extrai as edições mais recentes que ainda não estão no banco."""
    novos, pagina = 0, 1
    while novos < limite and pagina <= 6:
        posts = listar(pagina)
        if not posts:
            break
        for post in posts:
            if novos >= limite:
                break
            # já processada de verdade? então pula. estado parcial (baixada/erro) reprocessa
            anterior = db.edicao(post["numero"])
            if anterior and anterior["status"] in ("extraida", "resumida", "resumindo"):
                continue
            try:
                info = processar(post)
                log(f"  ed {info['numero']:>3} | {info['paginas']:>2}p | "
                    f"{info['chars']:>6} chars | {info['ocr']} paginas via OCR")
                if novos < resumir_novas:
                    db.enfileirar("resumir", post["id"], prioridade=1)
                novos += 1
            except Exception as e:
                log(f"  ed {post['numero']:>3} FALHOU: {type(e).__name__}: {e}")
                db.salvar_edicao({"id": post["id"], "numero": post["numero"],
                                  "data_pub": post["data"], "titulo": post["titulo"],
                                  "url_pdf": post.get("url_pdf"), "status": "erro",
                                  "erro": str(e)[:300], "paginas": 0, "chars": 0,
                                  "paginas_ocr": []})
            time.sleep(config.PAUSA_ENTRE_DOWNLOADS)
        pagina += 1
    return novos


def verificar_novidades(log=print) -> int:
    """Roda de hora em hora: se apareceu edição maior que a última, coleta."""
    posts = listar(1)
    if not posts:
        return 0
    maior = max(p["numero"] for p in posts)
    if maior <= db.ultima_edicao():
        return 0
    log(f"nova edição detectada: {maior}")
    return coletar(limite=max(1, maior - db.ultima_edicao()), resumir_novas=2, log=log)

def enfileirar_backfill(limite: int | None = None, log=print) -> int:
    """Descobre o acervo inteiro e enfileira o que falta extrair, sem bloquear o servidor."""
    total, pagina = 0, 1
    while pagina <= 12:
        posts = listar(pagina)
        if not posts:
            break
        for post in posts:
            ed = db.edicao(post["numero"])
            if ed and ed["status"] in ("extraida", "resumida", "resumindo"):
                continue
            if not ed:
                db.salvar_edicao({"id": post["id"], "numero": post["numero"],
                                  "data_pub": post["data"], "titulo": post["titulo"],
                                  "url_pdf": post.get("url_pdf"), "status": "nova",
                                  "paginas": None, "chars": 0, "paginas_ocr": [], "erro": None})
                ed = db.edicao(post["numero"])
            # as 20 mais recentes furam a fila
            prioridade = 3 if total < 20 else 6
            db.enfileirar("extrair", ed["id"], prioridade=prioridade)
            total += 1
            if limite and total >= limite:
                log(f"backfill enfileirado: {total} edições")
                return total
        pagina += 1
    log(f"backfill enfileirado: {total} edições")
    return total
