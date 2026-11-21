"""Páginas do Planalto guardadas localmente: decodificação, caminho e âncoras (SPEC §7.4.1a, §13.5)."""
from __future__ import annotations

import html.parser
import pathlib
import re

META_CHARSET_RE = re.compile(rb'charset\s*=\s*["\']?([\w-]+)', re.I)

HOST = "www.planalto.gov.br"
PASTA = "ccivil_03"

VAZIOS = frozenset("br img meta link hr input wbr area base col embed source track param".split())
TAGS_RISCADAS = frozenset(("s", "strike", "del"))


def decodificar(raw: bytes) -> str:
    """cp1252, salvo ``utf-8``/``utf8`` declarado nos primeiros 4.096 bytes."""
    m = META_CHARSET_RE.search(raw[:4096])
    if m and m.group(1).decode("ascii", "replace").lower() in ("utf-8", "utf8"):
        return raw.decode("utf-8", "replace")
    return raw.decode("cp1252", "replace")


def caminho_no_cache(raiz, caminho_rel: str) -> pathlib.Path:
    """``<raiz>/www.planalto.gov.br/ccivil_03/<caminho_rel em minúsculas>``."""
    rel = caminho_rel.replace("\\", "/").lstrip("/").lower()
    return pathlib.Path(raiz) / HOST / PASTA / pathlib.PurePosixPath(rel)


def _riscado(tag: str, attrs: dict) -> bool:
    if tag in TAGS_RISCADAS:
        return True
    estilo = attrs.get("style") or ""
    return "line-through" in estilo.lower().replace(" ", "")


class _Varredor(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pilha: list[tuple[str, bool]] = []
        self.por_a: dict[str, bool | None] = {}      # nome -> riscado seguinte (1ª <a>)
        self.por_id: dict[str, bool | None] = {}     # id de outro elemento (fallback)
        self.pend_a: list[str] = []
        self.pend_id: list[str] = []

    def _marcar(self, tag: str, attrs: dict) -> None:
        if tag == "a":
            for chave in ("name", "id"):
                v = attrs.get(chave)
                if v and v not in self.por_a:
                    self.por_a[v] = None
                    self.pend_a.append(v)
        else:
            v = attrs.get("id")
            if v and v not in self.por_id:
                self.por_id[v] = None
                self.pend_id.append(v)

    def _abrir(self, tag, attrs_l, empilhar: bool) -> None:
        attrs = {}
        for k, v in attrs_l:
            if k not in attrs:
                attrs[k] = v
        if empilhar and tag not in VAZIOS and not (tag == "a" and "href" not in attrs):
            self.pilha.append((tag, _riscado(tag, attrs)))
        self._marcar(tag, attrs)

    def handle_starttag(self, tag, attrs):
        self._abrir(tag, attrs, True)

    def handle_startendtag(self, tag, attrs):
        self._abrir(tag, attrs, False)

    def handle_endtag(self, tag):
        for i in range(len(self.pilha) - 1, -1, -1):
            if self.pilha[i][0] == tag:
                del self.pilha[i:]
                return

    def handle_data(self, data):
        if not (self.pend_a or self.pend_id) or not data.strip():
            return
        r = any(x for _, x in self.pilha)
        for n in self.pend_a:
            self.por_a[n] = r
        for n in self.pend_id:
            self.por_id[n] = r
        self.pend_a = []
        self.pend_id = []


def ancoras_da_pagina(html_txt: str) -> dict[str, bool | None]:
    """Mapa nome da âncora -> o 1º texto não vazio depois dela está riscado?

    ``None`` = não há texto depois. A 1ª ``<a>`` com ``name``/``id`` igual manda;
    um ``id`` de outro elemento só vale se nenhuma ``<a>`` tiver o nome.
    """
    v = _Varredor()
    v.feed(html_txt)
    v.close()
    saida = dict(v.por_id)
    saida.update(v.por_a)
    return saida
