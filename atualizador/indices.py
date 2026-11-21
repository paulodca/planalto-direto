"""Leitura dos índices (quadros) do Planalto: árvore mínima de tabelas e registros brutos.

Só biblioteca padrão (``html.parser``). Tolera o HTML do FrontPage/Word sem
fechamentos. Não converte página de lei em texto: lê só as tabelas dos índices.
"""
from __future__ import annotations

import html.parser
import re
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit

# Uma linha da tabela é uma lista de células; cada célula é
# {"texto": str, "links": [(href, texto), ...]}.
RAIZ = Path(__file__).resolve().parents[1]

Celula = dict
Linha = list
RegistroBruto = dict

_ESPACOS = re.compile(r"\s+")
_IGNORAR = {"script", "style"}
_QUEBRA = {"br", "p", "div", "li", "hr"}

INDICE_RE = re.compile(r"/_?quadro|/_leis\d{4}\.htm|principal|_lei-|quadro_", re.I)
FORA_RE = re.compile(r"/(?:msg|vep|exm)/|\.pdf$", re.I)
PREFIXO_ROTULO_RE = re.compile(
    r"^(?:Lei|Decreto-Lei|Medida Provis[óo]ria|Lei Complementar|Emenda Constitucional)[^\d]*", re.I)
ROTULO_RE = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+)(?:\s*-\s*([A-Z])\b|-(\d+))?")
# Regra ARQ (regra A do §9.3), aplicada ao nome do arquivo em minúsculas.
ARQ_RE = re.compile(
    r"^(l|lei|del|dl|lcp|lc|mpv|mp|emc|ec|ecr|ldl)0*(\d{1,3}(?:\.\d{3})+|\d+)(?:-?([a-z]))?(?:-(\d+))?"
    r"(cons|consol|consolidado|compilado|compilada|orig|consimpressao|impressao)?(?:\.html?)?$")
# MP: o nome do arquivo pode trazer o número sem prefixo ("1456.htm", "2158-35.htm").
ARQ_MP_RE = re.compile(r"^(?:mpv?)?0*(\d{1,3}(?:\.\d{3})+|\d+)(?:-?([a-z]))?(?:-(\d+))?(?=[a-z]*(?:\.html?)?$)")

RESTO_ROTULO_RE = re.compile(r"^[\s,;]*de\s+\d")

NOVO_BUCKET_RES = (
    re.compile(r"(?i)^_Ato\d{4}-\d{4}/\d{4}/Lei/_leis\d{4}\.htm$"),
    re.compile(r"(?i)^MPV/Quadro/_Quadro\d{4}-\d{4}\.htm$"),
)


def decodificar(raw: bytes) -> str:
    """Charset pela meta tag; tudo que não é UTF-8 vira cp1252 (``pd.cache_html``)."""
    from pd.cache_html import decodificar as _dec
    return _dec(raw)


def _colapsar(s: str) -> str:
    return _ESPACOS.sub(" ", s).strip()


class _Tabela:
    __slots__ = ("linha", "celula")

    def __init__(self):
        self.linha: list | None = None
        self.celula: dict | None = None


class ExtratorTabela(html.parser.HTMLParser):
    """Árvore mínima com pilha de tabelas. ``linhas`` fica em ordem de abertura."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.linhas: list[Linha] = []
        self._pilha: list[_Tabela] = []
        self._ignorar = 0
        self._link: dict | None = None   # link aberto: {"href", "partes", "celula"}

    # células e linhas ---------------------------------------------------
    def _fechar_link(self) -> None:
        lk = self._link
        if lk is not None:
            lk["celula"]["links"].append((lk["href"], _colapsar("".join(lk["partes"]))))
            self._link = None

    def _fechar_celula(self, t: _Tabela) -> None:
        if t.celula is not None:
            if self._link is not None and self._link["celula"] is t.celula:
                self._fechar_link()
            t.celula["texto"] = _colapsar("".join(t.celula.pop("partes")))
            t.celula = None

    def _fechar_linha(self, t: _Tabela) -> None:
        self._fechar_celula(t)
        t.linha = None

    def _abrir_linha(self, t: _Tabela) -> None:
        self._fechar_linha(t)
        t.linha = []
        self.linhas.append(t.linha)

    def _abrir_celula(self, t: _Tabela) -> None:
        self._fechar_celula(t)
        if t.linha is None:
            self._abrir_linha(t)
        t.celula = {"texto": "", "links": [], "partes": []}
        t.linha.append(t.celula)

    def _celula_aberta(self) -> dict | None:
        return self._pilha[-1].celula if self._pilha else None

    def _texto(self, s: str) -> None:
        c = self._celula_aberta()
        if c is None:
            return
        c["partes"].append(s)
        if self._link is not None and self._link["celula"] is c:
            self._link["partes"].append(s)

    # eventos do parser ----------------------------------------------------
    def handle_starttag(self, tag, attrs):
        if tag in _IGNORAR:
            self._ignorar += 1
            return
        if tag == "table":
            self._pilha.append(_Tabela())
        elif tag == "tr":
            if self._pilha:
                self._abrir_linha(self._pilha[-1])
        elif tag in ("td", "th"):
            if self._pilha:
                self._abrir_celula(self._pilha[-1])
        elif tag == "a":
            self._fechar_link()
            c = self._celula_aberta()
            href = dict(attrs).get("href")
            if c is not None and href:
                self._link = {"href": href.strip(), "partes": [], "celula": c}
        elif tag in _QUEBRA:
            self._texto(" ")

    def handle_startendtag(self, tag, attrs):
        if tag in _QUEBRA:
            self._texto(" ")
        elif tag == "a":
            self.handle_starttag(tag, attrs)
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in _IGNORAR:
            if self._ignorar:
                self._ignorar -= 1
            return
        if tag == "table":
            if self._pilha:
                t = self._pilha.pop()
                self._fechar_linha(t)
        elif tag == "tr":
            if self._pilha:
                self._fechar_linha(self._pilha[-1])
        elif tag in ("td", "th"):
            if self._pilha:
                self._fechar_celula(self._pilha[-1])
        elif tag == "a":
            self._fechar_link()
        elif tag in ("p", "div", "li"):
            self._texto(" ")

    def handle_data(self, data):
        if not self._ignorar:
            self._texto(data)

    def close(self):
        super().close()
        while self._pilha:
            self._fechar_linha(self._pilha.pop())
        self.linhas = [ln for ln in self.linhas if ln]


def linhas_do_indice(html_txt: str) -> list[Linha]:
    p = ExtratorTabela()
    p.feed(html_txt)
    p.close()
    return p.linhas


# ------------------------------------------------------------------- URLs
def relativo_da_base(url_abs: str, base: str) -> str | None:
    """Caminho relativo a ``base`` (caixa original), ou None se a URL não está sob a base.

    A comparação ignora o esquema (http/https) e a caixa do host e do caminho da base.
    """
    u, b = urlsplit(url_abs), urlsplit(base)
    if u.netloc.lower() != b.netloc.lower():
        return None
    if not u.path.lower().startswith(b.path.lower()):
        return None
    return u.path[len(b.path):]


def absoluto(caminho_rel_ou_url: str, base: str) -> str:
    if re.match(r"(?i)^https?://", caminho_rel_ou_url):
        return caminho_rel_ou_url
    return base + caminho_rel_ou_url.lstrip("/")


def link_de_norma(href: str, texto: str, url_indice_abs: str, base: str) -> str | None:
    """Caminho relativo da norma se o link passa nos critérios (a)–(e) do §13.5."""
    if not href or not re.search(r"\d", texto or ""):
        return None
    alvo = urldefrag(urljoin(url_indice_abs, href))[0]
    rel = relativo_da_base(alvo, base)
    if not rel:
        return None
    caminho = urlsplit(alvo).path
    if not re.search(r"(?i)\.html?$", caminho):
        return None
    if INDICE_RE.search(caminho) or FORA_RE.search(caminho):
        return None
    if urlsplit(alvo).query:
        return None
    return rel


def _nome_arquivo(caminho: str) -> str:
    return caminho.rsplit("/", 1)[-1].lower()


def numero_do_arquivo(caminho: str, mp: bool) -> tuple[int, str, str] | None:
    """(numero, letra, reed) pelo nome do arquivo; None se não houver."""
    nome = _nome_arquivo(caminho)
    m = ARQ_RE.match(nome)
    if m:
        return int(m.group(2).replace(".", "")), (m.group(3) or ""), (m.group(4) or "")
    if mp:
        m = ARQ_MP_RE.match(nome)
        if m:
            return int(m.group(1).replace(".", "")), (m.group(2) or ""), (m.group(3) or "")
    return None


def numero_do_rotulo(rotulo: str) -> tuple[int, str, str] | None:
    resto = PREFIXO_ROTULO_RE.sub("", rotulo, count=1)
    m = ROTULO_RE.search(resto)
    if not m:
        return None
    return int(m.group(1).replace(".", "")), (m.group(2) or "").lower(), (m.group(3) or "")


def _numero(rotulo: str, rel: str, mp: bool):
    """(numero, letra, reed) e nota de divergência. O nome do arquivo prevalece sobre o rótulo."""
    pelo_rotulo = numero_do_rotulo(rotulo)
    pelo_arquivo = numero_do_arquivo(rel, mp)
    if pelo_arquivo is None:
        return pelo_rotulo, ""
    if pelo_rotulo is None:
        return pelo_arquivo, ""
    if pelo_rotulo[0] == pelo_arquivo[0]:
        return (pelo_arquivo[0], pelo_rotulo[1] or pelo_arquivo[1], pelo_rotulo[2] or pelo_arquivo[2]), ""
    nota = f"rótulo diz {pelo_rotulo[0]}, arquivo diz {pelo_arquivo[0]}: vale o arquivo"
    return pelo_arquivo, nota


def registros_do_indice(html_txt: str, url_indice: str, tipo: str, base: str | None = None) -> list[RegistroBruto]:
    """Registros brutos (uma norma por linha de tabela) de um índice.

    ``url_indice``: caminho relativo a ``base`` ou URL absoluta. ``base``:
    ``PLANALTO_BASE`` (lida de ``docs/config.js`` se omitida).
    Campos: url, rotulo, data_txt, ementa (bruta, da 2ª célula), tipo, indice,
    numero, sufixo, divergencia (texto ou '').
    """
    from pd import normas
    if base is None:
        from pd.config import ler_config
        base = ler_config(str(RAIZ / "docs" / "config.js"))["PLANALTO_BASE"]
    url_indice_abs = absoluto(url_indice, base)
    indice_rel = relativo_da_base(url_indice_abs, base) or url_indice
    mp = tipo == "medida provisoria"
    saida: list[RegistroBruto] = []
    for linha in linhas_do_indice(html_txt):
        cel1 = linha[0]
        validos = []
        for href, texto in cel1["links"]:
            rel = link_de_norma(href, texto, url_indice_abs, base)
            if not rel or rel.lower() in {v[0].lower() for v in validos}:
                continue
            # Além do 1º link, só entra o "rótulo partido" (", de 22.11.1946" apontando para outra
            # norma): links de situação ("... pela Medida Provisória nº N") ficam de fora.
            if not validos or RESTO_ROTULO_RE.match(_colapsar(texto)):
                validos.append((rel, _colapsar(texto)))
        if not validos:
            continue
        m = normas.DATA_RE.search(cel1["texto"])
        data_txt = m.group(0) if m else None
        ementa = linha[1]["texto"] if len(linha) > 1 else ""
        for rel, rotulo in validos:
            num, divergencia = _numero(rotulo, rel, mp)
            if num is None:
                continue
            numero, letra, reed = num
            sufixo = f"-{reed}" if reed else ("" if mp else letra)
            saida.append({
                "url": rel, "rotulo": rotulo, "data_txt": data_txt, "ementa": ementa, "tipo": tipo,
                "indice": indice_rel, "numero": numero, "sufixo": sufixo, "divergencia": divergencia,
            })
    return saida


def novos_buckets(html_txt: str, url_nav: str, conhecidos: set[str], base: str) -> list[str]:
    """Buckets novos (fora de ``conhecidos``, comparação em minúsculas) linkados numa página de navegação."""
    url_abs = absoluto(url_nav, base)
    p = _ColetorLinks()
    p.feed(html_txt)
    p.close()
    achados: list[str] = []
    vistos = {c.lower() for c in conhecidos}
    for href in p.hrefs:
        rel = relativo_da_base(urldefrag(urljoin(url_abs, href))[0], base)
        if not rel or not any(r.match(rel) for r in NOVO_BUCKET_RES):
            continue
        if rel.lower() not in vistos:
            vistos.add(rel.lower())
            achados.append(rel)
    return achados


class _ColetorLinks(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            h = dict(attrs).get("href")
            if h:
                self.hrefs.append(h.strip())
