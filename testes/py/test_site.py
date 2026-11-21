"""Estágio B (build/gerar_site.py): determinismo, sitemap, títulos, CSP, escape, subcaminho (I14), limpeza.

Usa uma base sintética mínima (dados inventados, sem texto de lei) e, se existir, a fixture
``testes/fixtures/base_min`` com as fontes filtradas para as chaves dela. As saídas ficam em
``testes/.saida/`` (ignorada pelo git) e são apagadas no fim.
"""
from __future__ import annotations

import sys
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import contextlib
import hashlib
import html.parser
import io
import json
import re
import shutil
import tempfile
import unittest

from build import gerar_site as G

RODAPE = "Ferramenta não oficial, sem vínculo com a Presidência da República. Sempre confira na fonte."
SAIDA_TESTES = RAIZ / "testes" / ".saida"
CONFIG = RAIZ / "docs" / "config.js"
BASE_MIN = RAIZ / "testes" / "fixtures" / "base_min"


def _jl(objs) -> str:
    return "".join(json.dumps(o, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for o in objs)


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1) + "\n"


def _norma(k, tipo, tsig, numero, ano, ementa, caminho, compilado="", letra="", reed="", data="", indice="leis/x/1.htm"):
    return {"ano": ano, "caminho": caminho, "caminho_compilado": compilado, "caminho_indice": caminho,
            "data": data, "desde": "2026-11-21", "ementa": ementa, "indice": indice, "k": k, "letra": letra,
            "numero": numero, "reed": reed, "rotulo": f"{numero}, de 1.1.{str(ano)[2:]}", "tipo": tipo, "tsig": tsig}


NORMAS = [
    _norma("lei-605-1949", "lei", "lei", 605, 1949, "Dispõe sobre o assunto A.", "leis/l0605.htm"),
    _norma("lei-8036-1990", "lei", "lei", 8036, 1990, 'Dispõe sobre "x" & <y> e dá outras providências.',
           "leis/l8036consol.htm", "leis/l8036compilada.htm", data="1990-05-11"),
    _norma("dl-605-1969", "decreto-lei", "dl", 605, 1969, "", "decreto-lei/del0605.htm"),
    _norma("dl-5452-1943", "decreto-lei", "dl", 5452, 1943, "Aprova a consolidação sintética.",
           "decreto-lei/del5452.htm", "decreto-lei/del5452compilado.htm", data="1943-05-01"),
    {"ano": 1988, "caminho": "constituicao/constituicao.htm", "caminho_compilado": "constituicao/constituicaocompilado.htm",
     "caminho_indice": "constituicao/constituicao.htm", "data": "1988-10-05", "desde": "2026-11-21",
     "ementa": "Constituição sintética de teste.", "indice": "", "k": "cf-1988", "letra": "", "numero": 1988,
     "reed": "", "rotulo": "Constituição Federal de 1988", "tipo": "constituicao", "tsig": "cf"},
]
ANCORAS = {"dl-5452-1943": {"c": "decreto-lei/del5452compilado.htm", "corpo": {"477": {"c": "art477..", "h": "art477.."}},
                            "h": "decreto-lei/del5452.htm", "k": "dl-5452-1943"}}
APELIDOS = {"versao": 1, "apelidos": [
    {"alvo": "lei-8036-1990", "sigla": "FGTS", "nome": "Lei do FGTS", "termos": ["fgts"], "nota": ""},
    {"alvo": "dl-5452-1943", "sigla": "CLT", "nome": "Consolidação sintética", "termos": ["clt"], "nota": "Nota de teste."},
], "listas": [], "assuntos": [], "fora_escopo": []}
AREAS = {"versao": 1, "areas": [{"id": "trabalho", "nome": "Trabalho", "itens": [
    {"k": "dl-5452-1943", "rotulo": "CLT", "dica": "Decreto-Lei 5.452/1943"},
    {"k": "cf-1988", "rotulo": "Constituição", "dica": ""}]}]}
AVISOS = {"versao": 1, "avisos": [
    {"id": "a-conferido", "alvo": {"k": "dl-5452-1943", "parte": "corpo", "disp": "477"}, "estado": "atencao",
     "texto": "Aviso de teste conferido.", "fonte": "Fonte de teste", "conferido_em": "2026-11-21", "ir_para": "",
     "prova": {"arquivo": "decreto-lei/del5452.htm", "ancora": "art477..", "contem": "x"}},
    {"id": "b-pendente", "alvo": {"k": "lei-605-1949", "parte": "corpo", "disp": ""}, "estado": "atencao",
     "texto": "Aviso de teste pendente.", "fonte": "Fonte de teste", "conferido_em": "", "ir_para": "",
     "prova": {"arquivo": "leis/l0605.htm", "ancora": "art1", "contem": "x"}},
]}


class _Links(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str, str]] = []
        self.scripts_inline = 0
        self.estilos = 0
        self._em_script = False

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        for at in ("href", "src", "action"):
            if at in d:
                self.links.append((tag, at, d[at] or ""))
        if tag == "script":
            self._em_script = "src" not in d
        if tag == "style" or "style" in d:
            self.estilos += 1

    def handle_data(self, data):
        if self._em_script and data.strip():
            self.scripts_inline += 1

    def handle_endtag(self, tag):
        if tag == "script":
            self._em_script = False


def _arvore(p: pathlib.Path) -> dict[str, str]:
    return {f.relative_to(p).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(p.rglob("*")) if f.is_file()}


def _rodar(argv) -> int:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return G.main(argv)


class BaseSintetica(unittest.TestCase):
    def setUp(self):
        SAIDA_TESTES.mkdir(parents=True, exist_ok=True)
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="site-", dir=SAIDA_TESTES))
        self.base = self.tmp / "base"
        self.fontes = self.tmp / "fontes"
        (self.base / "ancoras").mkdir(parents=True)
        self.fontes.mkdir()
        self.escrever_base(NORMAS)
        for k, d in ANCORAS.items():
            (self.base / "ancoras" / f"{k}.json").write_text(_j(d), encoding="utf-8", newline="\n")
        (self.base / "desempate.json").write_text(_j({"grupos": {}, "versao": 1}), encoding="utf-8", newline="\n")
        for nome, d in (("apelidos", APELIDOS), ("areas", AREAS), ("avisos", AVISOS)):
            (self.fontes / f"{nome}.json").write_text(_j(d), encoding="utf-8", newline="\n")
        self.saida = self.nova_saida("docs")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def escrever_base(self, normas):
        (self.base / "normas.jsonl").write_text(_jl(normas), encoding="utf-8", newline="\n")

    def nova_saida(self, nome) -> pathlib.Path:
        s = self.tmp / nome
        s.mkdir()
        shutil.copy(CONFIG, s / "config.js")
        (s / "favicon.svg").write_text("<svg/>\n", encoding="utf-8", newline="\n")
        (s / "assets").mkdir()
        (s / "assets" / "ui.js").write_text("// m\n", encoding="utf-8", newline="\n")
        return s

    def gerar(self, saida=None, *extra) -> int:
        saida = saida or self.saida
        return _rodar(["--base", str(self.base), "--fontes", str(self.fontes), "--saida", str(saida),
                       "--config", str(CONFIG), *extra])

    def html(self, rel) -> str:
        return (self.saida / rel).read_text(encoding="utf-8")


class TesteGeracao(BaseSintetica):
    def test_ajuda(self):
        self.assertEqual(_rodar(["--help"]), 0)
        self.assertEqual(_rodar(["--nao-existe"]), 2)

    def test_determinismo_e_verificar(self):
        self.assertEqual(self.gerar(), 0)
        outra = self.nova_saida("docs2")
        self.assertEqual(self.gerar(outra), 0)
        self.assertEqual(_arvore(self.saida), _arvore(outra))
        self.assertEqual(self.gerar(None, "--verificar"), 0)
        (self.saida / "lei" / "605-1949" / "index.html").write_text("x\n", encoding="utf-8", newline="\n")
        self.assertEqual(self.gerar(None, "--verificar"), 1)
        self.assertEqual(self.gerar(), 0)
        self.assertEqual(self.gerar(None, "--verificar"), 0)

    def test_arquivos_e_dados(self):
        self.assertEqual(self.gerar(), 0)
        for rel in ("index.html", "404.html", "opensearch.xml", "robots.txt", "sitemap.xml", ".gerado",
                    "dl/5452-1943/index.html", "cf/1988/index.html", "lei/8036-1990/index.html",
                    "dados/manifesto.json", "dados/n-cf-00.json", "dados/n-dl-05.json", "dados/n-lei-00.json",
                    "dados/n-lei-08.json", "dados/ancoras.json", "dados/a/dl-5452-1943.json",
                    "dados/apelidos.json", "dados/areas.json", "dados/avisos.json"):
            self.assertTrue((self.saida / rel).is_file(), rel)
        man = json.loads((self.saida / "dados" / "manifesto.json").read_text(encoding="utf-8"))
        self.assertEqual(man["normas"], len(NORMAS))
        self.assertEqual(man["gerado"], "2026-11-21")
        self.assertRegex(man["base_sha"], r"^[0-9a-f]{12}$")
        for nome, s in man["shards"].items():
            b = (self.saida / "dados" / f"{nome}.json").read_bytes()
            self.assertEqual(s["sha"], hashlib.sha256(b).hexdigest()[:12])
        reg = json.loads((self.saida / "dados" / "n-dl-00.json").read_text(encoding="utf-8"))
        self.assertEqual(reg, [{"a": 1969, "k": "dl-605-1969", "l": "", "n": 605, "u": "decreto-lei/del0605.htm"}])
        av = json.loads((self.saida / "dados" / "avisos.json").read_text(encoding="utf-8"))
        self.assertEqual([a["id"] for a in av["avisos"]], ["a-conferido"])
        self.assertEqual(set(av["avisos"][0]), {"id", "alvo", "estado", "texto", "fonte", "ir_para"})
        ap = json.loads((self.saida / "dados" / "apelidos.json").read_text(encoding="utf-8"))
        self.assertEqual(ap["desempate"], {})
        # [M] intocados
        self.assertEqual((self.saida / "favicon.svg").read_text(encoding="utf-8"), "<svg/>\n")
        self.assertEqual((self.saida / "config.js").read_bytes(), CONFIG.read_bytes())

    def test_titulo_ementa_escape(self):
        self.assertEqual(self.gerar(), 0)
        clt = self.html("dl/5452-1943/index.html")
        self.assertIn("<title>Decreto-Lei nº 5.452/1943 (CLT) — texto no Planalto</title>", clt)
        self.assertIn('href="https://www.planalto.gov.br/ccivil_03/decreto-lei/del5452compilado.htm"', clt)
        self.assertIn("Abrir no Planalto — texto compilado", clt)
        self.assertIn("Versão com histórico (trechos riscados são redação antiga)", clt)
        self.assertIn("Nota de teste.", clt)
        self.assertIn('data-consulta-base="dl 5452/1943"', clt)
        self.assertIn("../../lei/605-1949/", self.html("dl/605-1969/index.html"))
        fgts = self.html("lei/8036-1990/index.html")
        self.assertIn("<title>Lei nº 8.036/1990 (FGTS) — texto no Planalto</title>", fgts)
        self.assertIn("&quot;x&quot; &amp; &lt;y&gt;", fgts)
        self.assertNotIn("<y>", fgts)
        self.assertIn("<dd>11/05/1990</dd>", fgts)
        vazia = self.html("dl/605-1969/index.html")
        self.assertIn("Ementa não disponível no índice do Planalto.", vazia)
        self.assertNotIn("<dt>Data</dt>", vazia)
        self.assertIn("Não verificada pelo Planalto Direto — confira na fonte.", vazia)
        self.assertNotIn("Aviso de teste pendente.", self.html("lei/605-1949/index.html"))
        self.assertIn("Aviso de teste conferido.", clt)
        self.assertIn("<title>Constituição Federal de 1988 — texto no Planalto</title>", self.html("cf/1988/index.html"))

    def test_csp_rodape_marcas_e_formato(self):
        self.assertEqual(self.gerar(), 0)
        htmls = [p for p in self.saida.rglob("*.html")]
        self.assertGreaterEqual(len(htmls), 7)
        for p in htmls:
            t = p.read_text(encoding="utf-8")
            rel = p.relative_to(self.saida).as_posix()
            self.assertIn(f'<footer class="rodape">{RODAPE}</footer>', t, rel)
            self.assertIn(G.esc(G.CSP), t, rel)
            lk = _Links()
            lk.feed(t)
            self.assertEqual(lk.scripts_inline, 0, rel)
            self.assertEqual(lk.estilos, 0, rel)
            self.assertNotRegex(t, r"(?i)revogad", rel)
            self.assertNotRegex(t, r"(?i)fonts\.googleapis|fonts\.gstatic|gov\.br/ds|#4285F4|#1351B4", rel)
        for p in self.saida.rglob("*"):
            if p.is_file() and p.suffix in (".html", ".json", ".xml", ".txt", ""):
                b = p.read_bytes()
                self.assertNotIn(b"\r", b, p.name)
                self.assertFalse(b.startswith(b"\xef\xbb\xbf"), p.name)
                if p.suffix == ".html":
                    self.assertNotRegex(b.decode("utf-8"), r"[ \t]\n", p.name)
        home = self.html("index.html")
        self.assertNotIn("nucleo.js", home)
        self.assertNotIn("autofocus", home)
        self.assertNotIn("google-site-verification", home)

    def test_subcaminho_i14(self):
        self.assertEqual(self.gerar(), 0)
        site_path = "/planalto-direto/"
        externos = ("https://www.planalto.gov.br/ccivil_03/", "https://github.com/", "https://docs.google.com/")
        for rel in ("index.html", "dl/5452-1943/index.html", "cf/1988/index.html", "404.html"):
            lk = _Links()
            lk.feed(self.html(rel))
            for tag, at, v in lk.links:
                if tag == "link" and v.startswith("https://paulodca.github.io/planalto-direto/"):
                    continue  # canonical
                if v.startswith(externos):
                    continue
                if rel == "404.html":
                    self.assertTrue(v.startswith(site_path), f"{rel}: {tag}.{at}={v}")
                else:
                    self.assertFalse(v.startswith("/") or v.startswith("http"), f"{rel}: {tag}.{at}={v}")
        os_ = (self.saida / "opensearch.xml").read_text(encoding="utf-8")
        self.assertIn('template="https://paulodca.github.io/planalto-direto/?q={searchTerms}"', os_)
        self.assertIn("<Image type=\"image/svg+xml\">https://paulodca.github.io/planalto-direto/favicon.svg</Image>", os_)
        self.assertIn('<meta name="robots" content="noindex">', self.html("404.html"))
        self.assertIn('<link rel="canonical" href="https://paulodca.github.io/planalto-direto/dl/5452-1943/">',
                      self.html("dl/5452-1943/index.html"))
        rob = (self.saida / "robots.txt").read_text(encoding="utf-8")
        self.assertIn("Sitemap: https://paulodca.github.io/planalto-direto/sitemap.xml", rob)

    def test_sitemap(self):
        self.assertEqual(self.gerar(), 0)
        sm = (self.saida / "sitemap.xml").read_text(encoding="utf-8")
        locs = re.findall(r"<loc>([^<]+)</loc>", sm)
        self.assertEqual(len(locs), len(NORMAS) + 1)
        self.assertEqual(locs[0], "https://paulodca.github.io/planalto-direto/")
        self.assertNotIn("lastmod", sm)
        cfg = {"SITE_URL": "https://paulodca.github.io/planalto-direto/"}
        normas = sorted(NORMAS, key=lambda n: G_ordem(n["k"]))
        partes = G.gerar_sitemap(normas, cfg, limite_urls=2)
        self.assertEqual(sorted(partes), ["sitemap-0001.xml", "sitemap-0002.xml", "sitemap-0003.xml", "sitemap.xml"])
        self.assertIn("<sitemapindex", partes["sitemap.xml"].decode("utf-8"))
        total = sum(len(re.findall(rb"<url>", b)) for n, b in partes.items() if n != "sitemap.xml")
        self.assertEqual(total, len(NORMAS) + 1)

    def test_limpeza_segura(self):
        self.assertEqual(self.gerar(), 0)
        estranho = self.saida / "lei" / "manual.txt"
        estranho.write_text("m\n", encoding="utf-8", newline="\n")
        self.escrever_base([n for n in NORMAS if n["k"] != "lei-8036-1990"])
        ap = json.loads(json.dumps(APELIDOS))
        ap["apelidos"] = [a for a in ap["apelidos"] if a["alvo"] != "lei-8036-1990"]
        (self.fontes / "apelidos.json").write_text(_j(ap), encoding="utf-8", newline="\n")
        self.assertEqual(self.gerar(), 0)
        self.assertFalse((self.saida / "lei" / "8036-1990").exists())
        self.assertTrue(estranho.is_file())
        self.assertTrue((self.saida / "assets" / "ui.js").is_file())
        self.assertNotIn("lei/8036-1990/index.html", (self.saida / ".gerado").read_text(encoding="utf-8"))

    def test_gate_nao_grava(self):
        ap = json.loads(json.dumps(APELIDOS))
        ap["apelidos"].append({"alvo": "lei-99999-2030", "sigla": "X", "nome": "X", "termos": ["x"], "nota": ""})
        (self.fontes / "apelidos.json").write_text(_j(ap), encoding="utf-8", newline="\n")
        antes = _arvore(self.saida)
        self.assertEqual(self.gerar(), 1)
        self.assertEqual(_arvore(self.saida), antes)

    def test_gate_campo_proibido(self):
        normas = json.loads(json.dumps(NORMAS))
        normas[0]["ordem"] = 1
        self.escrever_base(normas)
        self.assertEqual(self.gerar(), 1)
        self.assertFalse((self.saida / ".gerado").exists())

    def test_so_dados(self):
        self.assertEqual(self.gerar(None, "--so-dados"), 0)
        self.assertTrue((self.saida / "dados" / "manifesto.json").is_file())
        self.assertFalse((self.saida / "index.html").exists())
        self.assertEqual(self.gerar(None, "--so-dados", "--verificar"), 0)

    def test_rotulo_disp(self):
        self.assertEqual(G.rotulo_disp("791-A|§4"), "art. 791-A, § 4º")
        self.assertEqual(G.rotulo_disp("8|pu"), "art. 8º, parágrafo único")
        self.assertEqual(G.rotulo_disp("7|XXIX"), "art. 7º, XXIX")
        self.assertEqual(G.rotulo_disp("76", "adct"), "art. 76 do ADCT")


def G_ordem(k):
    from pd.ordem import ordem_chave
    return ordem_chave(k)


@unittest.skipUnless((BASE_MIN / "normas.jsonl").is_file(), "fixture base_min ainda não existe")
class TesteBaseMin(unittest.TestCase):
    """Site gerado a partir da base_min, com as fontes filtradas para as chaves dela."""

    def test_gera_da_base_min(self):
        from pd.jsonio import ler_jsonl
        chaves = {n["k"] for n in ler_jsonl(BASE_MIN / "normas.jsonl")}
        SAIDA_TESTES.mkdir(parents=True, exist_ok=True)
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="site-min-", dir=SAIDA_TESTES))
        try:
            fontes = tmp / "fontes"
            fontes.mkdir()
            filtrar_fontes(RAIZ / "fontes", fontes, chaves)
            saida = tmp / "docs"
            saida.mkdir()
            argv = ["--base", str(BASE_MIN), "--fontes", str(fontes), "--saida", str(saida), "--config", str(CONFIG)]
            self.assertEqual(_rodar(argv), 0)
            self.assertEqual(_rodar(argv + ["--verificar"]), 0)
            man = json.loads((saida / "dados" / "manifesto.json").read_text(encoding="utf-8"))
            self.assertEqual(man["normas"], len(chaves))
            paginas = list(saida.glob("*/*/index.html"))
            self.assertEqual(len(paginas), len(chaves))
            for p in paginas:
                t = p.read_text(encoding="utf-8")
                self.assertIn(RODAPE, t)
                self.assertNotRegex(re.sub(r'<p class="ementa">.*?</p>|<meta name="description"[^>]*>|'
                                           r'<meta property="og:description"[^>]*>', "", t), r"(?i)revogad")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def filtrar_fontes(origem: pathlib.Path, destino: pathlib.Path, chaves: set) -> None:
    """Copia apelidos/areas/avisos mantendo só os alvos presentes em ``chaves`` (a ordem é preservada)."""
    ap = json.loads((origem / "apelidos.json").read_text(encoding="utf-8"))
    ap["apelidos"] = [a for a in ap["apelidos"] if a["alvo"] in chaves]
    for nome in ("listas", "assuntos"):
        novos = []
        for it in ap[nome]:
            alvos = [k for k in it["alvos"] if k in chaves]
            if alvos:
                novos.append(dict(it, alvos=alvos))
        ap[nome] = sorted(novos, key=lambda it: G_ordem(it["alvos"][0]))
    ar = json.loads((origem / "areas.json").read_text(encoding="utf-8"))
    areas = []
    for a in ar["areas"]:
        itens = [it for it in a["itens"] if it["k"] in chaves]
        if itens:
            areas.append(dict(a, itens=itens))
    ar["areas"] = areas
    av = json.loads((origem / "avisos.json").read_text(encoding="utf-8"))
    av["avisos"] = [a for a in av["avisos"] if a["alvo"]["k"] in chaves]
    for nome, d in (("apelidos", ap), ("areas", ar), ("avisos", av)):
        (destino / f"{nome}.json").write_text(_j(d), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    unittest.main()
