"""Normas: tipos, ano, letra, chave, ementa, data e nome de exibição (SPEC §5)."""
from __future__ import annotations

import datetime
import re
import unicodedata

# ---------------------------------------------------------------- §5.1 tipos
TIPOS = {
    "lei": "lei",
    "lei complementar": "lc",
    "decreto-lei": "dl",
    "medida provisoria": "mp",
    "emenda constitucional": "ec",
    "lei delegada": "ld",
    "emenda constitucional de revisao": "ecr",
    "constituicao": "cf",
}
TSIG_TIPO = {v: k for k, v in TIPOS.items()}
NOME_TIPO = {
    "lei": "Lei",
    "lc": "Lei Complementar",
    "dl": "Decreto-Lei",
    "mp": "Medida Provisória",
    "ec": "Emenda Constitucional",
    "ld": "Lei Delegada",
    "ecr": "Emenda Constitucional de Revisão",
    "cf": "Constituição Federal de 1988",
}
PREFIXOS_ARQ = {
    "lei": ("l", "lei"),
    "lc": ("lcp", "lc"),
    "dl": ("del", "dl"),
    "mp": ("mpv", "mp"),
    "ec": ("emc", "ec"),
    "ld": ("ldl",),
    "ecr": ("ecr",),
    "cf": ("constituicao", "constituicaocompilado"),
}
ORDEM_TIPOS = ("lei", "lc", "dl", "mp", "ec", "ld", "ecr", "cf")

PLANALTO_RE = re.compile(r"^https?://(?:www\.)?planalto\.gov\.br/ccivil_03/", re.I)


class ErroAno(ValueError):
    pass


def tsig_de(tipo: str) -> str:
    try:
        return TIPOS[tipo]
    except KeyError:
        raise ValueError(f"tipo desconhecido: {tipo!r}") from None


def caminho_relativo(url: str) -> str:
    """URL absoluta do Planalto -> caminho relativo a ``ccivil_03/`` (sem mudar a caixa)."""
    m = PLANALTO_RE.match(url or "")
    if not m:
        raise ValueError(f"URL fora do Planalto: {url!r}")
    return url[m.end():]


def slug_de(url: str) -> str:
    """Último segmento do caminho, sem ``.htm``/``.html``."""
    seg = (url or "").rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"(?i)\.html?$", "", seg)


def normalizar_espacos(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s.replace(" ", " ")).strip()


# ---------------------------------------------------------------- §5.2 ano
DATA_RE = re.compile(r"de\s+(\d{1,2})º?\s*(?:\.|º\.?|de\s+)\s*(\d{1,2}|[a-zç]+)\s*(?:\.|de\s+)\s*(\d{2,4})", re.I)
FIM_ROTULO_RE = re.compile(r"\.(\d{2,4})\s*$")


def faixa_indice(indice_url: str, ano_ref: int) -> tuple[int, int] | None:
    u = (indice_url or "").lower()
    if "quadro_ecr" in u:
        return (1994, 1994)
    if "quadro_emc" in u:
        return (1992, ano_ref)
    if "quadro_lcp" in u:
        return (1962, ano_ref)
    if "quadro_ldl" in u:
        return (1962, 1992)
    if "decreto-lei" in u:
        m = re.search(r"(\d{4})-(\d{4})/_quadro\.htm$", u)
        if m:
            return (int(m.group(1)), int(m.group(2)))
    m = re.search(r"quadro(?:ant)?(\d{4})-(\d{4})\.htm$", u)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    m = re.search(r"/quadro/(\d{4})-(\d{4})\.htm$", u)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    m = re.search(r"/quadro/(\d{4})\.htm$", u)
    if m:
        a = int(m.group(1))
        return (a, a)
    if "anterior_1960" in u:
        return (1900, 1959)
    m = re.search(r"/(\d{4})/lei/|leis/(\d{4})/|_quadro-(\d{4})", u)
    if m:
        a = int(next(g for g in m.groups() if g))
        return (a, a)
    return None


def faixa_url(url: str) -> tuple[int, int] | None:
    u = url or ""
    m = re.search(r"/(\d{4})-(\d{4})/", u)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    for m in re.finditer(r"/(\d{4})/", u):
        a = int(m.group(1))
        if 1800 < a < 2100:
            return (a, a)
    return None


def ano_bruto(data_txt: str | None, rotulo: str | None) -> int | None:
    for s in (data_txt, rotulo):
        if s:
            m = DATA_RE.search(s)
            if m:
                return int(m.group(3))
    if rotulo:
        m = FIM_ROTULO_RE.search(rotulo)
        if m:
            return int(m.group(1))
    return None


def resolver_ano(a: int | None, faixa: tuple[int, int] | None) -> int | None:
    if a is None or faixa is None:
        return None
    lo, hi = faixa
    if a >= 1000:
        if lo - 1 <= a <= hi + 1:
            return a
        if faixa == (1900, 1959) and a < 1960:
            return a
        return None
    if a < 100:
        cand = [s + a for s in (1800, 1900, 2000) if lo <= s + a <= hi]
        return cand[0] if len(cand) == 1 else None
    return None


def ano_de(rotulo, data_txt, url, indice_url, ano_ref) -> int:
    fi = faixa_indice(indice_url, ano_ref)
    if fi and fi[0] == fi[1]:
        return fi[0]
    a = ano_bruto(data_txt, rotulo)
    r = resolver_ano(a, fi)
    if r is None:
        r = resolver_ano(a, faixa_url(url))
    if r is None:
        raise ErroAno(f"sem ano: rotulo={rotulo!r} data={data_txt!r} url={url!r}")
    return r


# ---------------------------------------------------------------- §5.3 letra, reedição, chave
LETRA_ROTULO_RE = re.compile(r"^\D*[\d.]+\s*-?\s*([A-Z])\b")
LETRA_ARQ_RE = re.compile(r"(?i)^[a-z]*0*[\d.]+[-_]?([a-z])(?=(?:cons|consol|consolidado|compilad[oa]|orig|htm)?$)")


def letra_de(tipo, sufixo, rotulo, url) -> str:
    s = (sufixo or "").strip()
    if len(s) == 1 and s.isalpha():
        return s.lower()
    m = LETRA_ROTULO_RE.match(rotulo or "")
    if m:
        return m.group(1).lower()
    if tipo != "medida provisoria":
        m = LETRA_ARQ_RE.match(slug_de(url or ""))
        if m:
            return m.group(1).lower()
    return ""


def reed_de(tipo, sufixo) -> str:
    if tipo == "medida provisoria":
        m = re.fullmatch(r"-(\d+)", (sufixo or "").strip())
        if m:
            return m.group(1)
    return ""


def chave(tsig, numero, letra, ano) -> str:
    if tsig == "cf":
        return "cf-1988"
    return f"{tsig}-{int(numero)}{letra or ''}-{int(ano)}"


# ---------------------------------------------------------------- §5.4 ementa
VETO_RE = re.compile(r'(?is)\s*\(?\s*mensagem\s+de\s+veto\b.*$')
_STATUS = (r'convertid[ao]|revogad[ao]|sem\s+efic[áa]cia|em\s+tramita[çc][ãa]o|rejeitad[ao]|'
           r'vig[êe]ncia\s+encerrada|prejudicad[ao]|perd(?:a|eu)\s+(?:de\s+)?efic[áa]cia|'
           r'reeditad[ao]|transformad[ao]')
MP_STATUS_RE = re.compile(r'(?:^|(?<=[.;)\]]))\s*(?=[A-ZÀ-Ý])(?i:' + _STATUS + r')\b.*$', re.S)
MP_STATUS_SOLTO_RE = re.compile(
    r'\s(?=[A-ZÀ-Ý])(?i:convertid[ao]\s+(?:na\s+|em\s+)?lei|sem\s+efic[áa]cia|em\s+tramita[çc][ãa]o|'
    r'rejeitad[ao]\s+pel|revogad[ao]\s+(?:pel[ao]\s+)?(?:lei|mpv?|medida))\b.*$', re.S)
MP_STATUS_RESIDUAL_RE = re.compile(r'(?i)\b(?:sem\s+efic[áa]cia|revogad[ao]|convertid[ao]|rejeitad[ao]|'
                                   r'em\s+tramita[çc][ãa]o|vig[êe]ncia\s+encerrada|perd(?:a|eu)\s+(?:de\s+)?efic[áa]cia)\b')
EMENTA_VAZIA = "Ementa não disponível no índice do Planalto."
EMENTA_REVOGAD_OK = frozenset({"lei-1346-1951", "dl-1227-1972"})
C1_RE = re.compile("[\u0080-\u009f]")


def _c1(c: str) -> str:
    try:
        return bytes([ord(c)]).decode("cp1252")
    except UnicodeDecodeError:
        return ""


def limpar_ementa_detalhe(ementa: str | None, tipo: str) -> tuple[str, list[str]]:
    """Como ``limpar_ementa``, devolvendo também os cortes feitos (para o relatório)."""
    cortes: list[str] = []
    s = ementa or ""
    s = C1_RE.sub(lambda m: _c1(m.group(0)), s)
    s = s.replace("�", "")
    s = normalizar_espacos(s)
    novo = VETO_RE.sub("", s)
    if novo != s:
        cortes.append("veto")
        s = novo
    if tipo == "medida provisoria":
        while True:
            antes = s
            novo = MP_STATUS_RE.sub("", s)
            if novo != s:
                cortes.append("status")
                s = novo
            corte = len(s) - 160 if len(s) > 160 else 0
            m = MP_STATUS_SOLTO_RE.search(s, corte)
            if m:
                cortes.append("status_solto")
                s = s[:m.start()]
            s = s.rstrip()
            if s == antes:
                break
    s = s.rstrip(" ;,")
    return s, cortes


def limpar_ementa(ementa: str | None, tipo: str) -> str:
    return limpar_ementa_detalhe(ementa, tipo)[0]


def problemas_ementa(ementa: str, tipo: str, k: str = "") -> list[str]:
    """Gates do §5.4 sobre uma ementa já limpa. Lista vazia = ok."""
    erros = []
    if re.search(r"(?i)mensagem\s+de\s+veto", ementa):
        erros.append("contém 'mensagem de veto'")
    if MP_STATUS_RE.search(ementa):
        erros.append("casa MP_STATUS_RE")
    if tipo in ("medida provisoria", "mp") and MP_STATUS_RESIDUAL_RE.search(ementa[-160:]):
        erros.append("casa MP_STATUS_RESIDUAL_RE nos últimos 160 caracteres")
    if re.search(r"(?i)revogad", ementa):
        if tipo in ("medida provisoria", "mp") or k not in EMENTA_REVOGAD_OK:
            erros.append("contém 'revogad'")
    if C1_RE.search(ementa):
        erros.append("caractere C1")
    return erros


# ---------------------------------------------------------------- §5.5 data
MESES = {m: i for i, m in enumerate(
    ("janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho",
     "agosto", "setembro", "outubro", "novembro", "dezembro"), 1)}


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


def data_iso(data_txt, rotulo, ano) -> str:
    for s in (data_txt, rotulo):
        if not s:
            continue
        m = DATA_RE.search(s)
        if not m:
            continue
        mes_txt = m.group(2)
        if mes_txt.isdigit():
            mes = int(mes_txt)
        else:
            mes = MESES.get(_sem_acento(mes_txt.lower()))
            if mes is None:
                return ""
        try:
            return datetime.date(int(ano), mes, int(m.group(1))).isoformat()
        except (ValueError, TypeError):
            return ""
    return ""


# ---------------------------------------------------------------- §5.6 nome
def numero_milhar(n: int) -> str:
    return f"{int(n):,}".replace(",", ".") if int(n) >= 1000 else str(int(n))


def nome_norma(tsig, numero, letra, reed, ano) -> str:
    if tsig == "cf":
        return NOME_TIPO["cf"]
    s = f"{NOME_TIPO[tsig]} nº {numero_milhar(numero)}"
    if letra:
        s += "-" + letra.upper()
    if reed:
        s += "-" + str(reed)
    return f"{s}/{int(ano)}"


def nome_curto(k: str, nome: str, apelidos: list | None = None) -> str:
    for ap in apelidos or ():
        if ap.get("alvo") == k and ap.get("sigla"):
            return ap["sigla"]
    return nome


# ---------------------------------------------------------------- CF (entrada fixa, §7.2 passo 4)
CF_REGISTRO = {
    "k": "cf-1988", "tipo": "constituicao", "tsig": "cf", "numero": 1988, "letra": "", "reed": "",
    "ano": 1988, "data": "1988-10-05", "rotulo": "Constituição Federal de 1988",
    "ementa": "Constituição da República Federativa do Brasil de 1988.",
    "caminho_indice": "constituicao/constituicao.htm", "indice": "",
}
