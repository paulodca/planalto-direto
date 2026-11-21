"""ESTÁGIO B — gera o site estático a partir de base/ + fontes/ + modelos/ + docs/config.js (SPEC §10).

Uso:
  python -P build/gerar_site.py [--base base/] [--fontes fontes/] [--modelos modelos/] [--saida docs/]
                                [--config docs/config.js] [--verificar] [--so-dados]

Determinístico: a mesma base produz a mesma árvore, byte a byte (nenhuma data de relógio).
Limpeza segura: só apaga caminhos listados em <saida>/.gerado da execução anterior.
Códigos de saída de ``main``: 0 ok, 1 gate/validação falhou (ou --verificar achou diferença), 2 erro de uso.
"""
from __future__ import annotations

import sys
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import argparse
import hashlib
import html
import json
import os
import re
import string
import urllib.parse

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "font-src 'self'; form-action 'self'; base-uri 'none'; object-src 'none'")
RODAPE = "Ferramenta não oficial, sem vínculo com a Presidência da República. Sempre confira na fonte."
MARCA = "Planalto Direto"
SITUACAO_PADRAO = "Não verificada pelo Planalto Direto — confira na fonte."
ROTULO_VERSAO = {"c": "texto compilado", "h": "texto com histórico (trechos riscados são redação antiga)"}
EXEMPLOS = ("clt 477", "lei 8.036/90 art 3", "Del5452", "lc 150 art 7", "art 7 xxix cf", "adct 76",
            "aviso prévio proporcional", "5452")
LIMITE_URLS = 45000
LIMITE_BYTES = 45 * 1000 * 1000
DESCRICAO_MAX = 155
# Arquivos escritos à mão em docs/ (nunca gerados nem apagados).
PROTEGIDOS = frozenset(("config.js", ".nojekyll", "favicon.svg", ".gerado"))
PREFIXOS_PROTEGIDOS = ("assets/",)


class ErroUso(Exception):
    pass


class ErroGate(Exception):
    def __init__(self, erros):
        super().__init__("; ".join(erros[:5]))
        self.erros = list(erros)


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def _sha(b: bytes, n: int | None = None) -> str:
    h = hashlib.sha256(b).hexdigest()
    return h[:n] if n else h


def _json_compacto(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


# ----------------------------------------------------------------------------------- leitura
def _ler_json(p: pathlib.Path):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def ler_base(base: pathlib.Path):
    from pd.jsonio import ler_jsonl
    arq = base / "normas.jsonl"
    if not arq.is_file():
        raise ErroUso(f"base sem normas.jsonl: {base.name}/")
    normas = ler_jsonl(arq)
    ancoras = {}
    pasta = base / "ancoras"
    if pasta.is_dir():
        for p in sorted(pasta.glob("*.json")):
            d = _ler_json(p)
            ancoras[p.stem] = d
    arq_d = base / "desempate.json"
    desempate = _ler_json(arq_d) if arq_d.is_file() else {"grupos": {}, "versao": 1}
    return normas, ancoras, desempate


def ler_fontes(fontes: pathlib.Path):
    saida = {}
    for nome in ("apelidos", "areas", "avisos"):
        p = fontes / f"{nome}.json"
        if not p.is_file():
            raise ErroUso(f"fontes sem {nome}.json")
        saida[nome] = _ler_json(p)
    return saida


def ler_modelos(modelos: pathlib.Path):
    saida = {}
    for nome in ("index.html", "norma.html", "404.html", "opensearch.xml", "robots.txt"):
        p = modelos / nome
        if not p.is_file():
            raise ErroUso(f"modelo ausente: {nome}")
        saida[nome] = string.Template(p.read_text(encoding="utf-8"))
    return saida


def base_sha(base: pathlib.Path, ancoras_ks) -> str:
    """12 hex do sha256 sobre (caminho relativo + NUL + bytes) de normas.jsonl, desempate.json e
    cada ancoras/<k>.json, nesta ordem (âncoras em ordem canônica de chave)."""
    h = hashlib.sha256()
    rels = ["normas.jsonl", "desempate.json"] + [f"ancoras/{k}.json" for k in ancoras_ks]
    for rel in rels:
        p = base / rel
        if p.is_file():
            h.update(rel.encode("utf-8") + b"\0" + p.read_bytes())
    return h.hexdigest()[:12]


# ----------------------------------------------------------------------------------- validação
def validar(normas, ancoras, desempate, fontes) -> None:
    from pd import esquemas as E
    erros = []
    erros += E.validar_normas(normas)
    chaves = {n.get("k") for n in normas if isinstance(n, dict)}
    por_k = {n["k"]: n for n in normas if isinstance(n, dict) and "k" in n}
    for k, d in ancoras.items():
        if k not in por_k:
            erros.append(f"[ancoras {k}] norma inexistente na base")
            continue
        if d.get("k") != k:
            erros.append(f"[ancoras {k}] nome do arquivo difere de k")
        erros += E.validar_ancoras(d, por_k[k])
    erros += E.validar_desempate(desempate, chaves)
    erros += E.validar_apelidos(fontes["apelidos"], chaves)
    erros += E.validar_areas(fontes["areas"], chaves)
    erros += E.validar_avisos(fontes["avisos"], chaves)
    for nome, obj in (("normas", normas), ("ancoras", ancoras), ("desempate", desempate),
                      ("apelidos", fontes["apelidos"]), ("areas", fontes["areas"]), ("avisos", fontes["avisos"])):
        for c in E.campos_proibidos(obj):
            erros.append(f"{nome}: campo proibido {c}")
        if ":~:" in json.dumps(obj, ensure_ascii=False):
            erros.append(f"{nome}: contém ':~:'")
    for n in normas:
        if isinstance(n, dict) and re.search(r"(?i)mensagem\s+de\s+veto", str(n.get("ementa", ""))):
            erros.append(f"[{n.get('k')}] ementa com 'mensagem de veto'")
    if erros:
        raise ErroGate(erros)


# ----------------------------------------------------------------------------------- utilidades
def rota(k: str) -> str:
    """``lei-8036-1990`` -> ``lei/8036-1990/``; ``cf-1988`` -> ``cf/1988/``."""
    tsig, resto = k.split("-", 1)
    return f"{tsig}/{resto}/"


def nome_do_shard(n: dict) -> str:
    return f"n-{n['tsig']}-{0 if n['tsig'] == 'cf' else n['numero'] // 1000:02d}"


def marca_html() -> str:
    partes, i = [], 0
    for ch in MARCA:
        if ch == " ":
            partes.append(" ")
            continue
        partes.append(f'<span class="l{i % 6 + 1}">{esc(ch)}</span>')
        i += 1
    return "".join(partes)


def descricao(ementa: str) -> str:
    from pd.normas import EMENTA_VAZIA
    s = ementa or EMENTA_VAZIA
    if len(s) > DESCRICAO_MAX:
        s = s[:DESCRICAO_MAX - 1].rstrip() + "…"
    return s


def data_br(d: str) -> str:
    return f"{d[8:10]}/{d[5:7]}/{d[:4]}" if d else ""


def _ordinal(n: str) -> str:
    """'1' -> '1º' (até 9), '10' -> '10'; com letra mantém: '790-B'."""
    if n.isdigit() and int(n) < 10:
        return n + "º"
    return n


def rotulo_disp(disp: str, parte: str = "corpo") -> str:
    """Dispositivo canônico -> rótulo de leitura: '791-A|§4' -> 'art. 791-A, § 4º'."""
    if not disp:
        return ""
    comps = disp.split("|")
    out = ["art. " + _ordinal(comps[0])]
    for c in comps[1:]:
        if c == "pu":
            out.append("parágrafo único")
        elif c.startswith("§"):
            num = c[1:]
            base, _, letra = num.partition("-")
            out.append("§ " + _ordinal(base) + (f"-{letra}" if letra else ""))
        elif c.isdigit():
            out.append("item " + c)
        elif len(c) == 1 and c.islower():
            out.append("alínea " + c)
        else:
            out.append(c)
    s = ", ".join(out)
    return s + (" do ADCT" if parte == "adct" else "")


def avisos_publicados(fontes_avisos: dict) -> list[dict]:
    pub = []
    for a in fontes_avisos.get("avisos", []):
        if not a.get("conferido_em"):
            continue
        pub.append({c: a[c] for c in ("id", "alvo", "estado", "texto", "fonte", "ir_para")})
    pub.sort(key=lambda a: a["id"])
    return pub


def sugestao(cfg: dict) -> tuple[str, str]:
    if cfg.get("SUGESTAO_URL") and cfg.get("SUGESTAO_CAMPO"):
        return cfg["SUGESTAO_URL"], "Sugerir uma lei ou apelido (formulário, sem login)"
    href = (cfg["REPO_URL"] + "/issues/new?title=" + urllib.parse.quote("Sugestão: ", safe="")
            + "&labels=sugestao")
    return href, "Sugerir uma lei ou apelido (no GitHub, precisa de conta no GitHub)"


def _limpar_html(s: str) -> str:
    """Sem espaço no fim de linha e sem linhas vazias (placeholders vazios)."""
    linhas = [ln.rstrip() for ln in s.split("\n")]
    return "\n".join(ln for ln in linhas if ln) + "\n"


# ----------------------------------------------------------------------------------- dados
def gerar_dados(normas, ancoras, desempate, fontes, sha_base) -> dict[str, bytes]:
    from pd import esquemas as E
    from pd import ordem as O
    arqs: dict[str, bytes] = {}
    shards: dict[str, list] = {}
    for n in normas:  # já em ordem canônica (validado)
        r = {"a": n["ano"], "k": n["k"], "l": n["letra"], "n": n["numero"], "u": n["caminho"]}
        if n["caminho_compilado"]:
            r["c"] = n["caminho_compilado"]
        if n["data"]:
            r["d"] = n["data"]
        if n["ementa"]:
            r["e"] = n["ementa"]
        if n["reed"]:
            r["r"] = n["reed"]
        shards.setdefault(nome_do_shard(n), []).append(r)
    erros = []
    info = {}
    for nome in sorted(shards):
        erros += E.validar_shard(shards[nome], nome)
        b = _json_compacto(shards[nome])
        arqs[f"dados/{nome}.json"] = b
        info[nome] = {"qtd": len(shards[nome]), "sha": _sha(b, 12)}
    ks_anc = sorted(ancoras, key=O.ordem_chave)
    ind = {"normas": ks_anc, "versao": 1}
    erros += E.validar_ancoras_indice(ind)
    arqs["dados/ancoras.json"] = _json_compacto(ind)
    for k in ks_anc:
        arqs[f"dados/a/{k}.json"] = _json_compacto(ancoras[k])
    ap = dict(fontes["apelidos"])
    ap["desempate"] = dict(desempate.get("grupos", {}))
    chaves = {n["k"] for n in normas}
    erros += E.validar_apelidos_publicos(ap, chaves)
    arqs["dados/apelidos.json"] = _json_compacto(ap)
    erros += E.validar_areas_publicas(fontes["areas"], chaves)
    arqs["dados/areas.json"] = _json_compacto(fontes["areas"])
    av = {"avisos": avisos_publicados(fontes["avisos"]), "versao": 1}
    erros += E.validar_avisos_publicos(av, chaves)
    arqs["dados/avisos.json"] = _json_compacto(av)
    man = {"base_sha": sha_base, "gerado": max((n["desde"] for n in normas), default="0000-00-00"),
           "normas": len(normas), "shards": info, "versao": 1}
    erros += E.validar_manifesto(man)
    arqs["dados/manifesto.json"] = _json_compacto(man)
    for rel, b in arqs.items():
        if b":~:" in b:
            erros.append(f"{rel}: contém ':~:'")
    if erros:
        raise ErroGate(erros)
    return arqs


# ----------------------------------------------------------------------------------- páginas
def gerar_paginas(normas, desempate, fontes, modelos, cfg) -> dict[str, bytes]:
    from pd import normas as N
    from pd import ordem as O
    base_pl = cfg["PLANALTO_BASE"]
    site_url = cfg["SITE_URL"]
    marca = marca_html()
    apelidos = fontes["apelidos"]["apelidos"]
    alvos_apelido = frozenset(a["alvo"] for a in apelidos)
    ap_por_k: dict[str, list] = {}
    for a in apelidos:
        ap_por_k.setdefault(a["alvo"], []).append(a)
    pub = avisos_publicados(fontes["avisos"])
    av_por_k: dict[str, list] = {}
    for a in pub:
        av_por_k.setdefault(a["alvo"]["k"], []).append(a)
    grupos: dict[tuple, list] = {}
    for n in normas:
        if n["tsig"] != "cf":
            grupos.setdefault((n["numero"], n["letra"]), []).append(n["k"])
    nomes = {n["k"]: N.nome_norma(n["tsig"], n["numero"], n["letra"], n["reed"], n["ano"]) for n in normas}
    grupos_des = desempate.get("grupos", {})
    tpl = modelos["norma.html"]
    arqs: dict[str, bytes] = {}
    for n in normas:
        k = n["k"]
        nome = nomes[k]
        aps = ap_por_k.get(k, [])
        sigla = aps[0]["sigla"] if aps else ""
        titulo = f"{nome}{f' ({sigla})' if sigla else ''} — texto no Planalto"
        # apelidos e notas
        conhecidos = []
        for a in aps:
            for t in (a["sigla"], a["nome"]):
                if t and t != nome and t not in conhecidos:
                    conhecidos.append(t)
        apel = ""
        if conhecidos:
            apel = f'<p class="apelidos">Também conhecida como: {esc(", ".join(conhecidos))}</p>'
        for a in aps:
            if a["nota"]:
                apel += f'\n<p class="nota">{esc(a["nota"])}</p>'
        # avisos
        avs = av_por_k.get(k, [])
        avisos_html, situacao = [], SITUACAO_PADRAO
        toda = [a for a in avs if not a["alvo"].get("disp")]
        if toda:
            situacao = "Atenção: " + " ".join(a["texto"] for a in toda)
        for a in avs:
            disp = a["alvo"].get("disp", "")
            onde = rotulo_disp(disp, a["alvo"].get("parte", "corpo"))
            cab = "Atenção" + (f" ({onde})" if onde else "")
            avisos_html.append(
                f'<div class="aviso" data-aviso="{esc(a["id"])}"><p><strong>{esc(cab)}:</strong> {esc(a["texto"])}</p>'
                f'<p class="nota">Fonte: {esc(a["fonte"])}</p></div>')
        # links para o Planalto
        c, u = n["caminho_compilado"], n["caminho"]
        if c:
            url_p, rot_p = base_pl + c, ROTULO_VERSAO["c"]
        else:
            url_p, rot_p = base_pl + u, ROTULO_VERSAO["h"]
        alt = ""
        if c and c.lower() != u.lower():
            alt = (f'<p><a href="{esc(base_pl + u)}" rel="noopener">Versão com histórico '
                   f'(trechos riscados são redação antiga)</a></p>')
        data_html = f"<dt>Data</dt><dd>{esc(data_br(n['data']))}</dd>" if n["data"] else ""
        arquivo = n["caminho_indice"].rsplit("/", 1)[-1]
        comp_html = f"<dt>Compilado</dt><dd><code>{esc(c.rsplit('/', 1)[-1])}</code></dd>" if c else ""
        if n["tsig"] == "cf":
            consulta_base = "cf"
        else:
            consulta_base = f"{n['tsig']} {n['numero']}{n['letra']}/{n['ano']}"
        # mesmo número
        mesmo = ""
        if n["tsig"] != "cf":
            outros = [x for x in grupos[(n["numero"], n["letra"])] if x != k]
            if outros:
                ordem = O.ordem_publica(outros, alvos_apelido)
                pref = grupos_des.get(f"num:{n['numero']}{n['letra']}")
                if pref in ordem and not (ordem[0] in alvos_apelido and pref not in alvos_apelido):
                    ordem = [pref] + [x for x in ordem if x != pref]
                itens = "".join(f'<li><a href="../../{esc(rota(x))}">{esc(nomes[x])}</a></li>' for x in ordem)
                num = N.numero_milhar(n["numero"]) + (f"-{n['letra'].upper()}" if n["letra"] else "")
                mesmo = (f'<nav class="mesmo-numero" aria-label="Outras normas com o mesmo número">'
                         f'<h2>Outras normas com o nº {esc(num)}</h2><ul>{itens}</ul></nav>')
        pagina = tpl.substitute(
            csp=esc(CSP), titulo=esc(titulo), descricao=esc(descricao(n["ementa"])),
            canonical=esc(site_url + rota(k)), marca_html=marca, nome_norma=esc(nome),
            apelidos_html=apel, ementa=esc(n["ementa"] or N.EMENTA_VAZIA), avisos_html="\n".join(avisos_html),
            url_principal=esc(url_p), rotulo_principal=esc(rot_p), alternativo_html=alt, data_html=data_html,
            arquivo=esc(arquivo), compilado_html=comp_html, situacao=esc(situacao),
            consulta_base=esc(consulta_base), mesmo_numero_html=mesmo)
        arqs[rota(k) + "index.html"] = _limpar_html(pagina).encode("utf-8")
    return arqs


def gerar_raiz(normas, fontes, modelos, cfg) -> dict[str, bytes]:
    site_url, site_path = cfg["SITE_URL"], cfg["SITE_PATH"]
    marca = marca_html()
    areas_html = []
    for a in fontes["areas"]["areas"]:
        itens = "\n".join(
            f'<li><a href="{esc(rota(it["k"]))}">{esc(it["rotulo"])}</a>'
            + (f' <span class="area-dica">{esc(it["dica"])}</span>' if it["dica"] else "") + "</li>"
            for it in a["itens"])
        areas_html.append(f'<section class="area" id="area-{esc(a["id"])}">\n<h3>{esc(a["nome"])}</h3>\n'
                          f'<ul>\n{itens}\n</ul>\n</section>')
    exemplos = "\n".join(f'<li><a href="./?q={esc(urllib.parse.quote(q, safe=""))}"><code>{esc(q)}</code></a></li>'
                         for q in EXEMPLOS)
    google = ""
    if cfg.get("GOOGLE_VERIFICACAO"):
        google = f'<meta name="google-site-verification" content="{esc(cfg["GOOGLE_VERIFICACAO"])}">'
    sug = ""
    if cfg.get("SUGESTAO_ATIVA") == "sim":  # config.js; "nao" = sem botão de sugestão
        s_href, s_txt = sugestao(cfg)
        sug = f'<p><a class="sugestao" href="{esc(s_href)}" rel="noopener">{esc(s_txt)}</a></p>'
    arqs = {}
    arqs["index.html"] = _limpar_html(modelos["index.html"].substitute(
        csp=esc(CSP), site_url=esc(site_url), google_meta=google, marca_html=marca,
        areas_html="\n".join(areas_html), exemplos_html=exemplos, sugestao_html=sug)).encode("utf-8")
    arqs["404.html"] = _limpar_html(modelos["404.html"].substitute(
        csp=esc(CSP), site_path=esc(site_path), marca_html=marca)).encode("utf-8")
    arqs["opensearch.xml"] = modelos["opensearch.xml"].substitute(site_url=esc(site_url)).encode("utf-8")
    arqs["robots.txt"] = modelos["robots.txt"].substitute(site_url=site_url).encode("utf-8")
    return arqs


def gerar_sitemap(normas, cfg, limite_urls: int = LIMITE_URLS, limite_bytes: int = LIMITE_BYTES) -> dict[str, bytes]:
    site_url = cfg["SITE_URL"]
    urls = [site_url] + [site_url + rota(n["k"]) for n in normas]
    cab = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    fim = "</urlset>\n"
    linhas = [f"<url><loc>{esc(u)}</loc></url>\n" for u in urls]

    def montar(ls):
        return (cab + "".join(ls) + fim).encode("utf-8")

    tudo = montar(linhas)
    if len(urls) <= limite_urls and len(tudo) <= limite_bytes:
        return {"sitemap.xml": tudo}
    partes, atual, tam = [], [], len(cab) + len(fim)
    for ln in linhas:
        b = len(ln.encode("utf-8"))
        if atual and (len(atual) >= limite_urls or tam + b > limite_bytes):
            partes.append(atual)
            atual, tam = [], len(cab) + len(fim)
        atual.append(ln)
        tam += b
    if atual:
        partes.append(atual)
    arqs = {}
    ind = ['<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n']
    for i, p in enumerate(partes, 1):
        nome = f"sitemap-{i:04d}.xml"
        arqs[nome] = montar(p)
        ind.append(f"<sitemap><loc>{esc(site_url + nome)}</loc></sitemap>\n")
    ind.append("</sitemapindex>\n")
    arqs["sitemap.xml"] = "".join(ind).encode("utf-8")
    return arqs


# ----------------------------------------------------------------------------------- orquestração
def gerar(base: pathlib.Path, fontes_dir: pathlib.Path, modelos_dir: pathlib.Path, cfg: dict,
          so_dados: bool = False) -> dict[str, bytes]:
    """Gera tudo em memória: {caminho relativo à saída: bytes}. Sem efeito colateral."""
    normas, ancoras, desempate = ler_base(base)
    fontes = ler_fontes(fontes_dir)
    modelos = None if so_dados else ler_modelos(modelos_dir)
    validar(normas, ancoras, desempate, fontes)
    from pd import ordem as O
    sha_base = base_sha(base, sorted(ancoras, key=O.ordem_chave))
    arqs = gerar_dados(normas, ancoras, desempate, fontes, sha_base)
    if not so_dados:
        arqs.update(gerar_paginas(normas, desempate, fontes, modelos, cfg))
        arqs.update(gerar_raiz(normas, fontes, modelos, cfg))
        arqs.update(gerar_sitemap(normas, cfg))
    for rel in arqs:
        if rel in PROTEGIDOS or rel.startswith(PREFIXOS_PROTEGIDOS):
            raise ErroGate([f"o estágio B não pode gerar o arquivo escrito à mão {rel}"])
    return arqs


def _ordem_escrita(rel: str) -> tuple:
    """dados -> páginas de norma -> index/404/opensearch/robots -> sitemap."""
    if rel.startswith("dados/"):
        g = 0
    elif rel.startswith("sitemap"):
        g = 3
    elif "/" in rel:
        g = 1
    else:
        g = 2
    return (g, rel)


def ler_gerado(saida: pathlib.Path) -> list[str]:
    p = saida / ".gerado"
    if not p.is_file():
        return []
    return [ln for ln in p.read_text(encoding="utf-8").split("\n") if ln]


def _seguro(saida: pathlib.Path, rel: str) -> pathlib.Path | None:
    if not rel or rel.startswith("/") or "\\" in rel or ".." in rel.split("/") or ":" in rel:
        return None
    if rel in PROTEGIDOS or rel.startswith(PREFIXOS_PROTEGIDOS):
        return None
    return saida / pathlib.PurePosixPath(rel)


def texto_gerado(rels) -> bytes:
    return "".join(r + "\n" for r in sorted(rels)).encode("utf-8")


def gravar(arqs: dict[str, bytes], saida: pathlib.Path, so_dados: bool = False) -> dict:
    antigos = ler_gerado(saida)
    if so_dados:
        manter = [r for r in antigos if not r.startswith("dados/")]
        novos = set(arqs) | set(manter)
    else:
        novos = set(arqs)
    removidos = 0
    pastas = set()
    for rel in antigos:
        if rel in novos:
            continue
        p = _seguro(saida, rel)
        if p is not None and p.is_file():
            p.unlink()
            removidos += 1
            pastas.add(p.parent)
    escritos = 0
    for rel in sorted(arqs, key=_ordem_escrita):
        p = saida / pathlib.PurePosixPath(rel)
        b = arqs[rel]
        if p.is_file() and p.read_bytes() == b:
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.tmp-{os.getpid()}")
        tmp.write_bytes(b)
        os.replace(tmp, p)
        escritos += 1
    (saida / ".gerado").write_bytes(texto_gerado(novos))
    raiz = saida.resolve()
    for d in sorted(pastas, key=lambda x: len(x.parts), reverse=True):
        while d.resolve() != raiz and d.is_dir() and not any(d.iterdir()):
            d.rmdir()
            d = d.parent
    return {"escritos": escritos, "removidos": removidos, "total": len(arqs)}


def verificar(arqs: dict[str, bytes], saida: pathlib.Path, so_dados: bool = False) -> list[str]:
    difs = []
    for rel in sorted(arqs):
        p = saida / pathlib.PurePosixPath(rel)
        if not p.is_file():
            difs.append(f"ausente: {rel}")
        elif _sha(p.read_bytes()) != _sha(arqs[rel]):
            difs.append(f"diferente: {rel}")
    antigos = set(ler_gerado(saida))
    if so_dados:
        esperado = set(arqs) | {r for r in antigos if not r.startswith("dados/")}
    else:
        esperado = set(arqs)
    for rel in sorted(antigos - esperado):
        difs.append(f"sobrando em .gerado: {rel}")
    for rel in sorted(esperado - antigos):
        difs.append(f"faltando em .gerado: {rel}")
    return difs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gerar_site.py",
                                 description="Estágio B: gera docs/ a partir de base/, fontes/, modelos/ e docs/config.js.")
    ap.add_argument("--base", default=str(RAIZ / "base"))
    ap.add_argument("--fontes", default=str(RAIZ / "fontes"))
    ap.add_argument("--modelos", default=str(RAIZ / "modelos"))
    ap.add_argument("--saida", default=str(RAIZ / "docs"))
    ap.add_argument("--config", default=str(RAIZ / "docs" / "config.js"))
    ap.add_argument("--verificar", action="store_true", help="gera em memória e compara com a saída, sem gravar")
    ap.add_argument("--so-dados", action="store_true", help="gera só <saida>/dados/")
    try:
        a = ap.parse_args([] if argv is None else argv)  # main() sem argumentos = tudo padrão
    except SystemExit as e:
        return 0 if e.code in (0, None) else 2
    saida = pathlib.Path(a.saida)
    cfg_path = pathlib.Path(a.config)
    try:
        from pd.config import ler_config
        if not cfg_path.is_file():
            raise ErroUso(f"config.js não encontrado: {cfg_path.name}")
        cfg = ler_config(str(cfg_path))
        base = pathlib.Path(a.base)
        if not base.is_dir():
            raise ErroUso("pasta da base não encontrada")
        arqs = gerar(base, pathlib.Path(a.fontes), pathlib.Path(a.modelos), cfg, so_dados=a.so_dados)
    except ErroUso as e:
        print(f"erro de uso: {e}", file=sys.stderr)
        return 2
    except ErroGate as e:
        print(f"gate do estágio B falhou ({len(e.erros)} erro(s)); nada foi gravado:", file=sys.stderr)
        for m in e.erros[:30]:
            print(f"  - {m}", file=sys.stderr)
        return 1
    except ValueError as e:  # ErroConfig, ErroEsquema, JSON inválido
        print(f"erro: {e}", file=sys.stderr)
        return 1
    if a.verificar:
        difs = verificar(arqs, saida, a.so_dados)
        if difs:
            print(f"--verificar: {len(difs)} diferença(s)")
            for d in difs[:30]:
                print(f"  - {d}")
            return 1
        print(f"--verificar: idêntico ({len(arqs)} arquivos)")
        return 0
    if not saida.is_dir():
        print("erro de uso: pasta de saída não existe", file=sys.stderr)
        return 2
    r = gravar(arqs, saida, a.so_dados)
    print(f"estágio B: {r['total']} arquivos ({r['escritos']} gravados, {r['removidos']} removidos)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
