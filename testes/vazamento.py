"""(d) Vazamento e (c) marcas proibidas (SPEC §14.5 e §11).

Uso:
  python -P -B testes/vazamento.py --termos-proibidos ARQ [--lista-privada ARQ ...] [--ancoras ARQ]
                                   [--historico] [--json ARQ]
  python -P -B testes/vazamento.py --marcas [--json ARQ]

Insumos privados só por argumento ou variável de ambiente (PD_TERMOS_PROIBIDOS, PD_LISTA_PRIVADA
separada por ';', PD_ANCORAS). Nada do que eles contêm é gravado: a saída mostra arquivo:linha e o
achado mascarado no meio; o valor de um token nunca é impresso.

Conjunto varrido = o que iria para o push, ``git ls-files --cached --others --exclude-standard -z``,
mais todo o docs/ local: o site gerado é ignorado pelo git (o Actions o gera e publica), mas é o
que vai ao ar. O mínimo de 50 arquivos vale para a parte do git (sem git: varredura da pasta, sem .git, .estado, testes/.saida, __pycache__, node_modules).

Os padrões deste arquivo são montados por concatenação, para que o próprio fonte não case consigo.
Códigos de saída: 0 PASS, 1 FAIL, 2 erro de uso, 77 SKIP (termos externos não fornecidos).
"""
from __future__ import annotations

import sys
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import argparse
import html.parser
import json
import os
import re
import subprocess

MIN_ARQUIVOS = 50
TSIGS = ("lei", "lc", "dl", "mp", "ec", "ld", "ecr", "cf")
EMENTA_REVOGAD_OK = frozenset({"lei-1346-1951", "dl-1227-1972"})
EXCLUIR_DIRS = {".git", ".estado", "__pycache__", "node_modules"}
BARRA = "\\"
ARROBA = "@"
DOIS_PONTOS = ":"

# ------------------------------------------------------------------ 1. padrões genéricos
# a. caminho de disco
P_DISCO = [
    ("1a-disco", re.compile(r"(?<![A-Za-z0-9])[A-Za-z]" + DOIS_PONTOS + BARRA * 2)),
    ("1a-disco", re.compile(r"(?<![A-Za-z0-9/])[A-Za-z]" + DOIS_PONTOS + "/(?!/)")),
    ("1a-disco", re.compile(r"(?i)(?<![\w.])/(?:mnt/)?[a-z]/(?:" + "us" + "ers|plan" + "alto|trab" + "alho)")),
]
# b. e-mail (só noreply do GitHub)
P_EMAIL = re.compile(r"[\w.+-]+" + ARROBA + r"[\w-]+\.[\w.-]+")
P_EMAIL_OK = re.compile(r"^[\w.+-]+" + ARROBA + r"users\.noreply\.github\.com$")
# c. tokens e segredos
P_SEGREDO = [
    ("1c-token", re.compile("gh" + r"[pousr]_[A-Za-z0-9]{30,}")),
    ("1c-token", re.compile("github" + r"_pat_[A-Za-z0-9_]{20,}")),
    ("1c-token", re.compile("AK" + r"IA[0-9A-Z]{16}")),
    ("1c-token", re.compile("xo" + r"x[abprs]-[A-Za-z0-9-]{10,}")),
    ("1c-token", re.compile("s" + r"k-[A-Za-z0-9]{20,}")),
    ("1c-token", re.compile("-----BEGIN " + r"[A-Z ]*PRIVATE KEY-----")),
    ("1c-token", re.compile(r"(?i)(?:tok" + r"en|sec" + r"ret|sen" + r"ha|pass" + r"word|api[_-]?key)\s*[:=]\s*[\"'][^\"'\s]{12,}[\"']")),
]
ENV_TOKENS = ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT")
# d. processo CNJ
P_CNJ = [
    ("1d-cnj", re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")),
    ("1d-cnj", re.compile(r"(?<![0-9A-Fa-f])\d{20}(?![0-9A-Fa-f])")),
]
# e. nomes de campo proibidos (§6)
CAMPOS = ("ord" + "em", "ori" + "gem", "ra" + "nk", "sc" + "ore", "pos" + "icao", "men" + "coes", "cit" + "acoes",
          "ini" + "cio", "ris" + "cado", "so_ris" + "cada", "altern" + "ativas", "revo" + "gada", "ordem" + "_doc",
          "ca" + "che", "url_" + "pedida")
P_CAMPOS = [("1e-campo", re.compile('"' + c + '"' + r"\s*" + DOIS_PONTOS)) for c in CAMPOS]
# f. fragmento de texto
P_FRAG = [("1f-fragmento", re.compile(re.escape(":~" + ":text="))), ("1f-fragmento", re.compile(re.escape("#:~" + ":")))]
# g. terceiros e analytics
P_TERCEIROS = [("1g-terceiros", re.compile(re.escape(s))) for s in (
    "fonts.goo" + "gleapis", "fonts.gst" + "atic", "google-an" + "alytics", "googleta" + "gmanager", "gta" + "g(",
    "plaus" + "ible", "mat" + "omo", "hot" + "jar", "clarity" + ".ms")]
# h. status proibido (I4)
P_REVOGAD = re.compile("(?i)revo" + "gad")
# i. veto
P_VETO = re.compile("(?i)mensagem" + " de veto")

EMENTA_LUGARES_RE = re.compile(
    r'<p class="ementa">.*?</p>|<meta name="description" content="[^"]*">|<meta property="og:description" content="[^"]*">',
    re.S)
ROTA_RE = re.compile(r"^docs/(" + "|".join(TSIGS) + r")/(\d+)([a-z]?)-(\d{4})/index\.html$")
CHAVE_SEQ_RE = re.compile(r"\b(?:lei|lc|dl|mp|ec|ld|ecr)-\d+[a-z]?-\d{4}\b|\bcf-1988\b"
                          r"|/(?:lei|lc|dl|mp|ec|ld|ecr|cf)/\d+[a-z]?-\d{4}/")
ROTA_SEQ_RE = re.compile(r"^/(\w+)/(\d+[a-z]?)-(\d{4})/$")
PLANALTO_RE = re.compile(r"(?i)^https?://(?:www\.)?planalto\.gov\.br/ccivil_03/")

# ------------------------------------------------------------------ marcas (§11)
# 21/11/2026: o dono autorizou as cores do logo e a fonte Google Sans (OFL, servida pelo próprio site) na marca;
# continuam proibidas as cores do gov.br, a Product Sans (proprietária), fontes de CDN e a palavra visível.
HEX_PROIBIDOS = ("1351B4", "071D41", "2670E8")
FONTES_PROIBIDAS = ("Product" + " Sans", "Raw" + "line")
HOSTS_PROIBIDOS = ("fonts.goo" + "gleapis.com", "fonts.gst" + "atic.com", "barra.sistema." + "gov.br", "gov" + ".br/ds")


def _rgb(hx: str) -> re.Pattern:
    r, g, b = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
    return re.compile(r"rgba?\(\s*" + rf"{r}\s*,\s*{g}\s*,\s*{b}" + r"\s*[,)]")


P_MARCAS = ([("marca-hex", re.compile("(?i)#" + h + r"\b")) for h in HEX_PROIBIDOS]
            + [("marca-rgb", _rgb(h)) for h in HEX_PROIBIDOS]
            + [("marca-fonte", re.compile("(?i)" + re.escape(f))) for f in FONTES_PROIBIDAS]
            + [("marca-fonte", re.compile(r"(?i)font-family\s*:\s*[\"']?Rob" + "oto"))]
            + [("marca-host", re.compile("(?i)" + re.escape(h))) for h in HOSTS_PROIBIDOS])
P_VISIVEL = [
    ("marca-palavra", re.compile(r"(?i)\bGoo" + r"gle\b")),
    ("marca-palavra", re.compile(r"(?i)(?<![\w.])gov\.br\b")),
    ("marca-palavra", re.compile(r"(?i)\bbras(?:ã|a)o\b")),
    ("marca-palavra", re.compile(r"(?i)Rep[úu]blica Federativa")),
]


# ------------------------------------------------------------------ utilidades
def mascarar(s: str) -> str:
    s = s.replace("\n", " ")
    if len(s) <= 6:
        return s[:1] + "…"
    return s[:3] + "…" + s[-2:]


def _linha(texto: str, pos: int) -> int:
    return texto.count("\n", 0, pos) + 1


class Relatorio:
    def __init__(self):
        self.achados: list[dict] = []
        self.notas: list[str] = []
        self.falhas_gerais: list[str] = []

    def achar(self, padrao: str, arquivo: str, linha: int, trecho: str, segredo: bool = False):
        self.achados.append({"padrao": padrao, "arquivo": arquivo, "linha": linha,
                             "trecho": "(oculto)" if segredo else mascarar(trecho)})


def _site_gerado(raiz: pathlib.Path) -> list[str]:
    """Todo arquivo de docs/: o site gerado não vai para o git (o Actions o gera), mas é o que vai ao ar."""
    docs = raiz / "docs"
    if not docs.is_dir():
        return []
    return [p.relative_to(raiz).as_posix() for p in docs.rglob("*") if p.is_file()]


def listar_arquivos(raiz: pathlib.Path) -> tuple[list[str], str, int]:
    """(arquivos varridos, método, quantos iriam para o push). O mínimo de 50 vale para o 3º."""
    try:
        r = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                           cwd=raiz, capture_output=True, timeout=120)
        if r.returncode == 0:
            rels = {x for x in r.stdout.decode("utf-8", "replace").split("\0") if x}
            n_git = len(rels)
            rels.update(_site_gerado(raiz))
            return (sorted(x for x in rels if (raiz / x).is_file()),
                    f"git ls-files ({n_git}) + docs/ gerado", n_git)
    except (OSError, subprocess.SubprocessError):
        pass
    saida = []
    for dirpath, dirnames, filenames in os.walk(raiz):
        rel_dir = pathlib.Path(dirpath).relative_to(raiz).as_posix()
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUIR_DIRS
                             and not (rel_dir == "testes" and d == ".saida"))
        for f in filenames:
            rel = (pathlib.Path(rel_dir) / f).as_posix() if rel_dir != "." else f
            saida.append(rel)
    return sorted(saida), "varredura da pasta", len(saida)


def em_dados(rel: str) -> bool:
    """Arquivos com ementas reais (onde os termos @sem-dados não se aplicam)."""
    if rel.startswith("base/") or rel.startswith("docs/dados/"):
        return True
    partes = rel.split("/")
    return len(partes) > 2 and partes[0] == "docs" and partes[1] in TSIGS


def ler_termos(caminho: str) -> list[tuple[str, re.Pattern, bool]]:
    termos = []
    with open(caminho, "r", encoding="utf-8") as f:
        for n, linha in enumerate(f, 1):
            s = linha.rstrip("\r\n").strip()
            if not s or s.startswith("#"):
                continue
            sem_dados = False
            if s.startswith("@sem-dados "):
                sem_dados, s = True, s[len("@sem-dados "):]
            if s.startswith("(?-i)"):
                rx = re.compile(s[5:])
            else:
                rx = re.compile(s, re.IGNORECASE)
            termos.append((f"2-termo#{n}", rx, sem_dados))
    return termos


def _tokens_ambiente() -> list[str]:
    return [v for v in (os.environ.get(n, "") for n in ENV_TOKENS) if len(v) >= 8]


# ------------------------------------------------------------------ 1 + 2 por arquivo
def checar_texto(rel: str, texto: str, binario: bool, termos, rel_obj: Relatorio, k_pagina: str | None = None):
    pads = list(P_DISCO) + list(P_SEGREDO) + list(P_CNJ)
    for nome, rx in pads:
        for m in rx.finditer(texto):
            rel_obj.achar(nome, rel, _linha(texto, m.start()), m.group(0), segredo=nome == "1c-token")
    for m in P_EMAIL.finditer(texto):
        if not P_EMAIL_OK.match(m.group(0)):
            rel_obj.achar("1b-email", rel, _linha(texto, m.start()), m.group(0))
    for tok in _tokens_ambiente():
        i = texto.find(tok)
        if i >= 0:
            rel_obj.achar("1c-token-ambiente", rel, _linha(texto, i), "", segredo=True)
    for nome, rx, sem_dados in termos:
        if sem_dados and em_dados(rel):
            continue
        for m in rx.finditer(texto):
            rel_obj.achar(nome, rel, _linha(texto, m.start()), m.group(0))
    if binario:
        return
    for nome, rx in P_CAMPOS + P_FRAG + P_TERCEIROS:
        for m in rx.finditer(texto):
            rel_obj.achar(nome, rel, _linha(texto, m.start()), m.group(0))
    checar_revogad(rel, texto, rel_obj, k_pagina)
    if rel.startswith("docs/") or rel.startswith("base/"):
        for m in P_VETO.finditer(texto):
            rel_obj.achar("1i-veto", rel, _linha(texto, m.start()), m.group(0))


def checar_revogad(rel: str, texto: str, rel_obj: Relatorio, k_pagina: str | None):
    """1h: a raiz proibida fora de ementa oficial de norma tolerada (§5.4)."""
    escopo_total = (rel.startswith("modelos/") or rel.startswith("fontes/") or rel.startswith("docs/assets/")
                    or (rel.startswith("docs/") and rel.count("/") == 1 and rel.endswith(".html"))
                    or rel in ("docs/dados/avisos.json", "docs/dados/apelidos.json"))
    if escopo_total:
        for m in P_REVOGAD.finditer(texto):
            rel_obj.achar("1h-status", rel, _linha(texto, m.start()), m.group(0))
        return
    if k_pagina is not None:
        fora = EMENTA_LUGARES_RE.sub(lambda m: " " * len(m.group(0)), texto)
        for m in P_REVOGAD.finditer(fora):
            rel_obj.achar("1h-status", rel, _linha(texto, m.start()), m.group(0))
        if k_pagina not in EMENTA_REVOGAD_OK:
            for m in EMENTA_LUGARES_RE.finditer(texto):
                for m2 in P_REVOGAD.finditer(m.group(0)):
                    rel_obj.achar("1h-status", rel, _linha(texto, m.start()), m2.group(0))
        return
    if re.match(r"^docs/dados/n-[a-z]+-\d{2}\.json$", rel):
        try:
            regs = json.loads(texto)
        except ValueError:
            return
        for r in regs if isinstance(regs, list) else []:
            if isinstance(r, dict) and P_REVOGAD.search(str(r.get("e", ""))) and r.get("k") not in EMENTA_REVOGAD_OK:
                rel_obj.achar("1h-status", rel, 1, str(r.get("k")))


# ------------------------------------------------------------------ 3. correlação com a lista privada
def _caminho_rel(url: str) -> str:
    return PLANALTO_RE.sub("", url.strip()).lower()


def mapa_caminho_chave(raiz: pathlib.Path) -> tuple[dict[str, str], list[dict]]:
    arq = raiz / "base" / "normas.jsonl"
    m: dict[str, str] = {}
    normas = []
    if not arq.is_file():
        return m, normas
    with open(arq, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            d = json.loads(ln)
            normas.append(d)
            for c in ("caminho_indice", "caminho", "caminho_compilado"):
                v = d.get(c) or ""
                if v:
                    m.setdefault(v.lower(), d["k"])
    return m, normas


def ler_lista_privada(caminho: str, mapa: dict[str, str]) -> dict[str, int]:
    """Chave -> posição (campo de posição, se houver; senão o número da linha). Só em memória."""
    campo_pos = "ord" + "em"
    pos: dict[str, int] = {}
    with open(caminho, "r", encoding="utf-8") as f:
        for n, ln in enumerate(f, 1):
            ln = ln.strip()
            if not ln:
                continue
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            url = d.get("url") if isinstance(d, dict) else None
            if not url:
                continue
            p = d.get(campo_pos)
            p = p if isinstance(p, (int, float)) else n
            k = mapa.get(_caminho_rel(url))
            if k and (k not in pos or p < pos[k]):
                pos[k] = p
    return pos


def sequencia_chaves(texto: str) -> list[str]:
    vistos, seq = set(), []
    for m in CHAVE_SEQ_RE.finditer(texto):
        s = m.group(0)
        r = ROTA_SEQ_RE.match(s)
        k = f"{r.group(1)}-{r.group(2)}-{r.group(3)}" if r else s
        if k not in vistos:
            vistos.add(k)
            seq.append(k)
    return seq


def kendall_tau(xs: list) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    c = d = 0
    for i in range(n):
        xi = xs[i]
        for j in range(i + 1, n):
            if xs[j] > xi:
                c += 1
            elif xs[j] < xi:
                d += 1
    return (c - d) / (n * (n - 1) / 2)


def maior_sequencia(xs: list) -> tuple[int, int]:
    """(maior corrida crescente, maior corrida decrescente) de elementos consecutivos."""
    if not xs:
        return 0, 0
    sobe = desce = melhor_s = melhor_d = 1
    for a, b in zip(xs, xs[1:]):
        sobe = sobe + 1 if b > a else 1
        desce = desce + 1 if b < a else 1
        melhor_s, melhor_d = max(melhor_s, sobe), max(melhor_d, desce)
    return melhor_s, melhor_d


class Correlacao:
    def __init__(self, nome: str, pos: dict[str, int]):
        self.nome = nome
        self.pos = pos
        self.max_n = 0
        self.falhas: list[str] = []

    def arquivo(self, rel: str, texto: str):
        seq = [self.pos[k] for k in sequencia_chaves(texto) if k in self.pos]
        n = len(seq)
        if n < 2:
            return
        self.max_n = max(self.max_n, n)
        s, d = maior_sequencia(seq)
        if s >= 10 or d >= 10:
            self.falhas.append(f"{rel}: corrida monotônica de {max(s, d)} chaves na ordem da lista ({self.nome})")
        if n >= 20:
            t = kendall_tau(seq)
            if abs(t) > 0.5:
                self.falhas.append(f"{rel}: |tau| = {abs(t):.2f} > 0,5 com n = {n} ({self.nome})")


def checar_desempate(raiz: pathlib.Path, normas: list[dict], pos: dict[str, int]) -> list[str]:
    arq = raiz / "docs" / "dados" / "apelidos.json"
    if not arq.is_file():
        return []
    d = json.loads(arq.read_text(encoding="utf-8"))
    falhas = []
    for grupo in (d.get("desempate") or {}):
        m = re.match(r"^(num|\w+):(\d+)([a-z]?)$", grupo)
        if not m:
            continue
        t, n, l = m.group(1), int(m.group(2)), m.group(3)
        membros = [x["k"] for x in normas if x.get("numero") == n and x.get("letra") == l
                   and (t == "num" or x.get("tsig") == t)]
        if sum(1 for k in membros if k in pos) >= 2:
            falhas.append(f"desempate {grupo}: grupo com 2 ou mais membros na lista privada")
    return falhas


# ------------------------------------------------------------------ 5. cópia de texto de lei
def ler_prefixos(caminho: str) -> set[str]:
    campo = "ini" + "cio"
    pref = set()
    with open(caminho, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            v = d.get(campo) if isinstance(d, dict) else None
            if isinstance(v, str):
                v = re.sub(r"\s+", " ", v).strip()
                if len(v) >= 40:
                    pref.add(v[:40])
    return pref


def procurar_prefixos(texto: str, prefixos: set[str], por_cabeca: dict[str, list[str]]) -> str | None:
    t = re.sub(r"\s+", " ", texto)
    n = len(t)
    for i in range(n - 39):
        if i and t[i - 1].isalnum():
            continue
        cab = t[i:i + 8]
        if cab in por_cabeca and t[i:i + 40] in prefixos:
            return t[i:i + 40]
    return None


# ------------------------------------------------------------------ 4. histórico
def _git(raiz: pathlib.Path, *args) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], cwd=raiz, capture_output=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)
    return r.returncode, r.stdout.decode("utf-8", "replace") + ("\n" + r.stderr.decode("utf-8", "replace") if r.returncode else "")


def checar_historico(raiz: pathlib.Path, termos, rel_obj: Relatorio) -> None:
    rc, out = _git(raiz, "rev-list", "--all")
    if rc != 0:
        rel_obj.falhas_gerais.append("histórico: git indisponível ou pasta sem repositório")
        return
    commits = [c for c in out.split() if c]
    if not commits:
        rel_obj.notas.append("histórico: nenhum commit ainda (nada a varrer)")
        return
    rc, out = _git(raiz, "log", "--all", "--format=%an%n%ae%n%cn%n%ce")
    linhas = [x for x in out.split("\n") if x.strip()]
    for i in range(0, len(linhas) - 3, 4):
        an, ae, cn, ce = linhas[i:i + 4]
        for nome in (an, cn):
            if nome not in ("paulodca", "github-actions[bot]"):
                rel_obj.achar("4-autor", "(metadados de commit)", 0, nome)
        for em in (ae, ce):
            if not re.search(ARROBA + r"users\.noreply\.github\.com$", em):
                rel_obj.achar("4-email", "(metadados de commit)", 0, em)
    pads = list(P_DISCO) + list(P_SEGREDO) + list(P_CNJ) + list(P_CAMPOS)
    rc, msgs = _git(raiz, "log", "--all", "--format=%B%x00")
    for nome, rx in pads + [(n, r) for n, r, _s in termos]:
        for m in rx.finditer(msgs):
            rel_obj.achar(nome, "(mensagem de commit)", 0, m.group(0), segredo=nome == "1c-token")
    for m in P_EMAIL.finditer(msgs):
        if not P_EMAIL_OK.match(m.group(0)):
            rel_obj.achar("1b-email", "(mensagem de commit)", 0, m.group(0))
    rc, diff = _git(raiz, "log", "-p", "--all", "--no-color", "--no-ext-diff", "-U0", "--format=commit %H")
    arquivo = "?"
    adicionadas: dict[str, list[str]] = {}
    for ln in diff.split("\n"):
        if ln.startswith("+++ "):
            arquivo = ln[6:] if ln.startswith("+++ b/") else ln[4:]
        elif ln.startswith("+") and not ln.startswith("+++"):
            adicionadas.setdefault(arquivo, []).append(ln[1:])
    for arq, ls in adicionadas.items():
        texto = "\n".join(ls)
        for nome, rx in pads:
            for m in rx.finditer(texto):
                rel_obj.achar(nome, f"(histórico) {arq}", 0, m.group(0), segredo=nome == "1c-token")
        for m in P_EMAIL.finditer(texto):
            if not P_EMAIL_OK.match(m.group(0)):
                rel_obj.achar("1b-email", f"(histórico) {arq}", 0, m.group(0))
        for nome, rx, sem_dados in termos:
            if sem_dados and em_dados(arq):
                continue
            for m in rx.finditer(texto):
                rel_obj.achar(nome, f"(histórico) {arq}", 0, m.group(0))
    rel_obj.notas.append(f"histórico: {len(commits)} commit(s) varridos")


# ------------------------------------------------------------------ 6. marcas
class _Visivel(html.parser.HTMLParser):
    """Texto visível (fora de atributos, script e style); o texto da ementa oficial fica em ``ementa``."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes: list[str] = []
        self.ementa: list[str] = []
        self.pilha: list[str] = []
        self.em_ementa = 0
        self.tags_img: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("img", "svg", "picture", "object", "embed"):
            self.tags_img.append(tag)
        if tag in ("script", "style"):
            self.pilha.append(tag)
        if tag == "p" and ("class", "ementa") in attrs:
            self.em_ementa += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.pilha:
            self.pilha.pop()
        if tag == "p" and self.em_ementa:
            self.em_ementa -= 1

    def handle_data(self, data):
        if self.pilha:
            return
        (self.ementa if self.em_ementa else self.partes).append(data)


def checar_marcas(raiz: pathlib.Path, arquivos: list[str], rel_obj: Relatorio) -> int:
    alvos = [r for r in arquivos if r.startswith("modelos/")
             or (r.startswith("docs/") and (r.endswith(".html") or r.endswith(".css")))]
    for rel in alvos:
        texto = (raiz / rel).read_bytes().decode("utf-8", "replace")
        for nome, rx in P_MARCAS:
            for m in rx.finditer(texto):
                rel_obj.achar(nome, rel, _linha(texto, m.start()), m.group(0))
        if rel.endswith(".css"):
            continue
        v = _Visivel()
        v.feed(texto)
        visivel = re.sub(r"(?i)planalto\.gov\.br", " ", " ".join(v.partes))
        ementa = re.sub(r"(?i)planalto\.gov\.br", " ", " ".join(v.ementa))
        for nome, rx in P_VISIVEL:
            for m in rx.finditer(visivel):
                rel_obj.achar(nome, rel, 0, m.group(0))
            # Ementa oficial do índice é dado, não marca: só "República Federativa" é tolerada nela
            # (CF e normas cuja ementa oficial cita o nome do país).
            if rx is not P_VISIVEL[3][1]:
                for m in rx.finditer(ementa):
                    rel_obj.achar(nome, rel, 0, m.group(0))
        for tag in v.tags_img:
            rel_obj.achar("marca-imagem", rel, 0, f"<{tag}>")
    return len(alvos)


# ------------------------------------------------------------------ saída
def imprimir(rel_obj: Relatorio, estado: str, detalhe: str, id_: str, destino: str | None):
    if rel_obj.achados:
        print(f"{'padrão':<20} {'arquivo:linha':<60} trecho")
        for a in rel_obj.achados[:200]:
            loc = f"{a['arquivo']}:{a['linha']}" if a["linha"] else a["arquivo"]
            print(f"{a['padrao']:<20} {loc:<60} {a['trecho']}")
        if len(rel_obj.achados) > 200:
            print(f"... e mais {len(rel_obj.achados) - 200} achado(s)")
    for n in rel_obj.notas:
        print(f"nota: {n}")
    for f in rel_obj.falhas_gerais:
        print(f"falha: {f}")
    if destino:
        d = pathlib.Path(destino)
        d.parent.mkdir(parents=True, exist_ok=True)
        with open(d, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"id": id_, "estado": estado, "detalhe": detalhe, "itens": rel_obj.achados},
                                ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    print(("SKIP: " if estado == "SKIP" else f"{estado}: ") + detalhe)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Checagem de vazamento (d) e de marcas proibidas (c).")
    ap.add_argument("--termos-proibidos", help="arquivo de regex, fora do repo (ou PD_TERMOS_PROIBIDOS)")
    ap.add_argument("--lista-privada", action="append", default=None,
                    help="JSONL com url (repetível; ou PD_LISTA_PRIVADA separado por ';')")
    ap.add_argument("--ancoras", help="JSONL das âncoras com o texto inicial (ou PD_ANCORAS)")
    ap.add_argument("--historico", action="store_true", help="varre também o histórico e os metadados do git")
    ap.add_argument("--marcas", action="store_true", help="só a checagem de marcas proibidas (parte de (c))")
    ap.add_argument("--raiz", default=str(RAIZ), help=argparse.SUPPRESS)
    ap.add_argument("--json", help="grava o resultado neste arquivo")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code in (0, None) else 2
    raiz = pathlib.Path(a.raiz)
    rel_obj = Relatorio()
    arquivos, metodo, n_push = listar_arquivos(raiz)

    if a.marcas:
        n = checar_marcas(raiz, arquivos, rel_obj)
        estado = "FAIL" if rel_obj.achados else "PASS"
        detalhe = f"{n} arquivos (HTML, CSS, modelos); {len(rel_obj.achados)} achado(s)"
        imprimir(rel_obj, estado, detalhe, "c-marcas", a.json)
        return 1 if estado == "FAIL" else 0

    termos_arq = a.termos_proibidos or os.environ.get("PD_TERMOS_PROIBIDOS", "")
    listas = a.lista_privada or [x for x in os.environ.get("PD_LISTA_PRIVADA", "").split(";") if x]
    ancoras_arq = a.ancoras or os.environ.get("PD_ANCORAS", "")
    termos = []
    if termos_arq:
        if not pathlib.Path(termos_arq).is_file():
            print("erro: arquivo de termos não encontrado", file=sys.stderr)
            return 2
        try:
            termos = ler_termos(termos_arq)
        except re.error as e:
            print(f"erro: regex inválida no arquivo de termos ({e})", file=sys.stderr)
            return 2
    for x in listas + ([ancoras_arq] if ancoras_arq else []):
        if not pathlib.Path(x).is_file():
            print("erro: arquivo de insumo privado não encontrado", file=sys.stderr)
            return 2

    if n_push < MIN_ARQUIVOS:
        rel_obj.falhas_gerais.append(f"conjunto suspeito: só {n_push} arquivos para o push ({metodo}); "
                                     f"o mínimo é {MIN_ARQUIVOS}")
    mapa, normas = mapa_caminho_chave(raiz)
    correl = [Correlacao(pathlib.Path(x).name, ler_lista_privada(x, mapa)) for x in listas]
    prefixos = ler_prefixos(ancoras_arq) if ancoras_arq else set()
    por_cabeca: dict[str, list[str]] = {}
    for p in prefixos:
        por_cabeca.setdefault(p[:8], []).append(p)
    copias = []

    for rel in arquivos:
        b = (raiz / rel).read_bytes()
        binario = b"\0" in b
        texto = b.decode("utf-8", "replace")
        m = ROTA_RE.match(rel)
        k_pagina = f"{m.group(1)}-{m.group(2)}{m.group(3)}-{m.group(4)}" if m else None
        if k_pagina == "cf-1988-1988":
            k_pagina = "cf-1988"
        if m and m.group(1) == "cf":
            k_pagina = "cf-1988"
        checar_texto(rel, texto, binario, termos, rel_obj, k_pagina)
        if binario:
            continue
        for c in correl:
            c.arquivo(rel, texto)
        if prefixos:
            achado = procurar_prefixos(texto, prefixos, por_cabeca)
            if achado:
                copias.append(rel)
                rel_obj.achar("5-texto-de-lei", rel, 0, achado)

    for c in correl:
        rel_obj.falhas_gerais.extend(c.falhas)
        rel_obj.falhas_gerais.extend(checar_desempate(raiz, normas, c.pos))
        if c.max_n < 20:
            rel_obj.falhas_gerais.append(f"correlação ({c.nome}): nenhum arquivo com n ≥ 20 membros comuns "
                                         f"(maior n = {c.max_n}); a checagem não pôde rodar")
        else:
            rel_obj.notas.append(f"correlação ({c.nome}): {len(c.pos)} chaves na lista; maior n por arquivo = {c.max_n}")
    if a.historico:
        checar_historico(raiz, termos, rel_obj)

    faltando = []
    if not termos_arq:
        faltando.append("termos externos não fornecidos")
    if not listas:
        faltando.append("lista privada não fornecida (correlação não rodou)")
    if not ancoras_arq:
        faltando.append("âncoras não fornecidas (cópia de texto não rodou)")
    if not a.historico:
        faltando.append("histórico não varrido (use --historico antes do push)")
    resumo = f"{len(arquivos)} arquivos ({metodo}); {len(rel_obj.achados)} achado(s)"
    if rel_obj.achados or rel_obj.falhas_gerais:
        estado = "FAIL"
        detalhe = resumo + ("; " + "; ".join(rel_obj.falhas_gerais[:5]) if rel_obj.falhas_gerais else "")
    elif not termos_arq:
        estado = "SKIP"
        detalhe = "termos externos não fornecidos; " + resumo
    else:
        estado = "PASS"
        detalhe = resumo + ("; sem: " + ", ".join(faltando) if faltando else "")
    imprimir(rel_obj, estado, detalhe, "d", a.json)
    return {"PASS": 0, "FAIL": 1, "SKIP": 77}[estado]


if __name__ == "__main__":
    sys.exit(main())
