"""Entrypoint: sobe o worker, o agendador e o servidor local."""
import argparse
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import collector, config, db, llm
from app.worker import Agendador, Worker
from app.web import criar_app


def log(msg):
    print(msg, flush=True)


def main():
    ap = argparse.ArgumentParser(description="Diário Oficial de Frutal — coletor e resumidor")
    ap.add_argument("--backfill", type=int, default=0,
                    help="enfileira as N edições mais recentes para baixar e extrair em segundo plano")
    ap.add_argument("--resumir", type=int, default=0,
                    help="resume as N edições mais recentes (gasta cota do Gemini)")
    ap.add_argument("--porta", type=int, default=5000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--sem-agendador", action="store_true")
    ap.add_argument("--sem-worker", action="store_true",
                    help="não processa a fila aqui (quando a fila roda noutro processo)")
    ap.add_argument("--so-worker", action="store_true",
                    help="roda só fila e agendador, sem subir a interface")
    ap.add_argument("--limpar-pdfs", action="store_true",
                    help="apaga PDFs antigos agora (mantém o texto e o acesso sob demanda)")
    args = ap.parse_args()

    db.init()
    if not config.chave_gemini():
        log("AVISO: nenhuma chave encontrada (chave.env / .env) — só coleta e busca vão funcionar.")

    if args.limpar_pdfs:
        n = collector.aplicar_retencao(log=log)
        log(f"{n} PDFs removidos; texto e busca continuam intactos.")

    if args.backfill:
        log(f"enfileirando {args.backfill} edições mais recentes (a interface sobe já)")
        collector.enfileirar_backfill(limite=args.backfill, log=log)

    if not args.sem_worker:
        Worker(log=log).start()
    if not args.sem_agendador:
        Agendador(config.INTERVALO_COLETA, log=log).start()

    if args.so_worker:
        log("modo coletor: fila e agendador ativos, sem interface.")
        while True:
            time.sleep(300)

    app = criar_app()
    log(f"\n  Diário de Frutal -> http://{args.host}:{args.porta}")
    if args.host in ("0.0.0.0", "::") or args.host.endswith(".0.0"):
        try:
            _s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            _s.connect(("8.8.8.8", 80))
            log(f"  No celular, no mesmo Wi-Fi -> http://{_s.getsockname()[0]}:{args.porta}\n")
            _s.close()
        except OSError:
            pass
    else:
        log("")
    app.run(host=args.host, port=args.porta, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
