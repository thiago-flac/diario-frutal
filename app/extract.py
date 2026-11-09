"""Extração de texto: camada nativa do PDF e OCR nas páginas que são imagem."""
import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import config

# cabeçalho e rodapé repetidos em toda página do diário
BOILER = re.compile(
    r"(Frutal/MG,? \d{1,2} de [^\n]{0,60}?N[ºo°] ?\d+"
    r"|Frutal, \d{1,2} de [^\n]{0,60}?N[ºo°] ?\d+"
    r"|Vers[ãa]o eletr[ôo]nica dispon[íi]vel em:[^\n]*"
    r"|Documento assinado digitalmente conforme MP[^\n]*"
    r"|^\s*\d{1,3}\s*$)", re.M | re.I)

LINHA_LOGO = re.compile(r"^\s*(PREFEITURA DE|Frutal\s*\|\s*Di[áa]rio Oficial Eletr[ôo]nico)\s*$", re.M | re.I)


def contar_paginas(pdf: Path) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    m = re.search(r"Pages:\s+(\d+)", out)
    return int(m.group(1)) if m else 0


def _limpar(texto: str) -> str:
    texto = texto.replace("\f", "\n")
    texto = BOILER.sub("", texto)
    texto = LINHA_LOGO.sub("", texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def _texto_nativo(pdf: Path, pagina: int) -> str:
    return subprocess.run(["pdftotext", "-f", str(pagina), "-l", str(pagina), str(pdf), "-"],
                          capture_output=True, text=True).stdout


def _ocr(pdf: Path, pagina: int, tmp: Path) -> str:
    base = tmp / f"p{pagina:04d}"
    subprocess.run(["pdftoppm", "-f", str(pagina), "-l", str(pagina),
                    "-r", str(config.OCR_DPI), "-gray", "-png", str(pdf), str(base)],
                   check=True, capture_output=True)
    imagens = sorted(tmp.glob(f"p{pagina:04d}-*.png"))
    if not imagens:
        return ""
    # sem OMP_THREAD_LIMIT o tesseract abre uma thread por núcleo em cada instância,
    # e alguns workers em paralelo viram disputa de CPU (medido: 78s/página)
    env = dict(os.environ, OMP_THREAD_LIMIT="1", OMP_NUM_THREADS="1")
    return subprocess.run(["tesseract", str(imagens[0]), "-", "-l", "por", "--psm", "3"],
                          capture_output=True, text=True, env=env).stdout


def extrair(pdf: Path, log=None) -> tuple[list[str], list[int]]:
    """Devolve (texto por página, lista de páginas que precisaram de OCR)."""
    total = contar_paginas(pdf)
    if not total:
        return [], []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        nativos = [_limpar(_texto_nativo(pdf, p)) for p in range(1, total + 1)]
        com_ocr = [p for p, t in enumerate(nativos, 1)
                   if len(re.sub(r"\s", "", t)) < config.OCR_MIN_CHARS]

        paginas = list(nativos)
        if com_ocr:
            trabalhadores = max(1, min(config.OCR_WORKERS, len(com_ocr)))
            if log:
                log(f"    OCR em {len(com_ocr)}/{total} páginas, {trabalhadores} em paralelo")
            feitas = 0
            with ThreadPoolExecutor(max_workers=trabalhadores) as pool:
                futuros = {pool.submit(_ocr, pdf, p, tmp): p for p in com_ocr}
                for fut in as_completed(futuros):
                    p = futuros[fut]
                    try:
                        paginas[p - 1] = _limpar(fut.result())
                    except Exception:
                        paginas[p - 1] = nativos[p - 1]
                    feitas += 1
                    if log and (feitas % 10 == 0 or feitas == len(com_ocr)):
                        log(f"    OCR {feitas}/{len(com_ocr)}")
    return paginas, com_ocr


def texto_marcado(paginas: list[str]) -> str:
    """Texto com marcadores de página, para o modelo citar a página certa."""
    return "\n".join(f"\n[PAGINA {i}]\n{p}" for i, p in enumerate(paginas, 1) if p.strip())
