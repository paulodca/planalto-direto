import sys
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import copy  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402

from pd import esquemas, jsonio  # noqa: E402

FIX = RAIZ / "testes" / "fixtures" / "base_min"

NORMA = {"ano": 1990, "caminho": "leis/l8036consol.htm", "caminho_compilado": "leis/l8036compilada.htm",
         "caminho_indice": "leis/L8036consol.htm", "data": "1990-05-11", "desde": "2026-11-21",
         "ementa": "Dispõe sobre o Fundo de Garantia do Tempo de Serviço, e dá outras providências.",
         "indice": "leis/QUADRO/1990.htm", "k": "lei-8036-1990", "letra": "", "numero": 8036, "reed": "",
         "rotulo": "8.036, de 11.5.90", "tipo": "lei", "tsig": "lei"}

ANC = {"adct": {"76": {"h": "adctart76.2"}}, "c": "constituicao/constituicaocompilado.htm",
       "corpo": {"7|XXIX": {"h": "art7xxix"}, "477|§4": {"c": "a.b", "h": "art477§4.."}},
       "h": "constituicao/constituicao.htm", "k": "cf-1988"}


class TestFixture(unittest.TestCase):
    def test_base_min(self):
        normas = jsonio.ler_jsonl(FIX / "normas.jsonl")
        self.assertGreaterEqual(len(normas), 40)
        self.assertEqual(esquemas.validar_normas(normas), [])
        por_k = {n["k"]: n for n in normas}
        arqs = sorted((FIX / "ancoras").glob("*.json"))
        self.assertTrue(arqs)
        for p in arqs:
            a = jsonio.ler_json(p)
            self.assertEqual(p.stem, a["k"])
            self.assertEqual(esquemas.validar_ancoras(a, por_k[a["k"]]), [])
        self.assertEqual(esquemas.validar_desempate(jsonio.ler_json(FIX / "desempate.json"), set(por_k)), [])
        self.assertEqual(esquemas.validar_indices(jsonio.ler_json(FIX / "indices.json")), [])
        for nome in ("normas.jsonl", "desempate.json", "indices.json"):
            b = (FIX / nome).read_bytes()
            self.assertNotIn(b"\r", b)
            self.assertFalse(b.startswith(b"\xef\xbb\xbf"))

    def test_casos_fixos_na_fixture(self):
        clt = jsonio.ler_json(FIX / "ancoras" / "dl-5452-1943.json")
        self.assertEqual(clt["corpo"]["477"], {"c": "art477..", "h": "art477.."})
        self.assertEqual(clt["corpo"]["11-A|§1"]["c"], "art11a§1")
        self.assertNotIn("8|pu", clt["corpo"])
        cf = jsonio.ler_json(FIX / "ancoras" / "cf-1988.json")
        self.assertEqual(cf["adct"]["76"], {"h": "adctart76.2"})
        normas = {n["k"]: n for n in jsonio.ler_jsonl(FIX / "normas.jsonl")}
        self.assertTrue(normas["mp-1456-1996"]["ementa"].endswith("e dá outras providências."))
        for k in ("mp-689-2015", "mp-692-2015", "mp-798-2017"):
            self.assertEqual(normas[k]["ementa"], "")
        self.assertEqual(normas["lei-8666-1993"]["caminho_compilado"], "")


class TestNorma(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(esquemas.validar_norma(NORMA), [])

    def test_erros(self):
        casos = [("k", "lei-8036-1991"), ("tsig", "dl"), ("caminho", "/leis/x.htm"), ("caminho", "C" + ":/x.htm"),
                 ("data", "1990-13-01"), ("ementa", "x Mensagem de veto"), ("ementa", "x  y"),
                 ("letra", "A"), ("reed", "35"), ("numero", "8036")]
        for campo, valor in casos:
            d = dict(NORMA, **{campo: valor})
            self.assertTrue(esquemas.validar_norma(d), (campo, valor))
        d = dict(NORMA)
        del d["desde"]
        self.assertTrue(esquemas.validar_norma(d))
        self.assertTrue(esquemas.validar_norma(dict(NORMA, extra=1)))

    def test_lista(self):
        n2 = dict(NORMA, k="lei-605-1949", numero=605, ano=1949, data="", caminho_indice="leis/L0605.htm")
        self.assertEqual(esquemas.validar_normas([n2, NORMA]), [])
        self.assertTrue(esquemas.validar_normas([NORMA, n2]))
        self.assertTrue(esquemas.validar_normas([NORMA, NORMA]))


class TestAncoras(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(esquemas.validar_ancoras(ANC), [])

    def test_erros(self):
        for mut in (lambda a: a["corpo"].update({"477|": {"h": "x"}}),
                    lambda a: a["corpo"].update({"1": {"h": "a b"}}),
                    lambda a: a["corpo"].update({"1": {}}),
                    lambda a: a["corpo"].update({"1": {"x": "a"}}),
                    lambda a: a.update({"k": "lei-1-2000"}),
                    lambda a: a.update({"c": ""})):
            a = copy.deepcopy(ANC)
            mut(a)
            self.assertTrue(esquemas.validar_ancoras(a))

    def test_contra_norma(self):
        n = {"k": "cf-1988", "caminho": "constituicao/constituicao.htm", "caminho_compilado": ""}
        self.assertTrue(esquemas.validar_ancoras(ANC, n))


class TestProibidos(unittest.TestCase):
    def test_campos(self):
        campo = "ini" + "cio"
        self.assertEqual(esquemas.campos_proibidos({"a": [{campo: "x"}]}), ["$.a[0]." + campo])
        self.assertEqual(esquemas.campos_proibidos(ANC), [])


class TestFontes(unittest.TestCase):
    AP = {"versao": 1,
          "apelidos": [{"alvo": "lei-8036-1990", "sigla": "FGTS", "nome": "Lei do FGTS", "termos": ["fgts"], "nota": ""},
                       {"alvo": "dl-5452-1943", "sigla": "CLT", "nome": "CLT", "termos": ["clt"], "nota": ""}],
          "listas": [], "assuntos": [{"alvos": ["lei-12506-2011"], "termos": ["aviso prévio"]}],
          "fora_escopo": [{"padrao": "^nr$", "mensagem": "NR."}]}

    def test_apelidos(self):
        self.assertEqual(esquemas.validar_apelidos(self.AP), [])
        self.assertTrue(esquemas.validar_apelidos(self.AP, {"dl-5452-1943"}))
        inv = copy.deepcopy(self.AP)
        inv["apelidos"].reverse()
        self.assertTrue(esquemas.validar_apelidos(inv))
        rv = copy.deepcopy(self.AP)
        rv["apelidos"][0]["nota"] = "Foi Revogada."
        self.assertTrue(esquemas.validar_apelidos(rv))
        pub = dict(self.AP, desempate={"lei:9991": "lei-9991-1950"})
        self.assertEqual(esquemas.validar_apelidos_publicos(pub), [])
        self.assertTrue(esquemas.validar_apelidos_publicos(dict(self.AP, desempate={"lei:9991": "dl-1-1937"})))

    def test_avisos(self):
        av = {"id": "x-1", "alvo": {"k": "dl-5452-1943", "parte": "corpo", "disp": "790-B"}, "estado": "atencao",
              "texto": "Texto.", "fonte": "Fonte.", "prova": {"arquivo": "decreto-lei/del5452.htm", "ancora": "a",
                                                               "contem": "ADI"},
              "conferido_em": "", "ir_para": ""}
        self.assertEqual(esquemas.validar_avisos({"versao": 1, "avisos": [av]}), [])
        for campo, valor in (("estado", "revogada"), ("texto", "revogado"), ("ir_para", "8|PU"),
                             ("conferido_em", "ontem")):
            self.assertTrue(esquemas.validar_avisos({"versao": 1, "avisos": [dict(av, **{campo: valor})]}), campo)
        pub = {k: v for k, v in av.items() if k not in ("prova", "conferido_em")}
        self.assertEqual(esquemas.validar_avisos_publicos([pub]), [])
        self.assertTrue(esquemas.validar_avisos_publicos([av]))

    def test_caminhos_repo(self):
        normas = {n["k"] for n in jsonio.ler_jsonl(FIX / "normas.jsonl")}
        d = jsonio.ler_json(RAIZ / "fontes" / "caminhos.json")
        self.assertEqual(esquemas.validar_caminhos(d, normas), [])
        self.assertEqual([s["k"] for s in d["substituicoes"]], ["lei-8666-1993"])

    def test_areas(self):
        a = {"versao": 1, "areas": [{"id": "trabalho", "nome": "Trabalho",
                                     "itens": [{"k": "dl-5452-1943", "rotulo": "CLT", "dica": ""}]}]}
        self.assertEqual(esquemas.validar_areas(a), [])
        self.assertTrue(esquemas.validar_areas(a, {"lei-1-2000"}))


class TestDados(unittest.TestCase):
    def test_manifesto(self):
        m = {"base_sha": "0123456789ab", "gerado": "2026-11-21", "normas": 2,
             "shards": {"n-cf-00": {"qtd": 1, "sha": "0123456789ab"}, "n-lei-08": {"qtd": 1, "sha": "abcdef012345"}},
             "versao": 1}
        self.assertEqual(esquemas.validar_manifesto(m), [])
        self.assertTrue(esquemas.validar_manifesto(dict(m, normas=3)))

    def test_shard(self):
        r = {"a": 1990, "c": "leis/l8036compilada.htm", "d": "1990-05-11", "e": "x", "k": "lei-8036-1990",
             "l": "", "n": 8036, "u": "leis/l8036consol.htm"}
        self.assertEqual(esquemas.validar_shard([r], "n-lei-08"), [])
        self.assertTrue(esquemas.validar_shard([r], "n-lei-07"))
        self.assertTrue(esquemas.validar_shard([dict(r, r="")]))
        self.assertTrue(esquemas.validar_shard([r, r]))

    def test_indice(self):
        self.assertEqual(esquemas.validar_ancoras_indice({"normas": ["lei-605-1949", "cf-1988"], "versao": 1}), [])
        self.assertTrue(esquemas.validar_ancoras_indice({"normas": ["cf-1988", "lei-605-1949"], "versao": 1}))

    def test_exigir(self):
        esquemas.exigir([], "x")
        with self.assertRaises(esquemas.ErroEsquema):
            esquemas.exigir(["erro"], "x")


class TestJsonio(unittest.TestCase):
    def test_deterministico(self):
        obj = {"b": [1, {"z": "ç", "a": "§"}], "a": 1}
        self.assertEqual(jsonio.dumps(obj), '{\n "a": 1,\n "b": [\n  1,\n  {\n   "a": "§",\n   "z": "ç"\n  }\n ]\n}\n')
        self.assertEqual(jsonio.dumps_compacto(obj), '{"a":1,"b":[1,{"a":"§","z":"ç"}]}\n')
        self.assertEqual(jsonio.texto_jsonl([{"b": 1, "a": 2}, {}]), '{"a":2,"b":1}\n{}\n')

    def test_escrita_atomica(self):
        d = tempfile.mkdtemp()
        try:
            p = pathlib.Path(d) / "sub" / "x.json"
            jsonio.escrever_json(p, {"a": "ç"})
            self.assertEqual(p.read_bytes(), '{\n "a": "ç"\n}\n'.encode("utf-8"))
            jsonio.escrever_texto(p, "a\r\nb")
            self.assertEqual(p.read_bytes(), b"a\nb")
            self.assertEqual(sorted(os.listdir(p.parent)), ["x.json"])
            jsonio.escrever_jsonl(p, [{"a": 1}])
            self.assertEqual(jsonio.ler_jsonl(p), [{"a": 1}])
        finally:
            import shutil
            shutil.rmtree(d)


class TestDesempate(unittest.TestCase):
    """Chaves fictícias: só a regra do §7.6 importa aqui."""

    def test_regra_de_um_membro(self):
        from build import montar_base as mb
        normas = [{"k": k, "tsig": k.split("-")[0], "numero": int(k.split("-")[1]), "letra": ""}
                  for k in ("lei-9991-1950", "lei-9991-1960", "ec-9992-2000", "lc-9992-2001")]
        d, _ = mb.calcular_desempate(normas, {"lei-9991-1950"}, set())
        self.assertEqual(d, {"num:9991": "lei-9991-1950", "lei:9991": "lei-9991-1950"})
        d, multi = mb.calcular_desempate(normas, {"ec-9992-2000", "lc-9992-2001"}, set())
        self.assertEqual(d, {})
        self.assertEqual(multi, 1)
        d, _ = mb.calcular_desempate(normas, {"lei-9991-1950"}, {"lei-9991-1960"})
        self.assertEqual(d, {})
        self.assertEqual(list(mb.calcular_desempate(normas, {"lei-9991-1960"}, set())[0]), [])


if __name__ == "__main__":
    unittest.main()
