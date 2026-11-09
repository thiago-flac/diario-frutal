"""Cliente do Gemini com cadeia de fallback entre modelos gratuitos."""
import json
import re
import time
import urllib.error
import urllib.request

from . import config

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
LIMITE_CHARS = 90_000          # acima disso, quebra em blocos
MAX_BLOCOS = 6

PROMPT = """Você lê o Diário Oficial do município de Frutal/MG e escreve um briefing para um cidadão que não vai ler o documento inteiro.

Responda APENAS com JSON válido, sem markdown, neste formato:

{{
  "resumo_curto": "3 a 5 linhas, direto, o que essa edição traz",
  "tipo_documento": "lei|decreto|portaria|licitação|contrato|plano|ato|misto",
  "orgaos": ["órgãos citados"],
  "destaques": [
    {{"titulo": "curto", "texto": "1 a 3 frases com o efeito prático", "pagina": 3, "categoria": "licitação|pessoal|tributo|saúde|obras|educação|norma|outro"}}
  ],
  "prazo": "data ou prazo mencionado, ou null",
  "relevancia_geral": 0
}}

Regras: no máximo 6 destaques. Priorize o que tem efeito prático e prazo. `pagina` é o número que aparece no marcador [PAGINA n] mais próximo do trecho. `relevancia_geral` de 0 a 3 (0 = rotina burocrática sem efeito para o cidadão). Ignore cabeçalho, rodapé, marca d'água e assinatura digital. O texto pode ter ruído de OCR: não invente nada que não esteja nele.

EDIÇÃO Nº {numero} — publicada em {data}

TEXTO:
{texto}"""

PROMPT_JUNTA = """Você recebeu resumos parciais de blocos do mesmo Diário Oficial (edição {numero}).
Junte tudo num único briefing, sem repetir item. Responda APENAS com JSON válido no mesmo formato:
{{"resumo_curto":"...","tipo_documento":"...","orgaos":[],"destaques":[{{"titulo":"","texto":"","pagina":0,"categoria":"outro"}}],"prazo":null,"relevancia_geral":0}}
Máximo 6 destaques, os mais relevantes.

RESUMOS PARCIAIS:
{parcial}"""

VAZIO = {"resumo_curto": "", "tipo_documento": "misto", "orgaos": [],
         "destaques": [], "prazo": None, "relevancia_geral": 0}


class SemModelo(RuntimeError):
    pass


def _chamar(modelo: str, prompt: str, timeout: int = 240) -> tuple[str, dict]:
    chave = config.chave_gemini()
    if not chave:
        raise SemModelo("nenhuma chave encontrada em chave.env / .env / GEMINI_API_KEY")
    corpo = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }).encode()
    req = urllib.request.Request(
        ENDPOINT.format(m=modelo), data=corpo,
        headers={"Content-Type": "application/json", "x-goog-api-key": chave})
    r = json.load(urllib.request.urlopen(req, timeout=timeout))
    cand = r["candidates"][0]
    texto = "".join(p.get("text", "") for p in cand["content"]["parts"])
    return texto, r.get("usageMetadata", {})


def _json_tolerante(txt: str) -> dict:
    txt = txt.strip()
    txt = re.sub(r"^```(?:json)?|```$", "", txt, flags=re.M).strip()
    i, j = txt.find("{"), txt.rfind("}")
    if i >= 0 and j > i:
        txt = txt[i:j + 1]
    return json.loads(txt)


def chamar(prompt: str, modelos=None, tentativas_por_modelo: int = 2) -> tuple[dict, str]:
    """Tenta cada modelo; devolve (objeto, modelo_que_respondeu)."""
    modelos = modelos or config.MODELOS
    falhas = []
    for modelo in modelos:
        for t in range(1, tentativas_por_modelo + 1):
            try:
                txt, _uso = _chamar(modelo, prompt)
                return _json_tolerante(txt), modelo
            except urllib.error.HTTPError as e:
                falhas.append(f"{modelo}:{e.code}")
                if e.code in (429, 500, 503):
                    time.sleep(2 * t)
                    continue
                break                      # 400/404 não melhora repetindo
            except (TimeoutError, urllib.error.URLError) as e:
                falhas.append(f"{modelo}:{type(e).__name__}")
                time.sleep(2 * t)
            except (json.JSONDecodeError, KeyError) as e:
                falhas.append(f"{modelo}:json")
                break
    raise SemModelo("todos os modelos falharam -> " + ", ".join(falhas))


def _blocos(texto: str) -> list[str]:
    if len(texto) <= LIMITE_CHARS:
        return [texto]
    partes = re.split(r"(?=\n\[PAGINA \d+\])", texto)
    partes = [p for p in partes if p.strip()]
    n = max(1, min(MAX_BLOCOS, -(-len(texto) // LIMITE_CHARS)))
    tam = -(-len(partes) // n)
    return ["".join(partes[i:i + tam]) for i in range(0, len(partes), tam)]


def resumir(texto: str, numero: int, data: str) -> tuple[dict, str]:
    blocos = _blocos(texto)
    if len(blocos) == 1:
        return chamar(PROMPT.format(numero=numero, data=data, texto=blocos[0]))

    parciais, modelos_usados = [], []
    for b in blocos:
        try:
            obj, m = chamar(PROMPT.format(numero=numero, data=data, texto=b))
            parciais.append(obj)
            modelos_usados.append(m)
        except SemModelo:
            continue
    if not parciais:
        raise SemModelo("nenhum bloco foi resumido")

    juntos = "\n\n".join(json.dumps(p, ensure_ascii=False) for p in parciais)
    fim, m = chamar(PROMPT_JUNTA.format(numero=numero, parcial=juntos))
    return fim, m
