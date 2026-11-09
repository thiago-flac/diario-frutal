# Diário de Frutal — imagem de produção.
# Python slim + tesseract (português) + poppler + LibreOffice para os .docx
# que a prefeitura publica de vez em quando.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=America/Sao_Paulo

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-por poppler-utils \
        fonts-dejavu-core tzdata \
        libreoffice-writer-nogui \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install "flask>=3.0" "gunicorn>=21"

COPY app ./app
COPY run.py wsgi.py ./

RUN mkdir -p /app/data/pdfs /app/data/txt
ENV DIARIO_DADOS=/app/data

EXPOSE 8000
# 1 processo + threads: o SQLite aceita leitura concorrente, mas escrita concorrente
# entre processos é pedir briga. A fila pesada vive no serviço "coletor".
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "8", \
     "--timeout", "120", "--access-logfile", "-", "wsgi:app"]
