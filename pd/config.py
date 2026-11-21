"""Leitura do ponto único de configuração ``docs/config.js`` (SPEC §4)."""
from __future__ import annotations

import pathlib
import re

CHAVES = ("PLANALTO_BASE", "SITE_URL", "SITE_PATH", "REPO_URL", "SUGESTAO_ATIVA", "SUGESTAO_URL",
          "SUGESTAO_CAMPO", "GOOGLE_VERIFICACAO", "ESPERA_MS", "ESPERA_DICA_MS")
LINHA_RE = re.compile(r'^\s*([A-Z_]+)\s*:\s*"((?:[^"\\]|\\.)*)"\s*,?\s*$')

RAIZ = pathlib.Path(__file__).resolve().parents[1]


class ErroConfig(ValueError):
    pass


def _desescapar(v: str) -> str:
    return re.sub(r'\\(.)', lambda m: m.group(1), v)


def ler_config(caminho: str = "docs/config.js") -> dict[str, str]:
    """Lê e valida ``docs/config.js``. Caminho relativo é resolvido contra a raiz do repo."""
    p = pathlib.Path(caminho)
    if not p.is_absolute() and not p.exists():
        p = RAIZ / p
    texto = p.read_text(encoding="utf-8")
    if texto.startswith("﻿"):
        texto = texto[1:]
    cfg: dict[str, str] = {}
    for linha in texto.splitlines():
        m = LINHA_RE.match(linha)
        if not m:
            continue
        nome, valor = m.group(1), _desescapar(m.group(2))
        if nome in cfg:
            raise ErroConfig(f"config.js: chave repetida: {nome}")
        cfg[nome] = valor
    faltam = [c for c in CHAVES if c not in cfg]
    if faltam:
        raise ErroConfig(f"config.js: faltam chaves: {', '.join(faltam)}")
    extras = sorted(set(cfg) - set(CHAVES))
    if extras:
        raise ErroConfig(f"config.js: chaves desconhecidas: {', '.join(extras)}")
    validar_config(cfg)
    return cfg


def validar_config(cfg: dict[str, str]) -> None:
    for c in ("PLANALTO_BASE", "SITE_URL"):
        v = cfg[c]
        if not (v.startswith("https://") and v.endswith("/")):
            raise ErroConfig(f"config.js: {c} precisa começar com https:// e terminar com /")
    sp = cfg["SITE_PATH"]
    if not (sp.startswith("/") and sp.endswith("/")):
        raise ErroConfig("config.js: SITE_PATH precisa começar e terminar com /")
    if not cfg["SITE_URL"].endswith(sp):
        raise ErroConfig("config.js: SITE_URL precisa terminar com SITE_PATH")
    if cfg["SUGESTAO_ATIVA"] not in ("sim", "nao"):
        raise ErroConfig('config.js: SUGESTAO_ATIVA precisa ser "sim" ou "nao"')
    campo = cfg["SUGESTAO_CAMPO"]
    if campo and not re.fullmatch(r"entry\.\d+", campo):
        raise ErroConfig("config.js: SUGESTAO_CAMPO precisa ser vazio ou entry.NNN")
    url = cfg["SUGESTAO_URL"]
    if url and not url.startswith("https://docs.google.com/forms/"):
        raise ErroConfig("config.js: SUGESTAO_URL precisa ser vazio ou um link do Google Forms")
