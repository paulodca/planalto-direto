"""Atualizador público do índice: lê os quadros do Planalto e mescla em base/.

Uso: python -P atualizador/atualizar.py --estado .estado [--modo ano-corrente|todos] ...
Veja atualizador/LEIAME.md. Códigos de saída: 0 ok; 2 parada (nada gravado);
3 lock ocupado; 4 erro de dados (gate).
"""
import sys
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import argparse
import datetime
import hashlib
import json
import os
import time

OK, PARADA, LOCK, ERRO_DADOS = 0, 2, 3, 4
LOCK_VELHO_S = 3 * 3600
LISTA_BRANCA = RAIZ / "atualizador" / "lista_branca.json"
IGUALDADE_MIN = 0.999
EMENTA_DIF_MAX = 0.005


# ------------------------------------------------------------------ argumentos
def _argumentos(argv):
    p = argparse.ArgumentParser(
        prog="atualizar.py",
        description="Lê os índices do Planalto (lista branca) e mescla normas novas/alteradas em base/.")
    p.add_argument("--estado", default=str(RAIZ / ".estado"),
                   help="pasta de estado (cache/, coleta.lock, relatorios/, log.jsonl); padrão: .estado/ na raiz")
    p.add_argument("--modo", choices=("ano-corrente", "todos"), default="ano-corrente")
    p.add_argument("--indice", nargs="+", metavar="CAMINHO_REL", help="lê só estes índices da lista branca")
    p.add_argument("--offline-cache-raiz", metavar="DIR",
                   help="lê os índices de uma cópia em disco (DIR/www.planalto.gov.br/ccivil_03/...), sem rede")
    p.add_argument("--cache-horas", type=float, default=20.0)
    p.add_argument("--max-req", type=int, default=80)
    p.add_argument("--simular", action="store_true", help="lê e mescla em memória; grava só o relatório")
    p.add_argument("--sem-regerar", action="store_true", help="não roda o estágio B depois de gravar")
    p.add_argument("--aceitar-novos-indices", action="store_true",
                   help="lê os buckets novos achados nas páginas de navegação e os acrescenta à lista branca")
    p.add_argument("--aceitar-muitas", action="store_true", help="aceita mais de 500 normas novas numa execução")
    p.add_argument("--remover-lock-velho", action="store_true", help="remove um lock com mais de 3 h")
    p.add_argument("--base", default=str(RAIZ / "base"), help="pasta da base pública (padrão: base/)")
    p.add_argument("--hoje", metavar="AAAA-MM-DD", help="data da execução (padrão: hoje)")
    p.add_argument("--lista-branca", default=str(LISTA_BRANCA), help=argparse.SUPPRESS)
    return p.parse_args(argv)


# ------------------------------------------------------------------------ lock
class LockOcupado(Exception):
    pass


def adquirir_lock(estado: pathlib.Path, remover_velho: bool, agora=time.time) -> pathlib.Path:
    estado.mkdir(parents=True, exist_ok=True)
    arq = estado / "coleta.lock"
    for _ in range(2):
        try:
            fd = os.open(arq, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                idade = agora() - arq.stat().st_mtime
            except OSError:
                continue
            if idade < LOCK_VELHO_S:
                raise LockOcupado("outra execução em andamento (coleta.lock)") from None
            if not remover_velho:
                raise LockOcupado("lock velho; use --remover-lock-velho") from None
            arq.unlink()
            continue
        quando = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        os.write(fd, f"{os.getpid()} {quando}\n".encode("utf-8"))
        os.close(fd)
        return arq
    raise LockOcupado("não foi possível criar coleta.lock")


# -------------------------------------------------------------------- arquivos
def _escrever_texto(destino: pathlib.Path, texto: str) -> None:
    """UTF-8 sem BOM, fim de linha LF, escrita atômica (pd.jsonio)."""
    from pd import jsonio
    jsonio.escrever_texto(destino, texto)


def ler_json(arq: pathlib.Path, padrao):
    from pd import jsonio
    return jsonio.ler_json(arq) if arq.is_file() else padrao


def texto_lista_branca(lb) -> str:
    linhas = ["  " + json.dumps(e, ensure_ascii=False, sort_keys=True) for e in lb["indices"]]
    return '{\n "indices": [\n' + ",\n".join(linhas) + '\n ],\n "versao": ' + str(lb.get("versao", 1)) + "\n}\n"


# -------------------------------------------------------------------- seleção
def selecionar(lb_ind, modo: str, ano: int, indice_args, base_url: str):
    from pd import normas
    nav = [e for e in lb_ind if e["papel"] == "navegacao"]
    buckets = [e for e in lb_ind if e["papel"] == "bucket"]
    if indice_args:
        pedidos = {i.lower() for i in indice_args}
        sel = [e for e in nav + buckets if e["caminho"].lower() in pedidos]
        faltam = pedidos - {e["caminho"].lower() for e in sel}
        return sel, sorted(faltam)
    if modo == "todos":
        return nav + buckets, []

    def cobre(e):
        f = normas.faixa_indice(base_url + e["caminho"], ano)
        return f is not None and f[0] <= ano <= f[1]

    sel = [e for e in buckets if cobre(e)]
    navs = []
    if not any(e["tipo"] == "lei" for e in sel):
        navs.append("leis/_lei-ordinaria.htm")
    if not any(e["tipo"] == "medida provisoria" for e in sel):
        navs.append("mpv/principal.htm")
    sel = [e for e in nav if e["caminho"].lower() in navs] + sel
    return sel, []


def _tipo_do_novo(caminho: str) -> str:
    return "medida provisoria" if caminho.lower().startswith("mpv/") else "lei"


# ------------------------------------------------------------------- relatório
def _md(rel) -> str:
    L = [f"# Atualização do índice — {rel['hoje']}", ""]
    L.append(f"- Modo: {rel['modo']}{' (simulação)' if rel['simular'] else ''}{' (offline)' if rel['offline'] else ''}")
    L.append(f"- Requisições: {rel['requisicoes']} · falhas: {rel['falhas']} · índices lidos: {len(rel['indices_lidos'])}")
    L.append(f"- Resultado: {rel['resultado']} (código {rel['codigo']})")
    if rel.get("parada"):
        L.append(f"- **Parada** em {rel['parada']['url']}: {rel['parada']['motivo']}. Nada foi gravado.")
    for erro in rel.get("erros", []):
        L.append(f"- Erro: {erro}")
    for aviso in rel.get("avisos", []):
        L.append(f"- Aviso: {aviso}")
    d = rel.get("diff") or {}

    def secao(titulo, itens, fmt):
        L.extend(["", f"## {titulo} ({len(itens)})", ""])
        if itens:
            L.extend(fmt(i) for i in itens)
        else:
            L.append("Nenhum item.")

    secao("Normas novas", rel.get("novas_detalhe", []),
          lambda n: f"- [{n['nome']}]({n['link']}) — {n['ementa'] or '(sem ementa)'}")
    secao("Alteradas", d.get("alteradas", []), lambda a: f"- {a['k']} · {a['campo']}: “{a['antes']}” → “{a['depois']}”")
    secao("Sumiram do índice (não apagadas)", d.get("sumidas", []), lambda k: f"- {k}")
    secao("Conflitos (não entraram)", d.get("conflitos", []),
          lambda c: f"- {c.get('url')} ({c.get('rotulo', '')}): {c.get('motivo')}")
    secao("Divergências rótulo × arquivo (MP)", d.get("divergencias", []),
          lambda c: f"- {c['url']} ({c['rotulo']}): {c['nota']}")
    secao("Índices que sumiram (404)", rel.get("indices_404", []), lambda c: f"- {c}")
    secao("Sem leitura anterior crua (regra dos 70% não aplicada)", rel.get("sem_leitura_anterior", []),
          lambda c: f"- {c}")
    secao("Buckets novos achados", rel.get("novos_indices", []),
          lambda c: f"- {c}{' (lido e acrescentado)' if rel.get('novos_aceitos') else ' (não lido; use --aceitar-novos-indices)'}")
    conf = rel.get("conferencia")
    if conf:
        L.extend(["", "## Conferência com a base (aceitação offline)", "",
                  f"- (caminho, número, letra, ano): {conf['iguais']} iguais; base {conf['base']}, lidos {conf['lidos']}; "
                  f"igualdade {conf['igualdade']:.4%}",
                  f"- Ementa diferente depois da limpeza: {conf['ementa_diferente']} ({conf['ementa_diferente_frac']:.3%})"])
        for t in conf["so_na_base"][:50]:
            L.append(f"  - só na base: {t}")
        for t in conf["so_nos_indices"][:50]:
            L.append(f"  - só nos índices: {t}")
    return "\n".join(L) + "\n"


def gravar_relatorio(estado: pathlib.Path, rel) -> pathlib.Path:
    pasta = estado / "relatorios"
    nome = f"atualizacao-{rel['hoje']}"
    from pd import jsonio
    _escrever_texto(pasta / f"{nome}.json", jsonio.dumps(rel))
    _escrever_texto(pasta / f"{nome}.md", _md(rel))
    return pasta / f"{nome}.md"


def _resumo(rel) -> str:
    d = rel.get("diff") or {}
    partes = [f"atualizador: {rel['resultado']} (código {rel['codigo']})",
              f"requisições {rel['requisicoes']}, falhas {rel['falhas']}, índices lidos {len(rel['indices_lidos'])}"]
    if d:
        partes.append(f"novas {len(d['novas'])}, alteradas {len(d['alteradas'])}, sumidas {len(d['sumidas'])}, "
                      f"conflitos {len(d['conflitos'])}")
    if rel.get("novos_indices"):
        partes.append(f"buckets novos: {', '.join(rel['novos_indices'])}")
    if rel.get("parada"):
        partes.append(f"parada em {rel['parada']['url']}: {rel['parada']['motivo']}")
    for e in rel.get("erros", []):
        partes.append(f"erro: {e}")
    for a in rel.get("avisos", []):
        partes.append(f"aviso: {a}")
    if rel.get("conferencia"):
        c = rel["conferencia"]
        partes.append(f"conferência: igualdade {c['igualdade']:.4%}, ementa diferente {c['ementa_diferente_frac']:.3%}")
    return "\n".join(partes)


# ----------------------------------------------------------------------- main
def main(argv=None) -> int:
    args = _argumentos(argv)
    estado = pathlib.Path(args.estado).resolve()
    base_dir = pathlib.Path(args.base).resolve()
    try:
        lock = adquirir_lock(estado, args.remover_lock_velho)
    except LockOcupado as e:
        print(f"atualizador: {e}", file=sys.stderr)
        return LOCK
    try:
        return _executar(args, estado, base_dir)
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def _executar(args, estado: pathlib.Path, base_dir: pathlib.Path) -> int:
    from pd.config import ler_config
    from pd import esquemas, jsonio
    from pd import normas as pdn
    from atualizador import indices, mesclar, rede

    base_url = ler_config(str(RAIZ / "docs" / "config.js"))["PLANALTO_BASE"]
    hoje = args.hoje or datetime.date.today().isoformat()
    datetime.date.fromisoformat(hoje)
    ano = int(hoje[:4])
    rel = {"hoje": hoje, "modo": args.modo, "simular": bool(args.simular), "offline": bool(args.offline_cache_raiz),
           "requisicoes": 0, "falhas": 0, "indices_lidos": [], "indices_404": [], "novos_indices": [],
           "novos_aceitos": bool(args.aceitar_novos_indices), "erros": [], "avisos": [], "sem_leitura_anterior": [],
           "diff": None, "novas_detalhe": [], "resultado": "", "codigo": OK}

    def fim(codigo, resultado):
        rel["codigo"], rel["resultado"] = codigo, resultado
        if rel["sem_leitura_anterior"]:
            rel["avisos"].append(f"regra dos 70% não aplicada a {len(rel['sem_leitura_anterior'])} índice(s): "
                                 "sem leitura anterior crua em estado/cache (TSPD e </html> conferidos)")
        gravar_relatorio(estado, rel)
        print(_resumo(rel))
        return codigo

    arq_lb = pathlib.Path(args.lista_branca)
    lb = ler_json(arq_lb, {"versao": 1, "indices": []})
    sel, faltam = selecionar(lb["indices"], args.modo, ano, args.indice, base_url)
    if faltam:
        rel["erros"].append("fora da lista branca: " + ", ".join(faltam))
        return fim(PARADA, "erro de uso")

    indices_json = ler_json(base_dir / "indices.json", {"indices": {}, "versao": 1})
    info_por_minusc = {k.lower(): (k, v) for k, v in indices_json.get("indices", {}).items()}
    # A regra dos 70% (§13.4) compara com o corpo CRU da leitura anterior do próprio atualizador
    # (estado/cache). O "bytes" de base/indices.json não serve: a base inicial veio de HTML reformatado.

    cli = rede.Cliente(base_url, estado, args.cache_horas, args.max_req,
                       pathlib.Path(args.offline_cache_raiz) if args.offline_cache_raiz else None)
    conhecidos = {e["caminho"] for e in lb["indices"]}
    brutos, lidos, novos_info, novas_entradas = [], [], {}, []
    fila = list(sel)
    try:
        while fila:
            e = fila.pop(0)
            caminho = e["caminho"]
            anterior = cli.bytes_anterior_cru(caminho)
            if anterior is None:
                rel["sem_leitura_anterior"].append(caminho)
            resp = cli.obter(caminho, anterior)
            if resp is None:
                rel["indices_404"].append(caminho)
                continue
            html_txt = indices.decodificar(resp.raw)
            if e["papel"] == "navegacao":
                for novo in indices.novos_buckets(html_txt, caminho, conhecidos, base_url):
                    conhecidos.add(novo)
                    rel["novos_indices"].append(novo)
                    if args.aceitar_novos_indices:
                        ent = {"caminho": novo, "papel": "bucket", "tipo": _tipo_do_novo(novo)}
                        novas_entradas.append(ent)
                        fila.append(ent)
                continue
            brutos.extend(indices.registros_do_indice(html_txt, caminho, e["tipo"], base_url))
            lidos.append(caminho)
            novos_info[caminho] = {"bytes": len(resp.raw), "quando": hoje,
                                   "sha256": hashlib.sha256(resp.raw).hexdigest()}
    except rede.Parada as p:
        rel["requisicoes"], rel["falhas"] = cli.requisicoes, cli.falhas
        rel["parada"] = {"url": p.url, "motivo": p.motivo}
        rel["indices_lidos"] = lidos
        return fim(PARADA, "parada")
    rel["requisicoes"], rel["falhas"], rel["indices_lidos"] = cli.requisicoes, cli.falhas, lidos

    arq_normas = base_dir / "normas.jsonl"
    base = jsonio.ler_jsonl(arq_normas) if arq_normas.is_file() else []
    novas_normas, diff = mesclar.mesclar(base, brutos, hoje, ano, base_url=base_url, indices_lidos=set(lidos))
    rel["diff"] = diff
    por_k = {n["k"]: n for n in novas_normas}
    for k in diff["novas"]:
        n = por_k[k]
        rel["novas_detalhe"].append({"k": k, "nome": pdn.nome_norma(n["tsig"], n["numero"], n["letra"], n["reed"], n["ano"]),
                                     "ementa": n["ementa"], "link": base_url + n["caminho"]})
    erros = mesclar.verificar(novas_normas, diff, args.aceitar_muitas)
    erros += esquemas.validar_normas(novas_normas)

    if args.offline_cache_raiz and args.simular:
        conf = mesclar.conferir(base, brutos, base_url, ano, set(lidos))
        rel["conferencia"] = conf
        if args.modo == "todos" and not args.indice:
            if conf["igualdade"] < IGUALDADE_MIN:
                erros.append(f"conferência: igualdade {conf['igualdade']:.4%} < 99,9%")
            if conf["ementa_diferente_frac"] > EMENTA_DIF_MAX:
                erros.append(f"conferência: ementa diferente em {conf['ementa_diferente_frac']:.3%} > 0,5%")

    if erros:
        rel["erros"].extend(erros)
        return fim(ERRO_DADOS, "gate falhou; nada gravado")
    if args.simular:
        return fim(OK, "simulação; nada gravado")

    gerar_site = None
    if not args.sem_regerar:
        try:
            from build import gerar_site
        except ImportError as e:
            rel["erros"].append(f"estágio B indisponível ({e}); use --sem-regerar")
            return fim(ERRO_DADOS, "nada gravado")

    # ---- gravação (só daqui em diante algo muda em base/)
    for caminho, info in novos_info.items():
        chave = info_por_minusc.get(caminho.lower(), (caminho, None))[0]
        indices_json.setdefault("indices", {})[chave] = info
    indices_json.setdefault("versao", 1)
    erros = esquemas.validar_indices(indices_json)
    if erros:
        rel["erros"].extend(erros)
        return fim(ERRO_DADOS, "gate falhou; nada gravado")
    jsonio.escrever_jsonl(arq_normas, novas_normas)
    jsonio.escrever_json(base_dir / "indices.json", indices_json)
    if novas_entradas:
        lb["indices"].extend(novas_entradas)
        _escrever_texto(arq_lb, texto_lista_branca(lb))
    if gerar_site is not None:
        cod = gerar_site.main(["--base", str(base_dir)])
        if cod != 0:
            rel["erros"].append(f"estágio B saiu com código {cod}")
            return fim(ERRO_DADOS, "base gravada; estágio B falhou")
    return fim(OK, "gravado")


if __name__ == "__main__":
    sys.exit(main())
