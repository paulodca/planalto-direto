"""(b2) Confere cada aviso de fontes/avisos.json contra as páginas do Planalto guardadas localmente (SPEC §14.8).

Uso:
  python -P -B testes/confere_avisos.py --cache-html DIR [--gravar --data AAAA-MM-DD] [--json ARQ]

DIR é a pasta que contém ``www.planalto.gov.br/ccivil_03/…`` (argumento ou variável PD_CACHE_HTML).
Nunca usa a data do relógio. Sem a pasta: SKIP (código 77).

Janela de busca: começa na 1ª ``<a>`` com ``name``/``id`` igual a ``prova.ancora`` e termina na
próxima âncora de artigo (``name`` casando ``^(?:adct|sadct)?art(\\d+)([a-z]?)\\.*$``) com
(número, letra) diferente do da âncora inicial, no fim do documento ou após 20.000 caracteres de texto.
Âncora com letra (``art193i``) é ambígua: pode ser o inciso I do art. 193 ou o art. 193-I. Ela só
fecha a janela se o 1º texto não vazio depois dela começa com "Art" (refino do §14.8, conservador).
O (número, letra) da âncora inicial sai do prefixo do nome (``art8§1`` -> (8, ''), ``art791a`` ->
(791, 'a')); se o nome não começa como âncora de artigo, a janela termina na 1ª âncora de artigo.

Códigos de saída: 0 PASS, 1 FAIL (aviso com ``conferido_em`` preenchido sem prova, ou esquema inválido),
2 erro de uso, 77 SKIP.
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

from pd.cache_html import decodificar, caminho_no_cache

ID_CHECAGEM = "b2"
ART_ANCORA_RE = re.compile(r"^(?:adct|sadct)?art(\d+)([a-z]?)\.*$")
ART_PREFIXO_RE = re.compile(r"^(?:adct|sadct)?art(\d+)([a-z]?)")
DATA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CHAVE_RE = re.compile(r"^(?:(?:lei|lc|dl|mp|ec|ld|ecr)-\d+[a-z]?-\d{4}|cf-1988)$")
LIMITE_TEXTO = 20000
CAMPOS_AVISO = {"id", "alvo", "estado", "texto", "fonte", "prova", "conferido_em", "ir_para"}


def _disp_valido(s: str) -> bool:
    try:
        from pd.ancoras import disp_canonico_valido
    except ImportError:  # pragma: no cover - P1 ainda não entregue
        return bool(re.match(r"^\d+(?:-[A-Z])?(?:\|[^|]+)*$", s))
    return disp_canonico_valido(s)


def validar_aviso(a: dict) -> list[str]:
    """Esquema do §6.2 (avisos). Lista vazia = ok."""
    erros = []
    if not isinstance(a, dict):
        return ["aviso não é objeto"]
    faltam = CAMPOS_AVISO - set(a)
    if faltam:
        erros.append("faltam campos: " + ", ".join(sorted(faltam)))
    extras = set(a) - CAMPOS_AVISO
    if extras:
        erros.append("campos desconhecidos: " + ", ".join(sorted(extras)))
    if not a.get("id") or not isinstance(a.get("id"), str):
        erros.append("id vazio")
    alvo = a.get("alvo") or {}
    if not isinstance(alvo, dict) or not CHAVE_RE.match(str(alvo.get("k", ""))):
        erros.append("alvo.k inválido")
    else:
        if alvo.get("parte", "corpo") not in ("corpo", "adct"):
            erros.append("alvo.parte inválida")
        d = alvo.get("disp", "")
        if d and not _disp_valido(d):
            erros.append("alvo.disp não é dispositivo canônico")
    if a.get("estado") != "atencao":
        erros.append("estado precisa ser 'atencao'")
    for campo in ("texto", "fonte"):
        v = a.get(campo)
        if not isinstance(v, str) or not v.strip():
            erros.append(f"{campo} vazio")
        elif re.search("(?i)" + "revo" + "gad", v):
            erros.append(f"{campo} contém palavra proibida (I4)")
    p = a.get("prova") or {}
    if not isinstance(p, dict) or not all(isinstance(p.get(c), str) and p.get(c) for c in ("arquivo", "ancora", "contem")):
        erros.append("prova incompleta")
    else:
        if p["arquivo"] != p["arquivo"].lower() or p["arquivo"].startswith("/") or "\\" in p["arquivo"]:
            erros.append("prova.arquivo precisa ser relativo e em minúsculas")
        try:
            re.compile(p["contem"])
        except re.error as e:
            erros.append(f"prova.contem não compila ({e})")
    ce = a.get("conferido_em", "")
    if not isinstance(ce, str) or (ce and not DATA_RE.match(ce)):
        erros.append("conferido_em precisa ser vazio ou AAAA-MM-DD")
    ip = a.get("ir_para", "")
    if not isinstance(ip, str) or (ip and not _disp_valido(ip)):
        erros.append("ir_para não é dispositivo canônico")
    return erros


class _Janela(html.parser.HTMLParser):
    def __init__(self, ancora: str):
        super().__init__(convert_charrefs=True)
        self.ancora = ancora
        m = ART_PREFIXO_RE.match(ancora)
        self.inicio = (int(m.group(1)), m.group(2)) if m else None
        self.aberta = False
        self.fechada = False
        self.achou = False
        self.partes: list[str] = []
        self.tam = 0
        self.confirmar = False

    def _tag(self, tag, attrs):
        if tag != "a" or self.fechada:
            return
        nomes = [v for k, v in attrs if k in ("name", "id") and v]
        if not self.aberta:
            if self.ancora in nomes:
                self.aberta = self.achou = True
            return
        for n in nomes:
            m = ART_ANCORA_RE.match(n)
            if m and (int(m.group(1)), m.group(2)) != self.inicio:
                if m.group(2):
                    # "art193i" pode ser o inciso I do art. 193: só fecha se o texto seguinte é "Art."
                    self.confirmar = True
                else:
                    self.fechada = True
                return

    handle_starttag = _tag
    handle_startendtag = _tag

    def handle_data(self, data):
        if not self.aberta or self.fechada:
            return
        s = data.strip()
        if s and self.confirmar:
            self.confirmar = False
            if re.match(r"Art(?:igo)?", s):
                self.fechada = True
                return
        if s:
            self.partes.append(s)
            self.tam += len(s) + 1
            if self.tam >= LIMITE_TEXTO:
                self.fechada = True

    def texto(self) -> str:
        return " ".join(self.partes)[:LIMITE_TEXTO]


def janela(html_txt: str, ancora: str) -> str | None:
    """Texto da janela da âncora; ``None`` se a âncora não existe na página."""
    j = _Janela(ancora)
    j.feed(html_txt)
    j.close()
    return j.texto() if j.achou else None


def conferir(aviso: dict, raiz_cache: pathlib.Path, _paginas: dict) -> tuple[bool, str]:
    p = aviso["prova"]
    arq = caminho_no_cache(raiz_cache, p["arquivo"])
    if not arq.is_file():
        return False, "prova fora do cache"
    if arq not in _paginas:
        _paginas[arq] = decodificar(arq.read_bytes())
    txt = janela(_paginas[arq], p["ancora"])
    if txt is None:
        return False, "âncora da prova não existe na página"
    if re.search(p["contem"], txt):
        return True, "prova encontrada"
    return False, "padrão não encontrado na janela"


def _gravar_json(destino: str | None, doc: dict) -> None:
    if not destino:
        return
    d = pathlib.Path(destino)
    d.parent.mkdir(parents=True, exist_ok=True)
    with open(d, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n")


def _gravar_avisos(caminho: pathlib.Path, doc: dict) -> None:
    texto = json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    try:
        from pd.jsonio import escrever_texto
    except ImportError:  # pragma: no cover
        caminho.write_bytes(texto.encode("utf-8"))
    else:
        escrever_texto(caminho, texto)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Confere os avisos curados contra as páginas do Planalto guardadas localmente.")
    ap.add_argument("--cache-html", help="pasta que contém www.planalto.gov.br/ccivil_03/ (ou PD_CACHE_HTML)")
    ap.add_argument("--avisos", default=str(RAIZ / "fontes" / "avisos.json"))
    ap.add_argument("--gravar", action="store_true", help="grava conferido_em nos aprovados (exige --data)")
    ap.add_argument("--data", help="AAAA-MM-DD usada em --gravar")
    ap.add_argument("--json", help="grava o resultado neste arquivo")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 2
    if a.gravar and not (a.data and DATA_RE.match(a.data)):
        print("erro: --gravar exige --data AAAA-MM-DD", file=sys.stderr)
        return 2
    cache = a.cache_html or os.environ.get("PD_CACHE_HTML", "")
    if not cache or not pathlib.Path(cache).is_dir():
        razao = "SKIP: páginas locais do Planalto não fornecidas (--cache-html ou PD_CACHE_HTML)"
        _gravar_json(a.json, {"id": ID_CHECAGEM, "estado": "SKIP", "detalhe": razao[6:], "itens": []})
        print(razao)
        return 77
    raiz_cache = pathlib.Path(cache)
    caminho = pathlib.Path(a.avisos)
    doc = json.loads(caminho.read_text(encoding="utf-8"))
    avisos = doc.get("avisos", [])
    itens, falhas, pendentes, paginas = [], [], [], {}
    ids = [x.get("id") for x in avisos if isinstance(x, dict)]
    if ids != sorted(ids) or len(set(ids)) != len(ids):
        falhas.append("avisos fora da ordem de id ou com id repetido")
    for av in avisos:
        erros = validar_aviso(av)
        if erros:
            falhas.append(f"{av.get('id')}: " + "; ".join(erros))
            itens.append({"id": av.get("id"), "resultado": "esquema", "motivo": "; ".join(erros)})
            continue
        ok, motivo = conferir(av, raiz_cache, paginas)
        alvo = av["alvo"]
        if a.gravar:
            if ok and not av["conferido_em"]:
                av["conferido_em"] = a.data
            elif not ok:
                av["conferido_em"] = ""
        if not ok and av["conferido_em"]:
            falhas.append(f"{av['id']}: publicado sem prova ({motivo})")
        if not av["conferido_em"]:
            pendentes.append((av["id"], alvo["k"] + (" / " + alvo["disp"] if alvo.get("disp") else ""), motivo))
        itens.append({"id": av["id"], "resultado": "aprovado" if ok else "reprovado", "motivo": motivo,
                      "conferido_em": av["conferido_em"]})
    if a.gravar and not falhas:
        _gravar_avisos(caminho, doc)
    print(f"{'aviso':<16} {'resultado':<10} motivo")
    for it in itens:
        print(f"{str(it['id']):<16} {it['resultado']:<10} {it['motivo']}")
    print(f"avisos pendentes de conferência: {len(pendentes)}")
    for pid, palvo, pmot in pendentes:
        print(f"  - {pid} ({palvo}): {pmot}")
    estado = "FAIL" if falhas else "PASS"
    detalhe = "; ".join(falhas) if falhas else f"{len(avisos) - len(pendentes)} publicados com prova; {len(pendentes)} pendentes"
    _gravar_json(a.json, {"id": ID_CHECAGEM, "estado": estado, "detalhe": detalhe, "itens": itens})
    print(f"{estado}: {detalhe}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
