"""Validadores dos formatos do §6 (base pública, fontes curadas, dados publicados).

Convenção: toda função ``validar_*`` devolve uma lista de mensagens de erro
(lista vazia = válido). ``exigir(erros, contexto)`` levanta ``ErroEsquema``
se a lista não estiver vazia. Sem dependência externa.
"""
from __future__ import annotations

import re

from pd import ancoras as _anc
from pd import normas as _nor
from pd import ordem as _ord

__all__ = [
    "ErroEsquema", "exigir", "CAMPOS_PROIBIDOS", "campos_proibidos",
    "validar_norma", "validar_normas", "validar_ancoras", "validar_desempate", "validar_indices",
    "validar_caminhos", "validar_apelidos", "validar_areas", "validar_avisos",
    "validar_manifesto", "validar_shard", "validar_ancoras_indice", "validar_apelidos_publicos",
    "validar_avisos_publicos", "validar_areas_publicas",
]

CAMPOS_PROIBIDOS = ("ordem", "origem", "rank", "score", "posicao", "mencoes", "citacoes", "inicio",
                    "riscado", "so_riscada", "alternativas", "revogada", "ordem_doc", "cache", "url_pedida")

DATA_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HEX12_RE = re.compile(r"^[0-9a-f]{12}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
REVOGAD_RE = re.compile(r"(?i)revogad")
CAMPOS_NORMA = frozenset(("ano", "caminho", "caminho_compilado", "caminho_indice", "data", "desde", "ementa",
                          "indice", "k", "letra", "numero", "reed", "rotulo", "tipo", "tsig"))
CAMPOS_REGISTRO = frozenset(("a", "c", "d", "e", "k", "l", "n", "r", "u"))
CAMPOS_AVISO = frozenset(("id", "alvo", "estado", "texto", "fonte", "prova", "conferido_em", "ir_para"))
CAMPOS_AVISO_PUB = frozenset(("id", "alvo", "estado", "texto", "fonte", "ir_para"))


class ErroEsquema(ValueError):
    pass


def exigir(erros: list[str], contexto: str = "") -> None:
    if erros:
        cab = f"{contexto}: " if contexto else ""
        mostra = erros[:20]
        resto = f" (+{len(erros) - 20})" if len(erros) > 20 else ""
        raise ErroEsquema(cab + "; ".join(mostra) + resto)


def campos_proibidos(obj, caminho: str = "$") -> list[str]:
    """Caminhos de todo campo de objeto com nome proibido (§6), em qualquer profundidade."""
    achados = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in CAMPOS_PROIBIDOS:
                achados.append(f"{caminho}.{k}")
            achados.extend(campos_proibidos(v, f"{caminho}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            achados.extend(campos_proibidos(v, f"{caminho}[{i}]"))
    return achados


def _data_ok(s) -> bool:
    if not isinstance(s, str) or not DATA_ISO_RE.match(s):
        return False
    import datetime
    try:
        datetime.date.fromisoformat(s)
        return True
    except ValueError:
        return False


def caminho_relativo_ok(s, vazio_ok: bool = False) -> bool:
    if s == "" and vazio_ok:
        return True
    if not isinstance(s, str) or not s:
        return False
    if s.startswith("/") or "\\" in s or ":" in s or "#" in s or "?" in s or " " in s:
        return False
    if ".." in s.split("/"):
        return False
    return bool(re.search(r"(?i)\.html?$", s))


def _str(d, campo, erros, pre, vazio_ok=True):
    v = d.get(campo)
    if not isinstance(v, str):
        erros.append(f"{pre}{campo} precisa ser texto")
        return None
    if not vazio_ok and not v:
        erros.append(f"{pre}{campo} vazio")
    return v


def _sem_c1(s: str) -> bool:
    return not re.search("[\u0080-\u009f]", s)


# ------------------------------------------------------------------ base/normas.jsonl
def validar_norma(d) -> list[str]:
    if not isinstance(d, dict):
        return ["norma precisa ser objeto"]
    k = d.get("k", "?")
    pre = f"[{k}] "
    erros = []
    faltam = CAMPOS_NORMA - set(d)
    extras = set(d) - CAMPOS_NORMA
    if faltam:
        erros.append(f"{pre}faltam campos {sorted(faltam)}")
    if extras:
        erros.append(f"{pre}campos extras {sorted(extras)}")
    if faltam:
        return erros
    for c in ("k", "tipo", "tsig", "letra", "reed", "data", "rotulo", "ementa", "caminho",
              "caminho_compilado", "caminho_indice", "indice", "desde"):
        _str(d, c, erros, pre)
    for c in ("numero", "ano"):
        if not isinstance(d[c], int) or isinstance(d[c], bool) or d[c] < 0:
            erros.append(f"{pre}{c} precisa ser inteiro >= 0")
    if erros:
        return erros
    tsig = d["tsig"]
    if tsig not in _ord.ORDEM_TIPOS:
        erros.append(f"{pre}tsig inválido {tsig!r}")
    elif _nor.TIPOS.get(d["tipo"]) != tsig:
        erros.append(f"{pre}tipo {d['tipo']!r} não corresponde a tsig {tsig!r}")
    if d["letra"] and not re.fullmatch(r"[a-z]", d["letra"]):
        erros.append(f"{pre}letra inválida")
    if d["reed"] and (tsig != "mp" or not d["reed"].isdigit()):
        erros.append(f"{pre}reed inválido")
    if not (1800 <= d["ano"] <= 2100):
        erros.append(f"{pre}ano fora da faixa")
    if tsig in _ord.ORDEM_TIPOS and not erros:
        if k != _nor.chave(tsig, d["numero"], d["letra"], d["ano"]):
            erros.append(f"{pre}k não corresponde a (tsig, numero, letra, ano)")
    if d["data"] and not _data_ok(d["data"]):
        erros.append(f"{pre}data inválida")
    if d["data"] and _data_ok(d["data"]) and int(d["data"][:4]) != d["ano"]:
        erros.append(f"{pre}data com ano diferente de ano")
    if not _data_ok(d["desde"]):
        erros.append(f"{pre}desde inválido")
    if not caminho_relativo_ok(d["caminho"]):
        erros.append(f"{pre}caminho inválido")
    if not caminho_relativo_ok(d["caminho_compilado"], vazio_ok=True):
        erros.append(f"{pre}caminho_compilado inválido")
    if not caminho_relativo_ok(d["caminho_indice"]):
        erros.append(f"{pre}caminho_indice inválido")
    if tsig == "cf":
        if d["indice"] != "":
            erros.append(f"{pre}indice da CF precisa ser vazio")
    elif not caminho_relativo_ok(d["indice"]):
        erros.append(f"{pre}indice inválido")
    for c in ("rotulo", "ementa"):
        if not _sem_c1(d[c]) or "�" in d[c]:
            erros.append(f"{pre}{c} com caractere C1/U+FFFD")
        if d[c] != d[c].strip() or re.search(r"\s{2,}|[\n\r\t ]", d[c]):
            erros.append(f"{pre}{c} com espaços não normalizados")
    for p in _nor.problemas_ementa(d["ementa"], d["tipo"], k):
        erros.append(f"{pre}ementa: {p}")
    for c in ("rotulo", "ementa", "caminho", "caminho_compilado", "caminho_indice", "indice"):
        if ":~:" in d[c]:
            erros.append(f"{pre}{c} contém ':~:'")
    return erros


def validar_normas(normas: list) -> list[str]:
    """Cada norma + chaves únicas + identidade (caminho_indice) única + ordem canônica."""
    erros = []
    vistos: set = set()
    caminhos: set = set()
    anterior = None
    for d in normas:
        e = validar_norma(d)
        erros.extend(e)
        if e:
            continue
        k = d["k"]
        if k in vistos:
            erros.append(f"[{k}] chave duplicada")
        vistos.add(k)
        ci = d["caminho_indice"].lower()
        if ci in caminhos:
            erros.append(f"[{k}] caminho_indice duplicado")
        caminhos.add(ci)
        o = _ord.ordem_chave(k)
        if anterior is not None and o <= anterior:
            erros.append(f"[{k}] fora da ordem canônica de chave")
        anterior = o
    return erros


# ------------------------------------------------------------------ base/ancoras/<k>.json
def validar_ancoras(d, norma: dict | None = None) -> list[str]:
    """Âncoras de uma norma. Com ``norma``, confere ``h``/``c`` contra caminho/caminho_compilado."""
    if not isinstance(d, dict):
        return ["âncoras precisam ser objeto"]
    k = d.get("k", "?")
    pre = f"[ancoras {k}] "
    erros = []
    extras = set(d) - {"k", "h", "c", "corpo", "adct"}
    if extras:
        erros.append(f"{pre}campos extras {sorted(extras)}")
    for c in ("k", "h", "c"):
        if not isinstance(d.get(c), str):
            erros.append(f"{pre}{c} precisa ser texto")
    if erros:
        return erros
    if not _ord.chave_valida(k):
        erros.append(f"{pre}k inválida")
    if not caminho_relativo_ok(d["h"]):
        erros.append(f"{pre}h inválido")
    if not caminho_relativo_ok(d["c"], vazio_ok=True):
        erros.append(f"{pre}c inválido")
    if "corpo" not in d:
        erros.append(f"{pre}falta corpo")
    if "adct" in d and k != _ord.CHAVE_CF:
        erros.append(f"{pre}adct só na CF")
    total = 0
    for parte in ("corpo", "adct"):
        if parte not in d:
            continue
        mapa = d[parte]
        if not isinstance(mapa, dict):
            erros.append(f"{pre}{parte} precisa ser objeto")
            continue
        for disp, vers in mapa.items():
            if not _anc.disp_canonico_valido(disp):
                erros.append(f"{pre}{parte}: dispositivo não canônico {disp!r}")
            if not isinstance(vers, dict) or not vers or set(vers) - {"c", "h"}:
                erros.append(f"{pre}{parte}/{disp}: versões precisam ser {{c?, h?}} não vazio")
                continue
            for v, nome in vers.items():
                total += 1
                if not isinstance(nome, str) or not _anc.ancora_valida(nome):
                    erros.append(f"{pre}{parte}/{disp}/{v}: âncora inválida {nome!r}")
                if v == "c" and not d["c"]:
                    erros.append(f"{pre}{parte}/{disp}: versão c sem página compilada")
    if total == 0:
        erros.append(f"{pre}nenhuma âncora")
    if norma is not None:
        if norma.get("k") != k:
            erros.append(f"{pre}k difere da norma")
        if d["h"] != norma.get("caminho"):
            erros.append(f"{pre}h difere do caminho da norma")
        if d["c"] != norma.get("caminho_compilado"):
            erros.append(f"{pre}c difere do caminho_compilado da norma")
    return erros


# ------------------------------------------------------------------ base/desempate.json
def validar_desempate(d, chaves: set | None = None) -> list[str]:
    erros = []
    if not isinstance(d, dict) or set(d) != {"grupos", "versao"}:
        return ["desempate: precisa ser {grupos, versao}"]
    if d["versao"] != 1:
        erros.append("desempate: versao != 1")
    g = d["grupos"]
    if not isinstance(g, dict):
        return erros + ["desempate: grupos precisa ser objeto"]
    for grupo, k in g.items():
        m = _ord.GRUPO_RE.match(grupo)
        if not m:
            erros.append(f"desempate: grupo inválido {grupo!r}")
            continue
        if not isinstance(k, str) or not _ord.chave_valida(k):
            erros.append(f"desempate: {grupo}: chave inválida")
            continue
        t, n, l, _a = _ord.partes_chave(k)
        if int(m.group(2)) != n or m.group(3) != l or (m.group(1) != "num" and m.group(1) != t):
            erros.append(f"desempate: {grupo}: {k} não pertence ao grupo")
        if chaves is not None and k not in chaves:
            erros.append(f"desempate: {grupo}: {k} não existe na base")
    return erros


# ------------------------------------------------------------------ base/indices.json
def validar_indices(d) -> list[str]:
    erros = []
    if not isinstance(d, dict) or set(d) != {"indices", "versao"}:
        return ["indices: precisa ser {indices, versao}"]
    if d["versao"] != 1:
        erros.append("indices: versao != 1")
    for url, r in (d["indices"] or {}).items():
        if not caminho_relativo_ok(url):
            erros.append(f"indices: caminho inválido {url!r}")
        if not isinstance(r, dict) or set(r) != {"bytes", "quando", "sha256"}:
            erros.append(f"indices: {url}: campos precisam ser bytes, quando, sha256")
            continue
        if not isinstance(r["bytes"], int) or r["bytes"] < 0:
            erros.append(f"indices: {url}: bytes inválido")
        if not _data_ok(r["quando"]):
            erros.append(f"indices: {url}: quando inválido")
        if not isinstance(r["sha256"], str) or not HEX64_RE.match(r["sha256"]):
            erros.append(f"indices: {url}: sha256 inválido")
    return erros


# ------------------------------------------------------------------ fontes/caminhos.json
def validar_caminhos(d, chaves: set | None = None) -> list[str]:
    erros = []
    if not isinstance(d, dict) or set(d) != {"substituicoes", "versao"}:
        return ["caminhos: precisa ser {substituicoes, versao}"]
    if d["versao"] != 1:
        erros.append("caminhos: versao != 1")
    vistos = set()
    for i, s in enumerate(d["substituicoes"]):
        pre = f"caminhos[{i}] "
        campos = {"k", "campo", "de", "para", "justificativa", "conferido_em"}
        if not isinstance(s, dict) or set(s) != campos:
            erros.append(pre + f"campos precisam ser {sorted(campos)}")
            continue
        if not _ord.chave_valida(s["k"]):
            erros.append(pre + "k inválida")
        elif chaves is not None and s["k"] not in chaves:
            erros.append(pre + f"{s['k']} não existe na base")
        if s["campo"] not in ("caminho", "caminho_compilado"):
            erros.append(pre + "campo precisa ser caminho ou caminho_compilado")
        if not caminho_relativo_ok(s["de"], vazio_ok=True):
            erros.append(pre + "de inválido")
        if not caminho_relativo_ok(s["para"], vazio_ok=(s["campo"] == "caminho_compilado")):
            erros.append(pre + "para inválido")
        if not isinstance(s["justificativa"], str) or not s["justificativa"].strip():
            erros.append(pre + "justificativa vazia")
        if not _data_ok(s["conferido_em"]):
            erros.append(pre + "conferido_em precisa ser data AAAA-MM-DD")
        chave_s = (s["k"], s["campo"])
        if chave_s in vistos:
            erros.append(pre + "substituição repetida")
        vistos.add(chave_s)
    return erros


# ------------------------------------------------------------------ fontes/apelidos.json
def _textos_revogad(obj, pre) -> list[str]:
    erros = []
    if isinstance(obj, str):
        if REVOGAD_RE.search(obj):
            erros.append(f"{pre}texto com 'revogad' (I4)")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            erros.extend(_textos_revogad(v, f"{pre}{k}."))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            erros.extend(_textos_revogad(v, f"{pre}{i}."))
    return erros


def _lista_str(v, vazio_ok=False) -> bool:
    return isinstance(v, list) and (vazio_ok or v) and all(isinstance(x, str) and x for x in v)


def _ordenado(seq, chave) -> bool:
    ks = [chave(x) for x in seq]
    return all(a <= b for a, b in zip(ks, ks[1:]))


def validar_apelidos(d, chaves: set | None = None, publico: bool = False) -> list[str]:
    erros = []
    campos = {"versao", "apelidos", "listas", "assuntos", "fora_escopo"} | ({"desempate"} if publico else set())
    if not isinstance(d, dict) or set(d) != campos:
        return [f"apelidos: campos precisam ser {sorted(campos)}"]
    if d["versao"] != 1:
        erros.append("apelidos: versao != 1")

    def alvo_ok(k, pre):
        if not isinstance(k, str) or not _ord.chave_valida(k):
            erros.append(f"{pre}alvo inválido {k!r}")
            return False
        if chaves is not None and k not in chaves:
            erros.append(f"{pre}alvo {k} não existe na base")
        return True

    aps = d["apelidos"]
    if not isinstance(aps, list):
        erros.append("apelidos: apelidos precisa ser lista")
        aps = []
    ok_ordem = True
    for i, a in enumerate(aps):
        pre = f"apelidos[{i}] "
        if not isinstance(a, dict) or set(a) != {"alvo", "sigla", "nome", "termos", "nota"}:
            erros.append(pre + "campos precisam ser alvo, sigla, nome, termos, nota")
            ok_ordem = False
            continue
        if not alvo_ok(a["alvo"], pre):
            ok_ordem = False
        for c in ("sigla", "nome"):
            if not isinstance(a[c], str) or not a[c]:
                erros.append(pre + f"{c} vazio")
        if not isinstance(a["nota"], str):
            erros.append(pre + "nota precisa ser texto")
        if not _lista_str(a["termos"]):
            erros.append(pre + "termos precisa ser lista de textos não vazia")
    if ok_ordem and not _ordenado(aps, lambda a: (_ord.ordem_chave(a["alvo"]), a["sigla"])):
        erros.append("apelidos: apelidos fora da ordem canônica do alvo")

    for nome_arr, campos_item in (("listas", {"alvos", "termos", "nota"}), ("assuntos", {"alvos", "termos"})):
        arr = d[nome_arr]
        if not isinstance(arr, list):
            erros.append(f"apelidos: {nome_arr} precisa ser lista")
            continue
        ok_ordem = True
        for i, it in enumerate(arr):
            pre = f"{nome_arr}[{i}] "
            if not isinstance(it, dict) or set(it) != campos_item:
                erros.append(pre + f"campos precisam ser {sorted(campos_item)}")
                ok_ordem = False
                continue
            if not _lista_str(it["alvos"]):
                erros.append(pre + "alvos precisa ser lista não vazia")
                ok_ordem = False
            else:
                for k in it["alvos"]:
                    if not alvo_ok(k, pre):
                        ok_ordem = False
            if not _lista_str(it["termos"]):
                erros.append(pre + "termos precisa ser lista de textos não vazia")
            if "nota" in campos_item and not isinstance(it["nota"], str):
                erros.append(pre + "nota precisa ser texto")
        if ok_ordem and not _ordenado(arr, lambda it: _ord.ordem_chave(it["alvos"][0])):
            erros.append(f"apelidos: {nome_arr} fora da ordem canônica do 1º alvo")

    fe = d["fora_escopo"]
    if not isinstance(fe, list):
        erros.append("apelidos: fora_escopo precisa ser lista")
    else:
        for i, it in enumerate(fe):
            pre = f"fora_escopo[{i}] "
            if not isinstance(it, dict) or set(it) != {"padrao", "mensagem"}:
                erros.append(pre + "campos precisam ser padrao, mensagem")
                continue
            try:
                re.compile(it["padrao"])
            except (re.error, TypeError):
                erros.append(pre + "padrao não é regex válida")
            if not isinstance(it["mensagem"], str) or not it["mensagem"]:
                erros.append(pre + "mensagem vazia")
        if all(isinstance(x, dict) and isinstance(x.get("padrao"), str) for x in fe) and \
                not _ordenado(fe, lambda x: x["padrao"]):
            erros.append("apelidos: fora_escopo fora da ordem de padrao")
    if publico:
        erros.extend(validar_desempate({"grupos": d["desempate"], "versao": 1}, chaves))
    erros.extend(_textos_revogad({k: v for k, v in d.items() if k != "desempate"}, "apelidos."))
    return erros


def validar_apelidos_publicos(d, chaves: set | None = None) -> list[str]:
    """``docs/dados/apelidos.json``: o mesmo formato, mais ``desempate``."""
    return validar_apelidos(d, chaves, publico=True)


# ------------------------------------------------------------------ fontes/areas.json
def validar_areas(d, chaves: set | None = None) -> list[str]:
    erros = []
    if not isinstance(d, dict) or set(d) != {"versao", "areas"}:
        return ["areas: precisa ser {versao, areas}"]
    if d["versao"] != 1:
        erros.append("areas: versao != 1")
    ids = set()
    for i, a in enumerate(d["areas"] if isinstance(d["areas"], list) else []):
        pre = f"areas[{i}] "
        if not isinstance(a, dict) or set(a) != {"id", "nome", "itens"}:
            erros.append(pre + "campos precisam ser id, nome, itens")
            continue
        if not isinstance(a["id"], str) or not re.fullmatch(r"[a-z0-9-]+", a["id"]):
            erros.append(pre + "id inválido")
        elif a["id"] in ids:
            erros.append(pre + "id repetido")
        ids.add(a.get("id"))
        if not isinstance(a["nome"], str) or not a["nome"]:
            erros.append(pre + "nome vazio")
        if not isinstance(a["itens"], list) or not a["itens"]:
            erros.append(pre + "itens vazio")
            continue
        for j, it in enumerate(a["itens"]):
            p2 = f"{pre}itens[{j}] "
            if not isinstance(it, dict) or set(it) != {"k", "rotulo", "dica"}:
                erros.append(p2 + "campos precisam ser k, rotulo, dica")
                continue
            if not isinstance(it["k"], str) or not _ord.chave_valida(it["k"]):
                erros.append(p2 + "k inválida")
            elif chaves is not None and it["k"] not in chaves:
                erros.append(p2 + f"{it['k']} não existe na base")
            if not isinstance(it["rotulo"], str) or not it["rotulo"]:
                erros.append(p2 + "rotulo vazio")
            if not isinstance(it["dica"], str):
                erros.append(p2 + "dica precisa ser texto")
    if not isinstance(d["areas"], list):
        erros.append("areas: areas precisa ser lista")
    erros.extend(_textos_revogad(d, "areas."))
    return erros


def validar_areas_publicas(d, chaves: set | None = None) -> list[str]:
    return validar_areas(d, chaves)


# ------------------------------------------------------------------ fontes/avisos.json
def _alvo_aviso(alvo, pre, chaves, erros):
    if not isinstance(alvo, dict) or not {"k"} <= set(alvo) <= {"k", "parte", "disp"}:
        erros.append(pre + "alvo precisa ser {k, parte?, disp?}")
        return
    if not isinstance(alvo["k"], str) or not _ord.chave_valida(alvo["k"]):
        erros.append(pre + "alvo.k inválida")
    elif chaves is not None and alvo["k"] not in chaves:
        erros.append(pre + f"alvo.k {alvo['k']} não existe na base")
    parte = alvo.get("parte", "corpo")
    if parte not in ("corpo", "adct"):
        erros.append(pre + "alvo.parte precisa ser corpo ou adct")
    disp = alvo.get("disp", "")
    if disp and not _anc.disp_canonico_valido(disp):
        erros.append(pre + f"alvo.disp não canônico {disp!r}")


def _aviso_base(a, pre, chaves, erros):
    if not isinstance(a["id"], str) or not re.fullmatch(r"[a-z0-9-]+", a["id"]):
        erros.append(pre + "id inválido")
    _alvo_aviso(a["alvo"], pre, chaves, erros)
    if a["estado"] != "atencao":
        erros.append(pre + "estado precisa ser 'atencao'")
    for c in ("texto", "fonte"):
        if not isinstance(a[c], str) or not a[c].strip():
            erros.append(pre + f"{c} vazio")
        elif REVOGAD_RE.search(a[c]):
            erros.append(pre + f"{c} com 'revogad' (I4)")
    if not isinstance(a["ir_para"], str) or (a["ir_para"] and not _anc.disp_canonico_valido(a["ir_para"])):
        erros.append(pre + "ir_para precisa ser vazio ou dispositivo canônico")


def validar_avisos(d, chaves: set | None = None) -> list[str]:
    erros = []
    if not isinstance(d, dict) or set(d) != {"versao", "avisos"}:
        return ["avisos: precisa ser {versao, avisos}"]
    if d["versao"] != 1:
        erros.append("avisos: versao != 1")
    if not isinstance(d["avisos"], list):
        return erros + ["avisos: avisos precisa ser lista"]
    ids = set()
    for i, a in enumerate(d["avisos"]):
        pre = f"avisos[{i}] "
        if not isinstance(a, dict) or set(a) != CAMPOS_AVISO:
            erros.append(pre + f"campos precisam ser {sorted(CAMPOS_AVISO)}")
            continue
        if a["id"] in ids:
            erros.append(pre + "id repetido")
        ids.add(a["id"])
        _aviso_base(a, pre, chaves, erros)
        p = a["prova"]
        if not isinstance(p, dict) or set(p) != {"arquivo", "ancora", "contem"}:
            erros.append(pre + "prova precisa ser {arquivo, ancora, contem}")
        else:
            if not caminho_relativo_ok(p["arquivo"]) or p["arquivo"] != p["arquivo"].lower():
                erros.append(pre + "prova.arquivo precisa ser caminho relativo em minúsculas")
            if not isinstance(p["ancora"], str) or not p["ancora"]:
                erros.append(pre + "prova.ancora vazia")
            try:
                re.compile(p["contem"])
            except (re.error, TypeError):
                erros.append(pre + "prova.contem não é regex válida")
        if a["conferido_em"] != "" and not _data_ok(a["conferido_em"]):
            erros.append(pre + "conferido_em precisa ser vazio ou AAAA-MM-DD")
    return erros


def validar_avisos_publicos(lista_ou_obj, chaves: set | None = None) -> list[str]:
    """``docs/dados/avisos.json``: aceita a lista de avisos ou ``{versao, avisos}``; só os campos públicos, em ordem de id."""
    erros = []
    if isinstance(lista_ou_obj, dict):
        if set(lista_ou_obj) != {"versao", "avisos"}:
            return ["avisos públicos: precisa ser {versao, avisos}"]
        avisos = lista_ou_obj["avisos"]
    else:
        avisos = lista_ou_obj
    if not isinstance(avisos, list):
        return ["avisos públicos: avisos precisa ser lista"]
    for i, a in enumerate(avisos):
        pre = f"avisos[{i}] "
        if not isinstance(a, dict) or set(a) != CAMPOS_AVISO_PUB:
            erros.append(pre + f"campos precisam ser {sorted(CAMPOS_AVISO_PUB)}")
            continue
        _aviso_base(a, pre, chaves, erros)
    ids = [a.get("id") for a in avisos if isinstance(a, dict)]
    if all(isinstance(x, str) for x in ids) and ids != sorted(ids):
        erros.append("avisos públicos: fora da ordem de id")
    if len(set(ids)) != len(ids):
        erros.append("avisos públicos: id repetido")
    return erros


# ------------------------------------------------------------------ docs/dados
def validar_manifesto(d) -> list[str]:
    erros = []
    campos = {"base_sha", "gerado", "normas", "shards", "versao"}
    if not isinstance(d, dict) or set(d) != campos:
        return [f"manifesto: campos precisam ser {sorted(campos)}"]
    if d["versao"] != 1:
        erros.append("manifesto: versao != 1")
    if not isinstance(d["base_sha"], str) or not HEX12_RE.match(d["base_sha"]):
        erros.append("manifesto: base_sha precisa ter 12 hex")
    if not _data_ok(d["gerado"]):
        erros.append("manifesto: gerado precisa ser AAAA-MM-DD")
    if not isinstance(d["normas"], int) or d["normas"] < 0:
        erros.append("manifesto: normas inválido")
    total = 0
    if not isinstance(d["shards"], dict):
        return erros + ["manifesto: shards precisa ser objeto"]
    for nome, s in d["shards"].items():
        if not re.fullmatch(r"n-(lei|lc|dl|mp|ec|ld|ecr|cf)-\d{2}", nome):
            erros.append(f"manifesto: nome de shard inválido {nome!r}")
        if not isinstance(s, dict) or set(s) != {"qtd", "sha"}:
            erros.append(f"manifesto: {nome}: campos precisam ser qtd, sha")
            continue
        if not isinstance(s["qtd"], int) or s["qtd"] <= 0:
            erros.append(f"manifesto: {nome}: qtd inválida")
        else:
            total += s["qtd"]
        if not isinstance(s["sha"], str) or not HEX12_RE.match(s["sha"]):
            erros.append(f"manifesto: {nome}: sha precisa ter 12 hex")
    if isinstance(d["normas"], int) and total != d["normas"]:
        erros.append("manifesto: soma de qtd difere de normas")
    return erros


def validar_registro(r) -> list[str]:
    if not isinstance(r, dict):
        return ["registro precisa ser objeto"]
    k = r.get("k", "?")
    pre = f"[reg {k}] "
    erros = []
    obrig = {"a", "k", "l", "n", "u"}
    if not obrig <= set(r):
        erros.append(pre + f"faltam {sorted(obrig - set(r))}")
        return erros
    if set(r) - CAMPOS_REGISTRO:
        erros.append(pre + f"campos extras {sorted(set(r) - CAMPOS_REGISTRO)}")
    if not _ord.chave_valida(k):
        erros.append(pre + "k inválida")
        return erros
    t, n, l, a = _ord.partes_chave(k)
    if r["n"] != n or r["l"] != l or r["a"] != a:
        erros.append(pre + "n/l/a não correspondem à chave")
    if not caminho_relativo_ok(r["u"]):
        erros.append(pre + "u inválido")
    for c in ("c", "d", "e", "r"):
        if c in r and (not isinstance(r[c], str) or r[c] == ""):
            erros.append(pre + f"{c} vazio precisa ser omitido")
    if "c" in r and not caminho_relativo_ok(r["c"]):
        erros.append(pre + "c inválido")
    if "d" in r and not _data_ok(r["d"]):
        erros.append(pre + "d inválido")
    return erros


def validar_shard(lista, nome: str | None = None) -> list[str]:
    """``n-<tsig>-<NN>.json``: array em ordem canônica; com ``nome``, confere tipo e milhar."""
    if not isinstance(lista, list):
        return ["shard precisa ser lista"]
    erros = []
    anterior = None
    m = re.fullmatch(r"n-(\w+)-(\d{2})", nome) if nome else None
    for r in lista:
        e = validar_registro(r)
        erros.extend(e)
        if e:
            continue
        o = _ord.ordem_chave(r["k"])
        if anterior is not None and o <= anterior:
            erros.append(f"[reg {r['k']}] fora da ordem canônica")
        anterior = o
        if m:
            t, n, _l, _a = _ord.partes_chave(r["k"])
            nn = 0 if t == "cf" else n // 1000
            if t != m.group(1) or nn != int(m.group(2)):
                erros.append(f"[reg {r['k']}] não pertence ao shard {nome}")
    return erros


def validar_ancoras_indice(d) -> list[str]:
    if not isinstance(d, dict) or set(d) != {"normas", "versao"}:
        return ["ancoras.json: precisa ser {normas, versao}"]
    erros = []
    if d["versao"] != 1:
        erros.append("ancoras.json: versao != 1")
    ks = d["normas"]
    if not isinstance(ks, list) or not all(isinstance(k, str) and _ord.chave_valida(k) for k in ks):
        return erros + ["ancoras.json: normas precisa ser lista de chaves"]
    os_ = [_ord.ordem_chave(k) for k in ks]
    if any(a >= b for a, b in zip(os_, os_[1:])):
        erros.append("ancoras.json: fora da ordem canônica ou com repetição")
    return erros
