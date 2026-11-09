"""Ponto de entrada para produção (gunicorn/uwsgi): só a interface, sem fila.

A fila roda num processo separado (`python run.py --so-worker`), para que reiniciar
ou escalar a interface nunca duplique OCR nem gaste cota duas vezes.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import db

db.init()

from app.web import criar_app  # noqa: E402

app = criar_app()
