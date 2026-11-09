"""Configuração central. Lê a chave de chave.env ou .env, sem hardcode."""
from pathlib import Path
import os

RAIZ = Path(__file__).resolve().parent.parent          # diario-lab/
# Em produção o volume monta em outro lugar; o padrão continua data/ ao lado do código.
DADOS = Path(os.environ.get("DIARIO_DADOS") or RAIZ / "data")
PDFS = DADOS / "pdfs"
TEXTOS = DADOS / "txt"
DB_PATH = DADOS / "diario.db"

SITE = "https://frutal.publicabrasil.net"
API = f"{SITE}/wp-json/wp/v2/lsvr_document"

# modelos em ordem de preferência; o primeiro que responder assume
MODELOS = [
    "gemini-3.5-flash",
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",       # bonito quando funciona, 503 com frequência hoje
]

OCR_MIN_CHARS = 180          # abaixo disso a página é tratada como imagem
OCR_DPI = 300
OCR_WORKERS = 4             # medido: 4 dá ~3x de ganho; 6+ satura a máquina
PAUSA_ENTRE_DOWNLOADS = 1.5  # segundos, para não martelar o servidor da prefeitura
INTERVALO_COLETA = 60 * 60   # o agendador olha de hora em hora

# PDFs são grandes (~4 MB cada). Guardamos em disco só os mais recentes; os antigos
# ficam com o texto no banco e o PDF é baixado do site na hora em que alguém abrir.
GUARDAR_PDF_RECENTES = 20


def _ler_arquivo_env(p: Path) -> str | None:
    if not p.exists():
        return None
    bruto = p.read_text(encoding="utf-8", errors="replace").strip()
    if not bruto:
        return None
    for linha in bruto.splitlines():
        s = linha.strip()
        if not s or s.startswith("#"):
            continue
        if "=" in s:
            k, v = s.split("=", 1)
            if k.strip().upper() in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "API_KEY"):
                return v.strip().strip('"').strip("'")
    # arquivo só com a chave solta, sem nome=valor
    candidato = bruto.splitlines()[0].strip().strip('"').strip("'")
    return candidato or None


def chave_gemini() -> str | None:
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"].strip()
    for nome in ("chave.env", ".env"):
        v = _ler_arquivo_env(RAIZ / nome)
        if v:
            return v
    return None


def preparar_pastas():
    for d in (DADOS, PDFS, TEXTOS):
        d.mkdir(parents=True, exist_ok=True)

# Acesso por senha (opcional). Só serve quando o app é exposto na internet por
# um túnel — na rede de casa, sem isso, qualquer aparelho do Wi-Fi entra.
USUARIO = os.environ.get("DIARIO_USUARIO", "")
SENHA_ACESSO = os.environ.get("DIARIO_SENHA", "")   # portal interno: pede esta senha
SEGREDO = os.environ.get("DIARIO_SEGREDO", "")      # assina o cookie de sessão
