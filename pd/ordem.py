"""Ordem canônica de chave e ordem pública de candidatos (SPEC §5.3, §7.6, §9.5)."""
from __future__ import annotations

import re

ORDEM_TIPOS = ("lei", "lc", "dl", "mp", "ec", "ld", "ecr", "cf")
_POS = {t: i for i, t in enumerate(ORDEM_TIPOS)}

CHAVE_RE = re.compile(r"^(lei|lc|dl|mp|ec|ld|ecr)-(\d+)([a-z]?)-(\d{4})$")
CHAVE_CF = "cf-1988"
GRUPO_RE = re.compile(r"^(num|lei|lc|dl|mp|ec|ld|ecr|cf):(\d+)([a-z]?)$")


def partes_chave(k: str) -> tuple[str, int, str, int]:
    """``'lei-5467a-1968'`` -> ``('lei', 5467, 'a', 1968)``; ``'cf-1988'`` -> ``('cf', 1988, '', 1988)``."""
    if k == CHAVE_CF:
        return ("cf", 1988, "", 1988)
    m = CHAVE_RE.match(k)
    if not m:
        raise ValueError(f"chave inválida: {k!r}")
    return (m.group(1), int(m.group(2)), m.group(3), int(m.group(4)))


def chave_valida(k: str) -> bool:
    return k == CHAVE_CF or bool(CHAVE_RE.match(k))


def ordem_chave(k: str) -> tuple[int, int, str, int]:
    """Tupla (posição do tipo, número, letra, ano)."""
    t, n, l, a = partes_chave(k)
    return (_POS[t], n, l, a)


def _k(x) -> str:
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        return x["k"]
    return getattr(x, "k")


def chave_ordem_publica(x, alvos_apelido=frozenset()) -> tuple:
    """Alvo de apelido primeiro; depois tipo (§5.1); ano DESC; ordem canônica de chave."""
    k = _k(x)
    t, n, l, a = partes_chave(k)
    return (0 if k in alvos_apelido else 1, _POS[t], -a, ordem_chave(k))


def ordem_publica(grupo, alvos_apelido=frozenset()) -> list:
    """Ordena ``grupo`` (chaves, dicts com ``k`` ou objetos com ``.k``). O ano sai da chave."""
    alvos = set(alvos_apelido or ())
    return sorted(grupo, key=lambda x: chave_ordem_publica(x, alvos))


def ordem_grupo(g: str) -> tuple:
    """Ordem canônica de grupo de desempate: ``num:`` primeiro, depois (tipo, número, letra)."""
    m = GRUPO_RE.match(g)
    if not m:
        raise ValueError(f"grupo inválido: {g!r}")
    t = m.group(1)
    return (0 if t == "num" else 1, -1 if t == "num" else _POS[t], int(m.group(2)), m.group(3))
