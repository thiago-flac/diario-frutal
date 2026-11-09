"""Worker: uma thread que consome a fila de jobs (coletar, extrair, resumir)."""
import threading
import time
import traceback

from . import collector, db, extract, llm


class Worker(threading.Thread):
    def __init__(self, log=print):
        super().__init__(daemon=True, name="worker")
        self.log = log
        self.parar = threading.Event()
        self.atual = None

    def run(self):
        while not self.parar.is_set():
            job = db.proximo_job()
            if not job:
                self.parar.wait(4)
                continue
            self.atual = job
            try:
                self.executar(job)
                db.concluir_job(job["id"])
            except Exception as e:
                detalhe = f"{type(e).__name__}: {e}"
                self.log(f"job {job['id']} ({job['tipo']}) falhou: {detalhe}")
                traceback.print_exc()
                db.concluir_job(job["id"], erro=detalhe[:500])
            finally:
                self.atual = None

    def executar(self, job):
        tipo = job["tipo"]
        if tipo == "coletar":
            collector.verificar_novidades(log=self.log)

        elif tipo == "backfill":
            collector.enfileirar_backfill(log=self.log)

        elif tipo == "extrair":
            ed = db.edicao_por_id(job["edicao_id"])
            if not ed:
                raise RuntimeError("edição inexistente")
            post = {"id": ed["id"], "numero": ed["numero"], "titulo": ed["titulo"],
                    "data": ed["data_pub"], "url_pdf": ed["url_pdf"]}
            self.log(f"extraindo edição {ed['numero']}...")
            try:
                collector.processar(post)
            except collector.SemArquivo as e:
                self.log(f"  ed {ed['numero']}: {e}")
                db.atualizar_status(ed["numero"], "sem_arquivo", str(e))
                return
            collector.aplicar_retencao(log=self.log)
            # só gasta cota com resumo automático nas edições mais recentes
            if ed["numero"] >= db.ultima_edicao() - 5:
                db.enfileirar("resumir", ed["id"], prioridade=2)

        elif tipo == "resumir":
            self.resumir(job)

    def numero_do_job(self, job):
        ed = db.edicao_por_id(job["edicao_id"]) if job["edicao_id"] else None
        if not ed:
            raise RuntimeError("job sem edição associada")
        return ed["numero"]

    def resumir(self, job):
        ed = db.edicao_por_id(job["edicao_id"])
        if not ed:
            raise RuntimeError("edição inexistente")
        numero = ed["numero"]

        if db.resumo(numero):
            return
        paginas = [p["texto"] or "" for p in db.paginas_de(ed["id"])]
        if not paginas:
            raise RuntimeError("edição sem texto extraído")

        db.atualizar_status(numero, "resumindo")
        self.log(f"resumindo edição {numero} ({len(paginas)} páginas)...")
        texto = extract.texto_marcado(paginas)
        inicio = time.time()
        try:
            obj, modelo = llm.resumir(texto, numero, (ed["data_pub"] or "")[:10])
        except Exception:
            db.atualizar_status(numero, "extraida")
            raise
        db.salvar_resumo(ed["id"], numero, modelo, obj)
        db.atualizar_status(numero, "resumida")
        self.log(f"  ed {numero} resumida por {modelo} em {time.time()-inicio:.0f}s")


class Agendador(threading.Thread):
    """De hora em hora pergunta se apareceu diário novo."""

    def __init__(self, intervalo, log=print):
        super().__init__(daemon=True, name="agendador")
        self.intervalo = intervalo
        self.log = log
        self.parar = threading.Event()

    def run(self):
        while not self.parar.is_set():
            try:
                db.enfileirar("coletar", None, prioridade=0)
            except Exception as e:
                self.log(f"agendador: {e}")
            self.parar.wait(self.intervalo)
