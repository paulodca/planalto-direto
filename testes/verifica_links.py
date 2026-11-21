"""(b) Confere uma amostra de links contra as páginas do Planalto guardadas localmente (SPEC §14.4). Sem rede.

Uso: python -P -B testes/verifica_links.py --cache-html DIR --amostra ARQ [--json ARQ]
(DIR também pode vir de PD_CACHE_HTML; é a pasta que contém www.planalto.gov.br/ccivil_03/.)

Para cada link: a página existe no cache (caminho em minúsculas); o fragmento (decodificado em UTF-8) existe
como name= ou id=; o primeiro texto não vazio depois da âncora não está riscado. Implementação própria,
independente da do pacote pd (de propósito, para um erro numa não mascarar a outra).
Saída: 0 PASS, 1 FAIL, 77 SKIP, 2 erro de uso.
"""
import sys, pathlib
RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import argparse
import html.parser
import json
import os
import re
import urllib.parse

CHARSET_RE = re.compile(rb'charset\s*=\s*["\']?([\w-]+)', re.I)
SEM_PILHA = {"br", "img", "meta", "link", "hr", "input", "wbr", "area", "base", "col", "embed", "source", "track", "param"}
RISCANTES = {"s", "strike", "del"}


def decodificar(raw: bytes) -> str:
    m = CHARSET_RE.search(raw[:4096])
    nome = m.group(1).decode("ascii", "replace").lower() if m else ""
    if nome in ("utf-8", "utf8"):
        return raw.decode("utf-8", "replace")
    return raw.decode("cp1252", "replace")


class Leitor(html.parser.HTMLParser):
    """Coleta os nomes (name/id) e, para cada âncora, se o primeiro texto depois dela está riscado."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nomes = set()
        self.pilha = []
        self.esperando = []          # âncoras <a> aguardando o primeiro texto
        self.esperando_id = []       # ids de outros elementos (alternativa)
        self.riscado_a = {}          # nome -> bool | None (sem texto depois)
        self.riscado_id = {}

    def handle_starttag(self, tag, attrs):
        d = {k.lower(): (v or "") for k, v in attrs}
        for chave in ("name", "id"):
            if d.get(chave):
                self.nomes.add(d[chave])
        if tag == "a":
            for chave in ("name", "id"):
                v = d.get(chave)
                if v and v not in self.riscado_a:
                    self.riscado_a[v] = None
                    self.esperando.append(v)
        elif d.get("id") and d["id"] not in self.riscado_id:
            self.riscado_id[d["id"]] = None
            self.esperando_id.append(d["id"])
        if tag in SEM_PILHA or (tag == "a" and "href" not in d):
            return
        estilo = d.get("style", "").lower().replace(" ", "")
        self.pilha.append((tag, tag in RISCANTES or "line-through" in estilo))

    def handle_startendtag(self, tag, attrs):
        d = {k.lower(): (v or "") for k, v in attrs}
        for chave in ("name", "id"):
            if d.get(chave):
                self.nomes.add(d[chave])
        if tag == "a":
            for chave in ("name", "id"):
                v = d.get(chave)
                if v and v not in self.riscado_a:
                    self.riscado_a[v] = None
                    self.esperando.append(v)

    def handle_endtag(self, tag):
        for i in range(len(self.pilha) - 1, -1, -1):
            if self.pilha[i][0] == tag:
                del self.pilha[i:]
                return

    def handle_data(self, data):
        if not data.strip() or not (self.esperando or self.esperando_id):
            return
        r = any(x for _, x in self.pilha)
        for v in self.esperando:
            self.riscado_a[v] = r
        for v in self.esperando_id:
            self.riscado_id[v] = r
        self.esperando, self.esperando_id = [], []

    def riscado(self, nome):
        if nome in self.riscado_a:
            return self.riscado_a[nome]
        return self.riscado_id.get(nome)


def caminho_relativo(url: str):
    partes = urllib.parse.urlsplit(url)
    marca = "/ccivil_03/"
    if marca not in partes.path:
        return None, None
    rel = partes.path.split(marca, 1)[1]
    return urllib.parse.unquote(rel), partes.fragment


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="(b) links da amostra contra as páginas do Planalto guardadas localmente")
    ap.add_argument("--cache-html", default=os.environ.get("PD_CACHE_HTML", ""), help="pasta com www.planalto.gov.br/ccivil_03/")
    ap.add_argument("--amostra", default=str(RAIZ / "testes" / ".saida" / "amostra.json"))
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)

    def fim(estado, detalhe, itens):
        if a.json:
            p = pathlib.Path(a.json)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"id": "verifica_links", "estado": estado, "detalhe": detalhe, "itens": itens},
                                    ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(("SKIP: " if estado == "SKIP" else estado + ": ") + detalhe)
        return {"PASS": 0, "FAIL": 1, "SKIP": 77}[estado]

    base = pathlib.Path(a.cache_html) / "www.planalto.gov.br" / "ccivil_03" if a.cache_html else None
    if not base or not base.is_dir():
        return fim("SKIP", "páginas do Planalto guardadas localmente não fornecidas (--cache-html ou PD_CACHE_HTML)", [])
    arq = pathlib.Path(a.amostra)
    if not arq.is_file():
        return fim("SKIP", "amostra ausente (gere com node testes/links_amostra.mjs)", [])
    amostra = json.loads(arq.read_text(encoding="utf-8"))
    paginas = {}
    itens = []
    for item in amostra:
        if item.get("na"):
            itens.append({"consulta": item.get("consulta"), "estado": "N/A", "motivo": item["na"]})
            continue
        url = item["url"]
        rel, frag = caminho_relativo(url)
        res = {"consulta": item.get("consulta"), "url": url, "estado": "PASS", "motivo": ""}
        if rel is None:
            res.update(estado="FAIL", motivo="URL fora de ccivil_03")
            itens.append(res)
            continue
        alvo = base.joinpath(*rel.lower().split("/"))
        if not alvo.is_file():
            res.update(estado="FAIL", motivo="página fora do cache")
            itens.append(res)
            continue
        if alvo not in paginas:
            leitor = Leitor()
            leitor.feed(decodificar(alvo.read_bytes()))
            leitor.close()
            paginas[alvo] = leitor
        leitor = paginas[alvo]
        if frag:
            nome = urllib.parse.unquote(frag, encoding="utf-8")
            if nome not in leitor.nomes:
                res.update(estado="FAIL", motivo=f"âncora ausente: {nome}")
            elif leitor.riscado(nome):
                res.update(estado="FAIL", motivo="texto seguinte riscado")
        itens.append(res)

    largura = max([len(str(i.get("consulta"))) for i in itens] + [8])
    print(f"{'consulta'.ljust(largura)} | estado | detalhe")
    for i in itens:
        print(f"{str(i.get('consulta')).ljust(largura)} | {i['estado'].ljust(6)} | {i.get('motivo') or i.get('url', '')}")
    falhas = [i for i in itens if i["estado"] == "FAIL"]
    total = len([i for i in itens if i["estado"] != "N/A"])
    if not total:
        return fim("FAIL", "amostra vazia", itens)
    return fim("FAIL" if falhas else "PASS", f"{total - len(falhas)}/{total} links ok, {len(itens) - total} N/A", itens)


if __name__ == "__main__":
    sys.exit(main())
