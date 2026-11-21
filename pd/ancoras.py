"""Âncoras: verificação do início, reparo da letra solta, parse do dispositivo (SPEC §7.4, §8).

O texto de início de cada âncora só é lido aqui para verificação; nunca é guardado na base.
"""
from __future__ import annotations

import re

ROMANO = r'(?:M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3}))'
ART_RE = re.compile(r'^\s*Art(?:igo)?[\s.]*(\d{1,3}(?:\.\d{3})+|\d+)\s*(?:[º°o]\.?)?\s*(?:[-–]\s*([A-Z])(?=[\s.\-–:(]|$))?')
ART_ESTRITO_LETRA_RE = re.compile(r'^\s*Art(?:igo)?[\s.]*(?:\d{1,3}(?:\.\d{3})+|\d+)(?:[º°o])?[-–]([A-Z])(?![a-zà-ú])')
PAR_RE = re.compile(r'^\s*§\s*(\d+)\s*(?:[º°o]\.?)?\s*(?:[-–]\s*([A-Z])(?![a-zà-ú]))?')
PU_RE = re.compile(r'^\s*Par[áa]grafo\s+[úu]nico', re.I)
INC_RE = re.compile(r'^\s*(' + ROMANO + r')\s*[-–—.)]')
ALI_RE = re.compile(r'^\s*([a-z])\s*[)\-–.]')
ITEM_RE = re.compile(r'^\s*(\d+)\s*[).\-–]')
UNICO_RE = re.compile(r'^\s*Artigo\s+[úu]nico', re.I)

ALFABETO_RE = re.compile(r'^[A-Za-z0-9._§-]+$')
ARTIGO_RE = re.compile(r'^(\d+)(?:-([A-Z]))?$')
REPARO_RE = re.compile(r'^([a-z])((?:§\d+|p|[ivxlc]+|\d+).*)$')

# Dispositivo canônico: artigo | (§N[-X] | pu) | inciso | alínea | item
DISP_CANONICO_RE = re.compile(
    r'^\d+(?:-[A-Z])?'
    r'(?:\|(?:§\d+(?:-[A-Z])?|pu))?'
    r'(?:\|(?!\|)' + ROMANO + r'(?<!\|))?'
    r'(?:\|[a-z])?'
    r'(?:\|\d+)?$')


def ancora_valida(nome: str) -> bool:
    """Alfabeto fechado (G11), sem ``:~:``."""
    return bool(nome) and ":~:" not in nome and bool(ALFABETO_RE.match(nome))


def artigo_canonico(artigo: str) -> str:
    """``'790-b'`` -> ``'790-B'``; ``'0477'`` -> ``'477'``."""
    m = re.fullmatch(r'\s*(\d+)\s*(?:-\s*([A-Za-z]))?\s*', artigo or "")
    if not m:
        raise ValueError(f"artigo inválido: {artigo!r}")
    s = str(int(m.group(1)))
    if m.group(2):
        s += "-" + m.group(2).upper()
    return s


def disp_canonico_valido(s: str) -> bool:
    if not isinstance(s, str) or not DISP_CANONICO_RE.match(s):
        return False
    partes = s.split("|")
    # a fronteira do romano: componente vazio não é inciso
    return all(p for p in partes)


def _base_letra(artigo: str) -> tuple[str, str]:
    m = ARTIGO_RE.match(artigo)
    if not m:
        raise ValueError(f"artigo inválido: {artigo!r}")
    return m.group(1), m.group(2) or ""


def _numero(s: str) -> str:
    """Número sem pontos de milhar e sem zeros à esquerda: ``'01'`` -> ``'1'``; ``'1.022'`` -> ``'1022'``."""
    return str(int(s.replace(".", "")))


def artigo_confere(artigo: str, inicio: str) -> bool:
    ini = inicio or ""
    if ini.lstrip().startswith(('"', '“')):
        return False
    base, letra = _base_letra(artigo)
    base = _numero(base)  # o extrator às vezes grava "01" (âncora art01 → "Art. 1º")
    if base == "1" and not letra and UNICO_RE.match(ini):
        return True
    m = ART_RE.match(ini)
    if not m:
        return False
    if _numero(m.group(1)) != base:
        return False
    if letra:
        return m.group(2) == letra
    return not ART_ESTRITO_LETRA_RE.match(ini)


def ultimo_componente_confere(comp: tuple[str, str], inicio: str) -> bool:
    tipo, v = comp
    ini = inicio or ""
    if tipo == "par":
        m = PAR_RE.match(ini)
        if not m:
            return False
        if "-" in v:
            n, x = v.split("-", 1)
            return m.group(1) == n and m.group(2) == x
        return m.group(1) == v and not m.group(2)
    if tipo == "pu":
        return bool(PU_RE.match(ini))
    if tipo == "inc":
        m = INC_RE.match(ini)
        return bool(m) and m.group(1) == v
    if tipo == "ali":
        m = ALI_RE.match(ini)
        return bool(m) and m.group(1) == v
    if tipo == "item":
        m = ITEM_RE.match(ini)
        return bool(m) and m.group(1) == v
    return False


def parse_disp(d: str, ini: str) -> list[tuple[str, str]] | None:
    """Pseudocódigo normativo do §7.4.4."""
    comps: list[tuple[str, str]] = []
    r = d
    m = re.match(r'^§(\d+)', r)
    if m:
        r = r[m.end():]
        pm = PAR_RE.match(ini or "")
        if r[:1].isalpha() and pm and pm.group(1) == m.group(1) and pm.group(2) == r[0].upper():
            comps.append(('par', f"{m.group(1)}-{r[0].upper()}"))
            r = r[1:]
        else:
            comps.append(('par', m.group(1)))
    elif r.startswith('p'):
        comps.append(('pu', ''))
        r = r[1:]
    saidas = set()
    for i in range(len(r) + 1):
        R = r[:i]
        if R and not re.fullmatch(ROMANO, R.upper()):
            continue
        for j in (0, 1):
            L, D = r[i:i + j], r[i + j:]
            if j and not (len(L) == 1 and L.isalpha()):
                continue
            if D and not D.isdigit():
                continue
            c = comps + ([('inc', R.upper())] if R else []) + ([('ali', L)] if L else []) + ([('item', D)] if D else [])
            if c and ultimo_componente_confere(c[-1], ini):
                saidas.add(tuple(c))
    return list(saidas.pop()) if len(saidas) == 1 else None


def formata(comp: tuple[str, str]) -> str:
    tipo, v = comp
    if tipo == "par":
        return "§" + v
    if tipo == "pu":
        return "pu"
    return v


def disp_canonico(artigo: str, comps) -> str:
    return "|".join([artigo_canonico(artigo)] + [formata(c) for c in (comps or ())])


def reparar_letra(artigo: str, disp: str, inicio: str, arts_com_letra) -> tuple[str, str, str]:
    """Reparos do §7.4.3. Devolve ``(artigo, disp, motivo)``; motivo '' = sem reparo."""
    ini = inicio or ""
    m = REPARO_RE.match(disp or "")
    if m and not ini.lstrip().startswith("Art"):
        cand = f"{artigo}-{m.group(1).upper()}"
        if cand in arts_com_letra:
            return cand, m.group(2), "reparo1"
    if disp and len(disp) == 1 and disp.isalpha() and "-" not in artigo:
        cand = f"{artigo}-{disp.upper()}"
        if artigo_confere(cand, ini):
            return cand, "", "reparo2"
    return artigo, disp, ""


def verificar(artigo: str, disp: str, inicio: str) -> tuple[str | None, str]:
    """Devolve ``(dispositivo canônico, '')`` se confere, ou ``(None, motivo)``."""
    try:
        art = artigo_canonico(artigo)
    except ValueError:
        return None, "disp não interpretável"
    if not disp:
        if ARTIGO_RE.match(artigo or "") and artigo_confere(artigo, inicio):
            return art, ""
        return None, "inicio reprovado (artigo)"
    comps = parse_disp(disp, inicio)
    if comps is None:
        return None, "inicio reprovado (dispositivo) ou disp ambíguo"
    return disp_canonico(art, comps), ""


def pontos_variante(nome: str) -> int:
    return nome.count(".")
