"""Interface web: lista, leitura do resumo, busca full-text e painel da fila."""
import json
from pathlib import Path

from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   send_file, session, url_for)

from . import collector, config, db

app = Flask(__name__)
app.secret_key = config.SEGREDO or "troque-esta-chave"
app.jinja_env.globals["config"] = config


@app.template_filter("dejson")
def dejson(txt):
    if not txt:
        return None
    try:
        return json.loads(txt)
    except (ValueError, TypeError):
        return None


@app.template_filter("data_br")
def data_br(iso: str | None) -> str:
    if not iso:
        return "—"
    return f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]}"


@app.route("/")
def home():
    pagina = max(1, request.args.get("p", 1, type=int))
    edicoes, total = db.edicoes(pagina=pagina, por_pagina=15)
    return render_template("index.html", edicoes=edicoes, pagina=pagina,
                           total=total, stats=db.estatisticas())


@app.route("/edicao/<int:numero>")
def ver_edicao(numero):
    ed = db.edicao(numero)
    if not ed:
        abort(404)
    paginas = db.paginas_de(ed["id"])
    return render_template("edicao.html", ed=ed, resumo=db.resumo(numero),
                           paginas=paginas, pdf_em_disco=pdf_local(numero))


@app.route("/busca")
def busca():
    termo = (request.args.get("q") or "").strip()
    resultados = db.buscar(termo) if termo else []
    return render_template("busca.html", termo=termo, resultados=resultados,
                           stats=db.estatisticas())


@app.route("/painel")
def painel():
    fila = db.fila_resumo()
    edicoes, total = db.edicoes(pagina=1, por_pagina=10)
    return render_template("painel.html", fila=fila, edicoes=edicoes,
                           stats=db.estatisticas())


def pdf_local(numero: int) -> bool:
    return (config.PDFS / f"ed{numero:04d}.pdf").exists()


LIBERADO = {"entrar", "static", "manifesto", "saude"}


@app.before_request
def exigir_senha():
    """Portal interno: com DIARIO_SENHA definida, só entra quem digitar a senha."""
    if not config.SENHA_ACESSO:
        return None
    if request.endpoint in LIBERADO or session.get("entrou"):
        return None
    return redirect(url_for("entrar", proximo=request.full_path if request.query_string else request.path))


@app.route("/entrar", methods=["GET", "POST"])
def entrar():
    erro = None
    if request.method == "POST":
        if request.form.get("senha", "") == config.SENHA_ACESSO:
            session["entrou"] = True
            session.permanent = True
            destino = request.form.get("proximo") or url_for("home")
            return redirect(destino if destino.startswith("/") else url_for("home"))
        erro = "Senha incorreta."
    return render_template("entrar.html", erro=erro,
                           proximo=request.args.get("proximo", ""))


@app.route("/sair")
def sair():
    session.clear()
    return redirect(url_for("entrar"))


@app.route("/saude")
def saude():
    e = db.estatisticas()
    return jsonify({"ok": True, **e})

@app.route("/manifest.webmanifest")
def manifesto():
    return app.response_class(json.dumps({
        "name": "Diário de Frutal",
        "short_name": "Diário",
        "description": "Resumos do Diário Oficial Eletrônico de Frutal/MG",
        "lang": "pt-BR",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait-primary",
        "background_color": "#faf7f2",
        "theme_color": "#1f6b3b",
        "icons": [
            {"src": "/static/icone-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icone-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/static/icone-maskable.png", "sizes": "512x512", "type": "image/png",
             "purpose": "maskable"},
        ],
    }), mimetype="application/manifest+json")


@app.route("/pdf/<int:numero>")
def pdf(numero):
    caminho = config.PDFS / f"ed{numero:04d}.pdf"
    if not caminho.exists():
        # edição antiga: o PDF não fica em disco, mas o site ainda tem o arquivo
        try:
            caminho = collector.baixar_pdf(numero)
        except Exception:
            abort(404)
    return send_file(caminho, mimetype="application/pdf",
                     download_name=f"diario-{numero}.pdf", conditional=True)


# ---------- ações ----------

@app.post("/api/coletar")
def api_coletar():
    db.enfileirar("coletar", None, prioridade=0)
    return redirect(url_for("painel"))


@app.post("/api/backfill")
def api_backfill():
    limite = request.form.get("limite", type=int)
    db.enfileirar("backfill", None, prioridade=0)
    return redirect(url_for("painel"))


@app.post("/api/resumir/<int:numero>")
def api_resumir(numero):
    ed = db.edicao(numero)
    if not ed:
        abort(404)
    db.enfileirar("resumir", ed["id"], prioridade=3)
    return redirect(url_for("ver_edicao", numero=numero))


@app.get("/api/status/<int:numero>")
def api_status(numero):
    ed = db.edicao(numero)
    if not ed:
        abort(404)
    return jsonify({"numero": numero, "status": ed["status"],
                    "tem_resumo": db.resumo(numero) is not None,
                    "erro": ed["erro"]})


@app.get("/api/fila")
def api_fila():
    return jsonify([dict(j) for j in db.fila_resumo()])


def criar_app():
    db.init()
    return app
