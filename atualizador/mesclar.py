"""Mescla dos registros lidos dos índices na base pública (``base/normas.jsonl``).

Identidade = ``caminho_indice.lower()``. Nunca apaga; norma existente nunca tem
``ano``, ``k``, ``caminho``, ``caminho_compilado`` nem ``desde`` recalculados.
"""
from __future__ import annotations

Norma = dict
Diff = dict

MAX_NOVAS = 500


def calcular(bruto: dict, base_url: str, ano_ref: int) -> dict:
    """Campos derivados de um registro bruto (§5.2–§5.5). Levanta ``normas.ErroAno``."""
    from pd import normas
    tipo = bruto["tipo"]
    tsig = normas.tsig_de(tipo)
    rotulo = normas.normalizar_espacos(bruto.get("rotulo"))
    url_abs = base_url + bruto["url"]
    indice_abs = base_url + bruto["indice"]
    ano = normas.ano_de(rotulo, bruto.get("data_txt"), url_abs, indice_abs, ano_ref)
    sufixo = bruto.get("sufixo") or ""
    letra = normas.letra_de(tipo, sufixo, rotulo, url_abs)
    reed = normas.reed_de(tipo, sufixo)
    numero = int(bruto["numero"])
    return {
        "ano": ano,
        "data": normas.data_iso(bruto.get("data_txt"), rotulo, ano),
        "ementa": normas.limpar_ementa(bruto.get("ementa"), tipo),
        "k": normas.chave(tsig, numero, letra, ano),
        "letra": letra,
        "numero": numero,
        "reed": reed,
        "rotulo": rotulo,
        "tipo": tipo,
        "tsig": tsig,
    }


def mesclar(base: list[Norma], brutos: list[dict], hoje: str, ano_ref: int,
            *, base_url: str, indices_lidos: set[str] | None = None) -> tuple[list[Norma], Diff]:
    """Mescla ``brutos`` em ``base``. Devolve (nova lista em ordem canônica, diff).

    ``indices_lidos``: buckets lidos nesta execução (para "sumiu do índice");
    por padrão, os ``indice`` dos próprios brutos.
    """
    from pd import normas
    from pd.ordem import ordem_chave

    diff: Diff = {"novas": [], "alteradas": [], "sumidas": [], "conflitos": [], "divergencias": []}
    saida = [dict(n) for n in base]
    por_caminho = {n["caminho_indice"].lower(): n for n in saida if n.get("caminho_indice")}
    chaves = {n["k"]: n for n in saida}
    vistos: set[str] = set()

    for b in brutos:
        ident = b["url"].lower()
        if ident in vistos:
            continue
        vistos.add(ident)
        if b.get("divergencia"):
            diff["divergencias"].append({"url": b["url"], "rotulo": b.get("rotulo", ""), "nota": b["divergencia"]})
        atual = por_caminho.get(ident)
        if atual is not None:
            rotulo = normas.normalizar_espacos(b.get("rotulo"))
            ementa = normas.limpar_ementa(b.get("ementa"), atual["tipo"])
            for campo, novo in (("rotulo", rotulo), ("ementa", ementa)):
                if atual.get(campo, "") != novo:
                    diff["alteradas"].append({"k": atual["k"], "campo": campo, "antes": atual.get(campo, ""), "depois": novo})
                    atual[campo] = novo
            continue
        try:
            c = calcular(b, base_url, ano_ref)
        except Exception as e:  # ErroAno ou tipo desconhecido
            diff["conflitos"].append({"url": b["url"], "rotulo": b.get("rotulo", ""), "motivo": f"{type(e).__name__}: {e}"})
            continue
        if c["k"] in chaves:
            diff["conflitos"].append({"url": b["url"], "rotulo": c["rotulo"], "k": c["k"],
                                      "motivo": "chave já existe com outro caminho: " + chaves[c["k"]]["caminho_indice"]})
            continue
        n = dict(c)
        n.update({
            "caminho": b["url"],
            "caminho_compilado": "",
            "caminho_indice": b["url"],
            "desde": hoje,
            "indice": b["indice"],
        })
        saida.append(n)
        chaves[n["k"]] = n
        por_caminho[ident] = n
        diff["novas"].append(n["k"])

    lidos = {i.lower() for i in (indices_lidos if indices_lidos is not None else {b["indice"] for b in brutos})}
    for n in base:
        if (n.get("indice") or "").lower() in lidos and n["caminho_indice"].lower() not in vistos:
            diff["sumidas"].append(n["k"])

    saida.sort(key=lambda n: ordem_chave(n["k"]))
    diff["novas"].sort(key=ordem_chave)
    diff["sumidas"].sort(key=ordem_chave)
    return saida, diff


def verificar(normas_lista: list[Norma], diff: Diff, aceitar_muitas: bool = False) -> list[str]:
    """Gates antes de gravar. Devolve a lista de erros (vazia = ok)."""
    from pd import normas
    erros = []
    vistas: set[str] = set()
    for n in normas_lista:
        if n["k"] in vistas:
            erros.append(f"chave duplicada: {n['k']}")
        vistas.add(n["k"])
    tocadas = set(diff["novas"]) | {a["k"] for a in diff["alteradas"]}
    for n in normas_lista:
        if n["k"] in tocadas:
            for p in normas.problemas_ementa(n.get("ementa") or "", n["tipo"], n["k"]):
                erros.append(f"ementa de {n['k']}: {p}")
    if len(diff["novas"]) > MAX_NOVAS and not aceitar_muitas:
        erros.append(f"{len(diff['novas'])} normas novas (> {MAX_NOVAS}); use --aceitar-muitas se for legítimo")
    return erros


def conferir(base: list[Norma], brutos: list[dict], base_url: str, ano_ref: int,
             indices_lidos: set[str] | None = None) -> dict:
    """Teste de aceitação offline (§13.5): recalcula (caminho, numero, letra, ano) e a ementa
    de cada registro lido e compara com a base, nos buckets lidos."""
    from pd import normas
    lidos = {i.lower() for i in (indices_lidos if indices_lidos is not None else {b["indice"] for b in brutos})}
    alvo = {n["caminho_indice"].lower(): n for n in base if (n.get("indice") or "").lower() in lidos}
    calculados: dict[str, tuple] = {}
    ementas: dict[str, str] = {}
    falhas = []
    for b in brutos:
        ident = b["url"].lower()
        if ident in calculados:
            continue
        try:
            c = calcular(b, base_url, ano_ref)
        except Exception as e:
            falhas.append({"url": b["url"], "motivo": f"{type(e).__name__}: {e}"})
            continue
        calculados[ident] = (ident, c["numero"], c["letra"], c["ano"])
        ementas[ident] = normas.limpar_ementa(b.get("ementa"), b["tipo"])
    na_base = {(k, n["numero"], n["letra"], n["ano"]) for k, n in alvo.items()}
    lidos_set = set(calculados.values())
    iguais = len(na_base & lidos_set)
    total = max(len(na_base | lidos_set), 1)
    so_base = sorted(na_base - lidos_set)
    so_lidos = sorted(lidos_set - na_base)
    comuns = [k for k in alvo if k in ementas]
    ementa_dif = [k for k in comuns if alvo[k].get("ementa", "") != ementas[k]]
    return {
        "base": len(na_base), "lidos": len(lidos_set), "iguais": iguais,
        "igualdade": iguais / total,
        "ementa_diferente": len(ementa_dif),
        "ementa_diferente_frac": len(ementa_dif) / max(len(comuns), 1),
        "so_na_base": [list(t) for t in so_base[:200]],
        "so_nos_indices": [list(t) for t in so_lidos[:200]],
        "ementas_diferentes": [{"k": alvo[k]["k"], "base": alvo[k].get("ementa", ""), "lida": ementas[k]}
                               for k in ementa_dif[:200]],
        "falhas": falhas[:200],
    }
