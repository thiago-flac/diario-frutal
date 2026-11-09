#!/usr/bin/env python3
"""Gera os resumos que o PWA lê — sem servidor, sem banco, rodando no GitHub Actions.

O que faz, em ordem:
  1. pergunta à API do site quais edições existem;
  2. compara com pwa/dados/resumos.json e escolhe as que faltam;
  3. baixa o PDF, extrai o texto (camada nativa + OCR nas páginas em imagem);
  4. grava o texto em pwa/dados/textos/<numero>.txt (para a busca do app);
  5. pede o resumo ao Gemini e acrescenta ao JSON.

Uso:
    GEMINI_API_KEY=... python ferramentas/gerar_resumos.py --limite 3
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app import collector, config, extract, llm  # noqa: E402


def ler_json(caminho: Path) -> list[dict]:
    if not caminho.exists():
        return []
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        return dados if isinstance(dados, list) else []
    except ValueError:
        print(f"aviso: {caminho} ilegível, começando do zero")
        return []


def gravar_json(caminho: Path, dados: list[dict]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def podar_textos(pasta: Path, manter: int) -> int:
    arquivos = sorted(pasta.glob("*.txt"), key=lambda p: int(p.stem) if p.stem.isdigit() else 0,
                      reverse=True)
    removidos = 0
    for velho in arquivos[manter:]:
        velho.unlink()
        removidos += 1
    return removidos


def entrada(numero: int, data: str, resultado: dict, modelo: str, paginas: int) -> dict:
    return {
        "numero": numero,
        "data": (data or "")[:10],
        "resumo": resultado.get("resumo_curto", ""),
        "tipo": resultado.get("tipo_documento", ""),
        "prazo": resultado.get("prazo", "") or "",
        "relevancia": resultado.get("relevancia_geral"),
        "orgaos": resultado.get("orgaos", []) or [],
        "destaques": resultado.get("destaques", []) or [],
        "paginas": paginas,
        "modelo": modelo,
        "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Resume as edições novas e alimenta o PWA")
    ap.add_argument("--limite", type=int, default=3, help="quantas edições resumir nesta rodada")
    ap.add_argument("--saida", default=str(RAIZ / "pwa/dados/resumos.json"))
    ap.add_argument("--textos", default=str(RAIZ / "pwa/dados/textos"))
    ap.add_argument("--manter-textos", type=int, default=120)
    ap.add_argument("--forcar", action="store_true", help="refaz mesmo as já resumidas")
    args = ap.parse_args()

    if not config.chave_gemini():
        print("ERRO: defina GEMINI_API_KEY (no GitHub, como secret do repositório).")
        return 1

    saida = Path(args.saida)
    textos = Path(args.textos)
    # checkout limpo do CI não tem data/: sem isso o download do PDF falha
    for pasta in (config.DADOS, config.PDFS, textos):
        pasta.mkdir(parents=True, exist_ok=True)

    try:
        edicoes = collector.listar()
    except Exception as e:  # noqa: BLE001
        print(f"ERRO ao listar edições: {e}")
        return 1

    prontos = ler_json(saida)
    feitos = {e.get("numero") for e in prontos}
    pendentes = [e for e in edicoes if args.forcar or e["numero"] not in feitos]
    pendentes.sort(key=lambda e: e["numero"], reverse=True)
    pendentes = pendentes[:max(0, args.limite)]

    print(f"{len(edicoes)} edições na API · {len(feitos)} já resumidas · "
          f"{len(pendentes)} nesta rodada")

    novos = 0
    falhas = 0
    for ed in pendentes:
        numero = ed["numero"]
        try:
            pdf = collector.baixar_pdf(numero, ed.get("url_pdf"))
            paginas, com_ocr = extract.extrair(pdf)
            texto = extract.texto_marcado(paginas)
            if not texto.strip():
                print(f"  ed {numero}: sem texto extraível, pulando")
                continue

            (textos / f"{numero}.txt").write_text(texto, encoding="utf-8")

            resultado, modelo = llm.resumir(texto, numero, (ed.get("data") or "")[:10])
            item = entrada(numero, ed.get("data"), resultado, modelo, len(paginas))
            prontos = [e for e in prontos if e.get("numero") != numero] + [item]
            novos += 1
            print(f"  ed {numero}: {len(paginas)} páginas ({len(com_ocr)} via OCR) · "
                  f"{modelo} · {item['resumo'][:90]}…")
        except collector.SemArquivo:
            print(f"  ed {numero}: o site não tem arquivo para esta edição")
        except Exception as e:  # noqa: BLE001
            falhas += 1
            print(f"  ed {numero}: falhou ({type(e).__name__}: {e})")

    prontos.sort(key=lambda e: e.get("numero", 0), reverse=True)
    gravar_json(saida, prontos)
    removidos = podar_textos(textos, args.manter_textos)
    print(f"gravado {saida} com {len(prontos)} resumos · {novos} novos · "
          f"{removidos} textos antigos removidos")

    # falhar alto: job verde que não resumiu nada é pior que job vermelho
    if pendentes and not novos and falhas:
        print(f"ERRO: {falhas} de {len(pendentes)} edições falharam e nenhuma entrou")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
