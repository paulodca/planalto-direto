"""ESTÁGIO A: monta a base pública (``base/``) a partir dos insumos privados (SPEC §7).

Roda só na máquina do dono. Todo insumo privado entra por argumento ou variável de
ambiente; nenhum caminho de disco fica no código. O relatório nunca é gravado dentro
do repositório.
"""
from __future__ import annotations

import sys
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import argparse  # noqa: E402
import collections  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import sqlite3  # noqa: E402

from pd import ancoras as anc  # noqa: E402
from pd import cache_html  # noqa: E402
from pd import esquemas  # noqa: E402
from pd import jsonio  # noqa: E402
from pd import normas as nor  # noqa: E402
from pd import ordem  # noqa: E402

CF_K = "cf-1988"
CF_CAMINHO = "constituicao/constituicao.htm"
MAX_EXEMPLOS = 50

# Campos do registro de âncora que o estágio A lê (os demais são ignorados na leitura).
CAMPO_INI = "inicio"
CAMPO_SR = "so_riscada"
CAMPO_RISC = "riscado"


class ErroBuild(Exception):
    pass


class ErroUso(Exception):
    pass


# ====================================================================== utilidades
class Relatorio:
    def __init__(self):
        self.linhas: list[str] = []
        self.cont = collections.Counter()
        self.exemplos: dict[str, list[str]] = collections.defaultdict(list)

    def __call__(self, s: str = "") -> None:
        self.linhas.append(s)

    def conta(self, motivo: str, exemplo: str | None = None, n: int = 1) -> None:
        self.cont[motivo] += n
        if exemplo is not None and len(self.exemplos[motivo]) < MAX_EXEMPLOS:
            self.exemplos[motivo].append(exemplo)

    def texto(self) -> str:
        return "\n".join(self.linhas) + "\n"


def _rel(url: str) -> str:
    return nor.caminho_relativo(url)


def _ler_jsonl_campos(caminho, campos: tuple[str, ...]):
    """Lê um JSONL qualquer devolvendo só ``campos`` de cada linha (o resto é descartado na leitura)."""
    with open(caminho, "r", encoding="utf-8") as f:
        for n, linha in enumerate(f, 1):
            linha = linha.strip()
            if not linha:
                continue
            try:
                d = json.loads(linha)
            except json.JSONDecodeError as e:
                raise ErroBuild(f"{pathlib.Path(caminho).name}: linha {n}: JSON inválido ({e})") from None
            yield {c: d.get(c) for c in campos}


def _dentro_do_repo(p: pathlib.Path) -> bool:
    try:
        p.resolve().relative_to(RAIZ.resolve())
        return True
    except ValueError:
        return False


def _arg_ou_env(valor, env: str):
    if valor:
        return valor
    v = os.environ.get(env, "").strip()
    return v or None


# ====================================================================== snapshot
def ler_snapshot(caminho: str, rel: Relatorio):
    uri = f"file:{pathlib.Path(caminho).as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        total = con.execute("SELECT count(*) FROM normas").fetchone()[0]
        linhas = con.execute(
            "SELECT tipo, numero, sufixo, rotulo, ementa, data_txt, url, indice FROM normas ORDER BY url"
        ).fetchall()
        idx = con.execute("SELECT url, quando, sha256, bytes FROM indices ORDER BY url").fetchall()
    finally:
        con.close()
    if len(linhas) != total:
        raise ErroBuild("snapshot: contagem divergente")
    quandos = [q for _u, q, _s, _b in idx if q]
    if not quandos:
        raise ErroBuild("snapshot: tabela indices sem data")
    max_q = max(quandos)
    desde = max_q[:10]
    ano_ref = int(desde[:4])
    brutas = [dict(zip(("tipo", "numero", "sufixo", "rotulo", "ementa", "data_txt", "url", "indice"), l))
              for l in linhas]
    indices = {}
    for u, q, s, b in idx:
        indices[_rel(u)] = {"bytes": int(b or 0), "quando": (q or "")[:10], "sha256": s or ""}
    return brutas, total, indices, ano_ref, desde


def normalizar_normas(brutas, ano_ref: int, desde: str, rel: Relatorio):
    normas = []
    erros = []
    cortes = collections.Counter()
    um_ano = 0
    for b in brutas:
        tipo = b["tipo"]
        try:
            tsig = nor.tsig_de(tipo)
        except ValueError as e:
            erros.append(str(e))
            continue
        url, indice = b["url"], b["indice"] or ""
        fi = nor.faixa_indice(indice, ano_ref)
        if fi and fi[0] == fi[1]:
            um_ano += 1
        try:
            ano = nor.ano_de(b["rotulo"], b["data_txt"], url, indice, ano_ref)
        except nor.ErroAno as e:
            erros.append(str(e))
            continue
        letra = nor.letra_de(tipo, b["sufixo"], b["rotulo"], url)
        reed = nor.reed_de(tipo, b["sufixo"])
        numero = int(b["numero"])
        k = nor.chave(tsig, numero, letra, ano)
        ementa, cs = nor.limpar_ementa_detalhe(b["ementa"], tipo)
        for c in cs:
            cortes[c] += 1
        if "veto" in cs:
            cortes["normas_com_veto"] += 1
        if tipo == "medida provisoria" and any(c.startswith("status") for c in cs):
            cortes["mps_com_status"] += 1
        normas.append({
            "k": k, "tipo": tipo, "tsig": tsig, "numero": numero, "letra": letra, "reed": reed,
            "ano": ano, "data": nor.data_iso(b["data_txt"], b["rotulo"], ano),
            "rotulo": nor.normalizar_espacos(b["rotulo"]), "ementa": ementa,
            "caminho_indice": _rel(url), "indice": _rel(indice) if indice else "",
            "desde": desde,
        })
    rel(f"normas do snapshot: {len(brutas)}; normalizadas: {len(normas)}; erros: {len(erros)}")
    rel(f"ano pelo bucket de um ano: {um_ano}")
    rel(f"normas com letra: {sum(1 for n in normas if n['letra'])}")
    rel(f"ementas: com veto cortado {cortes['normas_com_veto']}; MPs com status cortado {cortes['mps_com_status']}"
        f" (cortes: status {cortes['status']}, status solto {cortes['status_solto']})")
    rel(f"ementas vazias depois da limpeza: {sum(1 for n in normas if not n['ementa'])}")
    por_tipo = collections.Counter(n["tsig"] for n in normas)
    rel("normas por tipo: " + ", ".join(f"{t} {por_tipo[t]}" for t in nor.ORDEM_TIPOS if por_tipo[t]))
    return normas, erros


# ====================================================================== compilados
def ler_compilados(caminho: str, chaves_por_caminho: dict) -> dict[str, str]:
    """Mapa de compilados: ``caminho_indice.lower() -> compilado`` (relativo, como está)."""
    mapa = {}
    faltam = []
    for d in _ler_jsonl_campos(caminho, ("url", "compilado")):
        if not d["url"]:
            continue
        u = _rel(d["url"]).lower()
        if u not in chaves_por_caminho:
            faltam.append(u)
            continue
        if d["compilado"]:
            mapa[u] = _rel(d["compilado"])
    if faltam:
        raise ErroBuild(f"mapa de compilados: {len(faltam)} url sem norma na base, ex.: {faltam[:5]}")
    return mapa


# ====================================================================== âncoras
def ler_ancoras(caminho: str):
    campos = ("url", "url_final", "versao", "parte", "artigo", "disp", "ancora", CAMPO_INI, CAMPO_SR)
    return list(_ler_jsonl_campos(caminho, campos))


def processar_ancoras(regs, por_caminho_indice: dict, por_compilado: dict, cache_raiz, rel: Relatorio):
    """Filtros (§7.4.1), reparos (§7.4.3), verificação (§7.4.2/§7.4.4), deduplicação e cache (§7.4.1a).

    Devolve (candidatas, observados, prefixos_ini, pares_riscados, paginas_cache).
    """
    observados: dict[str, str] = {}
    arts_com_letra: dict[tuple, set] = collections.defaultdict(set)
    prefixos: set[str] = set()
    pares = collections.defaultdict(lambda: [0, 0])     # (página, âncora) -> [total, só riscada]
    for r in regs:
        uf = _rel(r["url_final"])
        u = _rel(r["url"])
        observados.setdefault(u.lower(), uf)
        observados.setdefault(uf.lower(), uf)
        if "-" in (r["artigo"] or ""):
            arts_com_letra[(u.lower(), r["parte"] or "")].add(r["artigo"])
        ini = nor.normalizar_espacos(r[CAMPO_INI] or "")
        if len(ini) >= 40:
            prefixos.add(ini[:40])
        p = pares[(uf.lower(), r["ancora"])]
        p[0] += 1
        if r[CAMPO_SR]:
            p[1] += 1

    candidatas: dict[tuple, dict] = {}
    rep = collections.Counter()
    for i, r in enumerate(regs):
        u = _rel(r["url"]).lower()
        uf = _rel(r["url_final"])
        ex = f"{uf}#{r['ancora']}"
        if r[CAMPO_SR]:
            rel.conta("descartada: so_riscada", ex)
            continue
        if u in por_caminho_indice:
            k, versao = por_caminho_indice[u], "h"
        elif u in por_compilado:
            k, versao = por_compilado[u], "c"
        else:
            rel.conta("descartada: URL sem norma", ex)
            continue
        if (r["versao"] == "indice") != (versao == "h"):
            rel.conta("aviso: versao do registro difere do mapa", ex)
        parte = r["parte"] or ""
        if parte not in ("", "adct"):
            rel.conta("descartada: parte desconhecida", ex)
            continue
        if parte == "adct" and k != CF_K:
            rel.conta("descartada: adct fora da CF", ex)
            continue
        if not anc.ancora_valida(r["ancora"] or ""):
            rel.conta("descartada: âncora com caractere fora do alfabeto", ex)
            continue
        artigo, disp = r["artigo"] or "", r["disp"] or ""
        artigo, disp, motivo = anc.reparar_letra(artigo, disp, r[CAMPO_INI] or "",
                                                 arts_com_letra.get((u, parte), ()))
        if motivo:
            rep[motivo] += 1
        canon, erro = anc.verificar(artigo, disp, r[CAMPO_INI] or "")
        nivel = "dispositivo" if disp else "artigo"
        if canon is None:
            rel.conta(f"descartada: {erro}", ex)
            rel.cont[f"nivel {nivel}: reprovada"] += 1
            continue
        rel.cont[f"nivel {nivel}: ok"] += 1
        chave = (uf.lower(), parte, canon)
        nova = {"k": k, "versao": versao, "pagina": uf, "parte": parte, "disp": canon,
                "ancora": r["ancora"], "i": i}
        velha = candidatas.get(chave)
        if velha is not None:
            if velha["ancora"] != nova["ancora"]:
                rel.conta("conflito pós-reparo", f"{uf}: {velha['ancora']} x {nova['ancora']}")
            if anc.pontos_variante(nova["ancora"]) >= anc.pontos_variante(velha["ancora"]):
                candidatas[chave] = nova
        else:
            candidatas[chave] = nova
    rel(f"reparos de letra: 1º {rep['reparo1']}, 2º {rep['reparo2']}")
    rel(f"verificação: artigo ok {rel.cont['nivel artigo: ok']} x reprovado {rel.cont['nivel artigo: reprovada']}; "
        f"dispositivo ok {rel.cont['nivel dispositivo: ok']} x reprovado {rel.cont['nivel dispositivo: reprovada']}")
    rel(f"âncoras aprovadas antes do cache (depois da deduplicação): {len(candidatas)}")

    # ---- conferência no cache (I13)
    por_pagina = collections.defaultdict(list)
    for c in candidatas.values():
        por_pagina[c["pagina"].lower()].append(c)
    paginas: dict[str, dict] = {}
    finais = []
    for pag in sorted(por_pagina):
        arq = cache_html.caminho_no_cache(cache_raiz, pag)
        if not arq.is_file():
            for c in por_pagina[pag]:
                rel.conta("descartada: página fora do cache", f"{c['pagina']}#{c['ancora']}")
            continue
        mapa = cache_html.ancoras_da_pagina(cache_html.decodificar(arq.read_bytes()))
        paginas[pag] = mapa
        for c in sorted(por_pagina[pag], key=lambda x: x["i"]):
            st = mapa.get(c["ancora"], "ausente")
            if st == "ausente":
                rel.conta("descartada: âncora fora da página", f"{c['pagina']}#{c['ancora']}")
            elif st is True:
                rel.conta("descartada: texto seguinte riscado", f"{c['pagina']}#{c['ancora']}")
            else:
                finais.append(c)
    rel(f"âncoras aprovadas depois do cache: {len(finais)}")
    return finais, observados, prefixos, pares, paginas


# ====================================================================== caminhos
def aplicar_caminhos(normas_por_k: dict, compilados: dict, observados: dict, subs: dict, cache_raiz,
                     rel: Relatorio):
    """§5.7 + §6.2a. Devolve o conjunto de (k, campo) substituídos e os caminhos válidos (G8)."""
    for n in normas_por_k.values():
        ci = n["caminho_indice"]
        n["caminho"] = observados.get(ci.lower(), ci)
        comp = compilados.get(ci.lower(), "")
        n["caminho_compilado"] = observados.get(comp.lower(), comp) if comp else ""
    validos = set()
    for n in normas_por_k.values():
        validos.add(n["caminho_indice"])
    validos.update(observados.values())
    validos.update(compilados.values())

    erros = esquemas.validar_caminhos(subs, set(normas_por_k))
    if erros:
        raise ErroBuild("G12: fontes/caminhos.json inválido: " + "; ".join(erros))
    substituidos = set()
    for s in subs["substituicoes"]:
        n = normas_por_k[s["k"]]
        atual = n[s["campo"]]
        if atual.lower() != s["de"].lower():
            raise ErroBuild(f"G12: {s['k']}/{s['campo']}: 'de' ({s['de']}) não bate com {atual!r}; reconferir")
        if s["para"]:
            if not cache_html.caminho_no_cache(cache_raiz, s["para"]).is_file():
                raise ErroBuild(f"G12: {s['k']}: 'para' não existe no cache")
            validos.add(s["para"])
        else:
            if not cache_html.caminho_no_cache(cache_raiz, n["caminho"]).is_file():
                raise ErroBuild(f"G12: {s['k']}: caminho da norma não existe no cache")
        n[s["campo"]] = s["para"]
        substituidos.add((s["k"], s["campo"]))
        rel(f"substituição curada: {s['k']} {s['campo']}: {s['de']} -> {s['para'] or '(vazio)'}")
    return substituidos, validos


def montar_por_norma(finais, normas_por_k: dict, substituidos: set, rel: Relatorio):
    out: dict[str, dict] = {}
    for c in sorted(finais, key=lambda x: x["i"]):
        n = normas_por_k[c["k"]]
        campo = "caminho" if c["versao"] == "h" else "caminho_compilado"
        alvo = n[campo]
        if c["pagina"].lower() != alvo.lower():
            if (c["k"], campo) in substituidos:
                rel.conta("descartada: caminho substituído", f"{c['pagina']}#{c['ancora']}")
                continue
            raise ErroBuild(f"âncora de {c['pagina']} não bate com {campo} de {c['k']} ({alvo!r})")
        a = out.setdefault(c["k"], {"k": c["k"], "h": n["caminho"], "c": n["caminho_compilado"], "corpo": {}})
        parte = "adct" if c["parte"] == "adct" else "corpo"
        mapa = a.setdefault(parte, {})
        vers = mapa.setdefault(c["disp"], {})
        if c["versao"] in vers and vers[c["versao"]] != c["ancora"]:
            raise ErroBuild(f"conflito de âncora em {c['k']} {parte} {c['disp']} {c['versao']}")
        vers[c["versao"]] = c["ancora"]
    for a in out.values():
        for parte in ("corpo", "adct"):
            if parte in a:
                a[parte] = dict(sorted(a[parte].items()))
    return out


# ====================================================================== desempate
def ler_membros_lista(caminho: str, por_caminho_indice: dict) -> set[str]:
    """Só a pertinência à lista privada (chaves da base). Nada mais sai desta função."""
    membros = set()
    for d in _ler_jsonl_campos(caminho, ("url",)):
        if not d["url"]:
            continue
        try:
            u = _rel(d["url"]).lower()
        except ValueError:
            continue
        k = por_caminho_indice.get(u)
        if k:
            membros.add(k)
    return membros


def grupos_de(normas: list[dict]) -> dict[str, list[str]]:
    num = collections.defaultdict(list)
    tip = collections.defaultdict(list)
    for n in normas:
        if n["tsig"] == "cf":
            continue
        sufixo = f"{n['numero']}{n['letra']}"
        num[f"num:{sufixo}"].append(n["k"])
        tip[f"{n['tsig']}:{sufixo}"].append(n["k"])
    g = {}
    for d in (num, tip):
        for nome, ks in d.items():
            if len(ks) >= 2:
                g[nome] = ks
    return g


def calcular_desempate(normas: list[dict], membros: set[str], alvos_apelido: set[str]):
    """§7.6: entrada só se o grupo tem exatamente um membro na lista e ele não é o 1º da ordem pública."""
    saida = {}
    multi = 0
    for g, ks in grupos_de(normas).items():
        d = ordem.ordem_publica(ks, alvos_apelido)
        b = [k for k in ks if k in membros]
        if len(b) >= 2:
            multi += 1
        if len(b) != 1:
            continue
        p = b[0]
        if d[0] != p and d[0] not in alvos_apelido:
            saida[g] = p
    return dict(sorted(saida.items(), key=lambda kv: ordem.ordem_grupo(kv[0]))), multi


def conferir_g13(caminho: str, desempate: dict, normas: list[dict], brutas_por_caminho: dict,
                 por_caminho_indice: dict) -> list[str]:
    """G13: nenhum grupo publicado com >= 2 membros; ementa/rótulo vêm do snapshot, não da lista."""
    erros = []
    membros = ler_membros_lista(caminho, por_caminho_indice)
    grupos = grupos_de(normas)
    for g in desempate:
        if sum(1 for k in grupos.get(g, ()) if k in membros) >= 2:
            erros.append(f"G13: grupo {g} com 2 ou mais membros na lista privada")
    por_k = {n["k"]: n for n in normas}
    iguais = 0
    for d in _ler_jsonl_campos(caminho, ("url", "ementa", "rotulo")):
        try:
            u = _rel(d["url"] or "").lower()
        except ValueError:
            continue
        k = por_caminho_indice.get(u)
        b = brutas_por_caminho.get(u)
        if not k or b is None:
            continue
        n = por_k[k]
        for campo in ("ementa", "rotulo"):
            v = d[campo]
            if not isinstance(v, str) or not v:
                continue
            if campo == "ementa":
                v_l, s_l = nor.limpar_ementa(v, b["tipo"]), nor.limpar_ementa(b[campo], b["tipo"])
            else:
                v_l, s_l = nor.normalizar_espacos(v), nor.normalizar_espacos(b[campo])
            if v_l != s_l and n[campo] == v_l:
                iguais += 1
    if iguais:
        erros.append(f"G13: {iguais} ementas/rótulos da base iguais aos da lista privada (e não aos do snapshot)")
    return erros


# ====================================================================== diagnóstico (opcional)
def diagnostico_preambulo(caminho: str, rel: Relatorio) -> None:
    grupos = collections.defaultdict(set)
    campos = ("url", "parte", "artigo", "disp", "ancora", CAMPO_INI, CAMPO_RISC)
    for d in _ler_jsonl_campos(caminho, campos):
        if d[CAMPO_RISC] or not d["ancora"]:
            continue
        canon, _e = anc.verificar(d["artigo"] or "", d["disp"] or "", d[CAMPO_INI] or "")
        if canon is None:
            continue
        grupos[(_rel(d["url"]).lower(), d["parte"] or "", canon)].add(d["ancora"])
    multi = [(g, sorted(v)) for g, v in grupos.items() if len(v) > 1]
    multi.sort()
    rel(f"diagnóstico: grupos com mais de uma âncora não riscada que confere: {len(multi)}")
    for g, v in multi[:MAX_EXEMPLOS]:
        rel(f"  {g[0]} {g[1] or 'corpo'} {g[2]}: {', '.join(v)}")


# ====================================================================== gates
def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


CASOS_G5 = [
    ("dl-5452-1943", "corpo", "477", {"c": "art477..", "h": "art477.."}),
    ("dl-5452-1943", "corpo", "790-B", {"c": "art790b."}),
    ("dl-5452-1943", "corpo", "2", {"c": "art2.", "h": "art2."}),
    ("dl-5452-1943", "corpo", "1", {"c": "art1.", "h": "art1."}),
    ("dl-5452-1943", "corpo", "8|§1", {"c": "art8§1"}),
    ("dl-5452-1943", "corpo", "8|pu", None),
    ("dl-5452-1943", "corpo", "11-A|§1", {"c": "art11a§1"}),
    ("cf-1988", "corpo", "7|XXIX", {"h": "art7xxix"}),
    ("cf-1988", "adct", "76", {"h": "adctart76.2"}),
    ("lei-13105-2015", "corpo", "1022", {"c": "art1022", "h": "art1022"}),
]


def gates(saida_normas, saida_anc, desempate, indices, ctx, rel: Relatorio) -> list[str]:
    erros = []
    por_k = {n["k"]: n for n in saida_normas}
    # G1
    faltam = [k for k in ctx["chaves_snapshot"] if k not in por_k]
    if ctx["lidas"] != ctx["total_snapshot"] or faltam:
        erros.append(f"G1: lidas {ctx['lidas']} de {ctx['total_snapshot']}; ausentes {len(faltam)}")
    if len(saida_normas) < ctx["total_snapshot"] + 1 + ctx["extras_base"]:
        erros.append("G1: base menor que snapshot + CF + acrescentadas")
    # G2
    if ctx["erros_normas"]:
        erros.append(f"G2: {len(ctx['erros_normas'])} normas sem ano/tipo: {ctx['erros_normas'][:3]}")
    if len(por_k) != len(saida_normas):
        erros.append("G2: chaves duplicadas")
    # G3 + esquema
    e = esquemas.validar_normas(saida_normas)
    if e:
        erros.append(f"G3/esquema: {len(e)} erros em normas: {e[:5]}")
    # G4
    for nome, func in (("apelidos.json", esquemas.validar_apelidos), ("areas.json", esquemas.validar_areas),
                       ("avisos.json", esquemas.validar_avisos)):
        p = ctx["fontes"] / nome
        if not p.exists():
            rel(f"aviso G4: fontes/{nome} ainda não existe")
            continue
        if ctx["so_fixture"]:
            continue
        e = func(jsonio.ler_json(p), set(por_k))
        if e:
            erros.append(f"G4: fontes/{nome}: {e[:5]}")
    # G5 (sobre a base completa)
    anc_full = ctx["anc_full"]
    for k, parte, disp, esperado in CASOS_G5:
        v = anc_full.get(k, {}).get(parte, {}).get(disp)
        if esperado is None:
            if v is not None:
                erros.append(f"G5: {k} {parte} {disp} deveria estar ausente, tem {v}")
        else:
            for ver, nome in esperado.items():
                if not v or v.get(ver) != nome:
                    erros.append(f"G5: {k} {parte} {disp} {ver}: esperado {nome}, obtido {v}")
    # G6, G10, G11
    pares, paginas = ctx["pares"], ctx["paginas"]
    for a in saida_anc.values():
        e = esquemas.validar_ancoras(a, por_k.get(a["k"]))
        if e:
            erros.append(f"esquema âncoras: {e[:3]}")
        for parte in ("corpo", "adct"):
            for disp, vers in a.get(parte, {}).items():
                for ver, nome in vers.items():
                    pag = (a["h"] if ver == "h" else a["c"]).lower()
                    tot, sr = pares.get((pag, nome), (0, 0))
                    if tot == 0 or tot == sr:
                        erros.append(f"G6: {a['k']} {disp} {ver} {nome}: sem registro não riscado")
                    st = paginas.get(pag, {}).get(nome, "ausente")
                    if st == "ausente" or st is True:
                        erros.append(f"G10: {a['k']} {disp} {ver} {nome}: {st}")
                    if not anc.ancora_valida(nome):
                        erros.append(f"G11: {a['k']} {nome}")
    for r in ctx["sr_publicados"]:
        erros.append(f"G6: registro so_riscada publicado: {r}")
    # G7, G9
    objs = [saida_normas, list(saida_anc.values()), desempate, indices]
    for o in objs:
        for s in _strings(o):
            if ":~:" in s:
                erros.append("G7: ':~:' na base")
                break
        cp = esquemas.campos_proibidos(o)
        if cp:
            erros.append(f"G9: campos proibidos: {cp[:5]}")
    for t in ctx["textos"]:
        for c in esquemas.CAMPOS_PROIBIDOS:
            if re.search('"' + re.escape(c) + r'"\s*:', t):
                erros.append(f"G9: campo proibido no texto: {c}")
    # G8
    validos = ctx["validos"]
    for n in saida_normas:
        for campo in ("caminho", "caminho_compilado"):
            v = n[campo]
            if v and v not in validos:
                erros.append(f"G8: {n['k']} {campo} {v!r} não vem do índice/observado/mapa")
    # G13 (desempate restrito por construção) — conferência com a lista feita fora
    erros.extend(ctx["erros_g13"])
    # G14
    prefixos = ctx["prefixos"]
    if prefixos:
        achados = 0
        for o in objs:
            for s in _strings(o):
                s2 = nor.normalizar_espacos(s)
                for j in range(0, len(s2) - 39):
                    if s2[j:j + 40] in prefixos:
                        achados += 1
                        break
        if achados:
            erros.append(f"G14: {achados} strings da base contêm início de âncora")
    e = esquemas.validar_desempate(desempate, set(por_k))
    if e:
        erros.append(f"esquema desempate: {e[:3]}")
    e = esquemas.validar_indices(indices)
    if e:
        erros.append(f"esquema indices: {e[:3]}")
    return erros


# ====================================================================== escrita
def conteudo_saida(normas, ancs, desempate, indices) -> dict[str, bytes]:
    arquivos = {
        "normas.jsonl": jsonio.texto_jsonl(normas).encode("utf-8"),
        "desempate.json": jsonio.dumps(desempate).encode("utf-8"),
        "indices.json": jsonio.dumps(indices).encode("utf-8"),
    }
    for k, a in ancs.items():
        arquivos[f"ancoras/{k}.json"] = jsonio.dumps(a).encode("utf-8")
    return arquivos


def existentes(saida: pathlib.Path) -> dict[str, pathlib.Path]:
    r = {}
    for nome in ("normas.jsonl", "desempate.json", "indices.json"):
        p = saida / nome
        if p.is_file():
            r[nome] = p
    d = saida / "ancoras"
    if d.is_dir():
        for p in d.glob("*.json"):
            r[f"ancoras/{p.name}"] = p
    return r


def gravar(saida: pathlib.Path, arquivos: dict[str, bytes]) -> None:
    tmp = saida.parent / f"{saida.name}.tmp-{os.getpid()}"
    try:
        if tmp.exists():
            shutil.rmtree(tmp)
        for rel_, dados in arquivos.items():
            p = tmp / rel_
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(dados)
        (saida / "ancoras").mkdir(parents=True, exist_ok=True)
        for rel_ in sorted(arquivos):
            os.replace(tmp / rel_, saida / rel_)
        for rel_, p in existentes(saida).items():
            if rel_ not in arquivos:
                p.unlink()
    finally:
        if tmp.exists():
            shutil.rmtree(tmp)


# ====================================================================== principal
def _ler_chaves_fixture(v: str) -> list[str]:
    if v.startswith("@"):
        txt = pathlib.Path(v[1:]).read_text(encoding="utf-8")
        ks = [l.split("#", 1)[0].strip() for l in txt.splitlines()]
    else:
        ks = [x.strip() for x in v.split(",")]
    return [k for k in ks if k]


def montar(args, rel: Relatorio):
    snapshot = _arg_ou_env(args.snapshot, "PD_SNAPSHOT")
    ancoras_p = _arg_ou_env(args.ancoras, "PD_ANCORAS")
    compilados_p = _arg_ou_env(args.compilados, "PD_COMPILADOS")
    cache_raiz = _arg_ou_env(args.cache_html, "PD_CACHE_HTML")
    lista_p = _arg_ou_env(args.lista_privada, "PD_LISTA_PRIVADA")
    todas_p = _arg_ou_env(args.ancoras_todas, "PD_ANCORAS_TODAS")
    faltam = [n for n, v in (("--snapshot/PD_SNAPSHOT", snapshot), ("--ancoras/PD_ANCORAS", ancoras_p),
                             ("--compilados/PD_COMPILADOS", compilados_p),
                             ("--cache-html/PD_CACHE_HTML", cache_raiz)) if not v]
    if faltam:
        raise ErroUso(f"faltam insumos obrigatórios: {', '.join(faltam)}")
    if lista_p and ";" in lista_p:
        lista_p = lista_p.split(";")[0].strip()
    cache_raiz = pathlib.Path(cache_raiz)
    if not (cache_raiz / cache_html.HOST / cache_html.PASTA).is_dir():
        raise ErroUso("--cache-html não contém www.planalto.gov.br/ccivil_03/")
    saida = pathlib.Path(args.saida) if args.saida else RAIZ / "base"
    if not saida.is_absolute():
        saida = (pathlib.Path.cwd() / saida)
    fontes = RAIZ / "fontes"
    caminhos_p = pathlib.Path(args.caminhos) if args.caminhos else fontes / "caminhos.json"

    rel("# Relatório do estágio A")
    brutas, total, indices_snap, ano_ref, desde = ler_snapshot(snapshot, rel)
    rel(f"data do snapshot: {desde}; ano_ref: {ano_ref}")
    normas, erros_normas = normalizar_normas(brutas, ano_ref, desde, rel)
    brutas_por_caminho = {_rel(b["url"]).lower(): b for b in brutas}
    normas_snapshot = list(normas)

    cf = dict(nor.CF_REGISTRO)
    cf["desde"] = desde
    normas.append(cf)

    # ---- mescla com a base existente (§7.2 passo 10)
    base_exist = []
    if (saida / "normas.jsonl").is_file():
        base_exist = jsonio.ler_jsonl(saida / "normas.jsonl")
    por_ident = {n["caminho_indice"].lower(): n for n in normas}
    extras_base = 0
    for b in base_exist:
        ident = b["caminho_indice"].lower()
        n = por_ident.get(ident)
        if n is None:
            extras_base += 1
            novo = dict(b)
            novo["_base"] = True
            normas.append(novo)
            por_ident[ident] = novo
            continue
        for campo in ("ementa", "rotulo"):
            if b.get(campo) != n[campo]:
                rel.conta(f"mescla: {campo} mudou", f"{b['k']}")
        n["k"], n["ano"], n["letra"] = b["k"], b["ano"], b["letra"]
        n["desde"] = min(n["desde"], b.get("desde") or n["desde"])
    if extras_base:
        rel(f"normas da base fora do snapshot (mantidas): {extras_base}")
    cont_k = collections.Counter(n["k"] for n in normas)
    dup = sorted(k for k, c in cont_k.items() if c > 1)
    if dup:
        raise ErroBuild(f"G2: chaves duplicadas: {dup[:20]}")
    normas_por_k = {n["k"]: n for n in normas}
    chaves_snapshot = [n["k"] for n in normas_snapshot]
    por_caminho_indice = {n["caminho_indice"].lower(): n["k"] for n in normas}

    compilados = ler_compilados(compilados_p, por_caminho_indice)
    por_compilado = {c.lower(): por_caminho_indice[u] for u, c in compilados.items()}
    rel(f"mapa de compilados: {len(compilados)} normas com compilado")

    regs = ler_ancoras(ancoras_p)
    rel(f"âncoras lidas: {len(regs)}")
    finais, observados, prefixos, pares, paginas = processar_ancoras(
        regs, por_caminho_indice, por_compilado, cache_raiz, rel)
    sr_publicados = [f"{c['pagina']}#{c['ancora']}" for c in finais if regs[c["i"]][CAMPO_SR]]
    del regs

    subs = jsonio.ler_json(caminhos_p) if caminhos_p.is_file() else {"substituicoes": [], "versao": 1}
    # normas que vieram só da base existente já têm caminho; as do snapshot recebem pelo §5.7
    base_so = {n["k"]: n for n in normas if n.get("_base")}
    snap = {k: n for k, n in normas_por_k.items() if k not in base_so}
    substituidos, validos = aplicar_caminhos(snap, compilados, observados, subs, cache_raiz, rel)
    for n in base_so.values():
        validos.update(x for x in (n.get("caminho"), n.get("caminho_compilado")) if x)
    anc_full = montar_por_norma(finais, normas_por_k, substituidos, rel)

    # ---- desempate
    alvos_apelido = set()
    ap_p = fontes / "apelidos.json"
    if ap_p.is_file():
        alvos_apelido = {a["alvo"] for a in jsonio.ler_json(ap_p).get("apelidos", [])}
    else:
        rel("aviso: fontes/apelidos.json ausente; desempate calculado sem alvos de apelido")

    for n in normas:
        n.pop("_base", None)
    normas.sort(key=lambda n: ordem.ordem_chave(n["k"]))
    campos = sorted(esquemas.CAMPOS_NORMA)
    normas = [{c: n[c] for c in campos} for n in normas]

    so_fixture = None
    if args.so_fixture:
        so_fixture = _ler_chaves_fixture(args.so_fixture)
        faltam_k = [k for k in so_fixture if k not in normas_por_k]
        if faltam_k:
            raise ErroBuild(f"--so-fixture: chaves inexistentes: {faltam_k}")

    def desempate_de(lista_normas):
        if not lista_p:
            return {"grupos": {}, "versao": 1}, 0
        membros = ler_membros_lista(lista_p, por_caminho_indice)
        g, multi = calcular_desempate(lista_normas, membros, alvos_apelido)
        return {"grupos": g, "versao": 1}, multi

    desempate, multi = desempate_de(normas)
    rel(f"desempate: {len(desempate['grupos'])} grupos com desempate"
        + ("" if lista_p else " (sem lista privada)"))

    # ---- índices
    indices = {}
    if (saida / "indices.json").is_file():
        indices = dict(jsonio.ler_json(saida / "indices.json").get("indices", {}))
    for u, r in indices_snap.items():
        velho = indices.get(u)
        if velho is None or r["quando"] >= velho.get("quando", ""):
            indices[u] = r
    indices_obj = {"indices": dict(sorted(indices.items())), "versao": 1}

    erros_g13 = []
    if lista_p:
        erros_g13 = conferir_g13(lista_p, desempate["grupos"], normas, brutas_por_caminho, por_caminho_indice)

    # ---- recorte da fixture
    if so_fixture:
        sel = set(so_fixture)
        saida_normas = [n for n in normas if n["k"] in sel]
        saida_anc = {k: a for k, a in anc_full.items() if k in sel}
        desempate_s, _m = desempate_de(saida_normas)
        rel(f"fixture: {len(saida_normas)} normas, {len(saida_anc)} com âncoras, "
            f"{len(desempate_s['grupos'])} grupos de desempate")
    else:
        saida_normas, saida_anc, desempate_s = normas, anc_full, desempate
    saida_anc = dict(sorted(saida_anc.items(), key=lambda kv: ordem.ordem_chave(kv[0])))

    arquivos = conteudo_saida(saida_normas, saida_anc, desempate_s, indices_obj)
    ctx = {
        "chaves_snapshot": chaves_snapshot, "lidas": len(brutas), "total_snapshot": total,
        "extras_base": extras_base, "erros_normas": erros_normas, "fontes": fontes,
        "so_fixture": bool(so_fixture), "anc_full": anc_full, "pares": pares, "paginas": paginas,
        "sr_publicados": sr_publicados, "validos": validos, "erros_g13": erros_g13, "prefixos": prefixos,
        "textos": [b.decode("utf-8") for b in arquivos.values()],
    }
    # gates sobre a base completa (sempre) e sobre a saída
    erros = gates(normas, anc_full, desempate, indices_obj, ctx, rel)
    if so_fixture:
        ctx2 = dict(ctx, chaves_snapshot=[], lidas=total, extras_base=0)
        e2 = gates(saida_normas, saida_anc, desempate_s, indices_obj, ctx2, rel)
        erros.extend(x for x in e2 if not x.startswith("G1:"))

    # ---- relatório final
    n_anc = sum(len(v) for a in anc_full.values() for p in ("corpo", "adct") for v in a.get(p, {}).values())
    pub = collections.Counter()
    for a in anc_full.values():
        for p in ("corpo", "adct"):
            for vers in a.get(p, {}).values():
                for ver in vers:
                    pub[(ver, p)] += 1
    rel(f"âncoras publicadas: {n_anc} em {len(anc_full)} normas; por versão/parte: "
        + ", ".join(f"{v}/{p} {c}" for (v, p), c in sorted(pub.items())))
    com_c = [k for k, n in normas_por_k.items() if n.get("caminho_compilado")]
    com_c_anc = [k for k in com_c if any("c" in v for p in ("corpo", "adct")
                                         for v in anc_full.get(k, {}).get(p, {}).values())]
    rel(f"normas com compilado: {len(com_c)}; com âncora no compilado: {len(com_c_anc)}")
    rel("")
    rel("## Contagens")
    for m, c in sorted(rel.cont.items()):
        rel(f"- {m}: {c}")
    rel("")
    rel("## Exemplos por motivo")
    for m in sorted(rel.exemplos):
        rel(f"### {m}")
        for e in rel.exemplos[m]:
            rel(f"  {e}")
    if todas_p:
        diagnostico_preambulo(todas_p, rel)
    rel("")
    rel("## Gates")
    rel("todos verdes" if not erros else "\n".join(f"FALHOU {e}" for e in erros))
    return erros, saida, arquivos


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="montar_base.py", description="Estágio A: monta base/ a partir dos insumos privados.")
    ap.add_argument("--snapshot", help="sqlite do índice (ou PD_SNAPSHOT)")
    ap.add_argument("--ancoras", help="âncoras escolhidas, JSONL (ou PD_ANCORAS)")
    ap.add_argument("--ancoras-todas", help="todas as âncoras, JSONL; opcional, só diagnóstico (ou PD_ANCORAS_TODAS)")
    ap.add_argument("--compilados", help="mapa de compilados, JSONL (ou PD_COMPILADOS)")
    ap.add_argument("--cache-html", help="pasta com www.planalto.gov.br/ccivil_03/ (ou PD_CACHE_HTML); obrigatório")
    ap.add_argument("--lista-privada", help="lista privada, JSONL; opcional (ou PD_LISTA_PRIVADA)")
    ap.add_argument("--caminhos", help="substituições curadas (padrão: fontes/caminhos.json)")
    ap.add_argument("--saida", help="pasta de saída (padrão: base/)")
    ap.add_argument("--relatorio", help="arquivo do relatório, fora do repo (padrão: stdout)")
    ap.add_argument("--verificar", action="store_true", help="compara com a saída existente, sem gravar")
    ap.add_argument("--so-fixture", help="chaves separadas por vírgula, ou @arquivo")
    args = ap.parse_args(argv)

    if args.relatorio and _dentro_do_repo(pathlib.Path(args.relatorio)):
        print("erro: --relatorio não pode ficar dentro do repositório", file=sys.stderr)
        return 2
    rel = Relatorio()
    try:
        return _main(args, rel)
    except ErroUso as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2


def _main(args, rel: Relatorio) -> int:
    try:
        erros, saida, arquivos = montar(args, rel)
    except (ErroBuild, nor.ErroAno, esquemas.ErroEsquema) as e:
        rel(f"ERRO: {e}")
        erros, saida, arquivos = [str(e)], None, None

    codigo = 0
    if erros:
        codigo = 1
    elif args.verificar:
        ex = existentes(saida)
        dif = sorted(set(ex) ^ set(arquivos))
        dif += sorted(r for r in arquivos if r in ex and ex[r].read_bytes() != arquivos[r])
        if dif:
            rel(f"--verificar: {len(dif)} arquivos diferem, ex.: {dif[:10]}")
            codigo = 1
        else:
            rel(f"--verificar: {len(arquivos)} arquivos idênticos")
    else:
        gravar(saida, arquivos)
        rel(f"gravado: {len(arquivos)} arquivos")

    texto = rel.texto()
    if args.relatorio:
        p = pathlib.Path(args.relatorio)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(texto, encoding="utf-8", newline="\n")
        resumo = [l for l in rel.linhas if l.startswith(("ERRO", "FALHOU", "--verificar", "gravado", "todos verdes"))]
        print("\n".join(resumo[:40]))
    else:
        sys.stdout.write(texto)
    return codigo


if __name__ == "__main__":
    sys.exit(main())
