import sys
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import unittest  # noqa: E402

from pd import cache_html  # noqa: E402


class TestRiscadoSeguinte(unittest.TestCase):
    def r(self, html, nome):
        return cache_html.ancoras_da_pagina(html).get(nome, "ausente")

    def test_strike_fechado_em_volta_da_ancora(self):
        self.assertIs(self.r('<strike><a name="a1"></a></strike>Art. 1 x', "a1"), False)

    def test_texto_seguinte_riscado(self):
        self.assertIs(self.r('<a name="a2"></a><strike>Art. 2 x</strike>', "a2"), True)

    def test_estilo_line_through(self):
        self.assertIs(self.r('<span style="text-decoration: line-through"><a name="a3"></a>Art. 3</span>', "a3"), True)

    def test_strike_fechado_antes(self):
        self.assertIs(self.r('<p><strike>velho</strike></p><p><a name="a4"></a>Art. 4 x', "a4"), False)

    def test_strike_sem_fechamento(self):
        self.assertIs(self.r('<strike><p>x<a name="a5"></a>Art. 5', "a5"), True)

    def test_s_e_del(self):
        self.assertIs(self.r('<a name="b1"></a><s>x</s>', "b1"), True)
        self.assertIs(self.r('<a name="b2"></a><del> x</del>', "b2"), True)

    def test_varias_pendentes(self):
        m = cache_html.ancoras_da_pagina('<a name="c1"></a><a name="c2"></a>  <b>Art. 9</b>')
        self.assertIs(m["c1"], False)
        self.assertIs(m["c2"], False)

    def test_sem_texto_depois(self):
        self.assertIsNone(self.r('<p>x</p><a name="fim"></a>', "fim"))

    def test_ausente(self):
        self.assertEqual(self.r('<a name="x"></a>t', "y"), "ausente")

    def test_primeira_ocorrencia(self):
        self.assertIs(self.r('<a name="d"></a>vivo <a name="d"></a><strike>morto</strike>', "d"), False)

    def test_id_de_outro_elemento_e_fallback(self):
        self.assertIs(self.r('<p id="e1"><strike>x</strike></p>', "e1"), True)
        self.assertIs(self.r('<p id="e2"><strike>x</strike></p><a name="e2"></a>y', "e2"), False)

    def test_a_com_href_empilha(self):
        self.assertIs(self.r('<a href="#" style="text-decoration:line-through"><b><a name="f"/>x</b></a>', "f"), True)

    def test_entidades_e_paragrafo(self):
        self.assertIs(self.r('<a name="art8&#167;1"></a>&nbsp;<strike>x</strike>', "art8§1"), True)


class TestDecodificar(unittest.TestCase):
    def test_cp1252_padrao(self):
        self.assertEqual(cache_html.decodificar("Ação § “x”".encode("cp1252")), "Ação § “x”")

    def test_iso_8859_1_vira_cp1252(self):
        raw = b'<meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1">\x96'
        self.assertTrue(cache_html.decodificar(raw).endswith("–"))

    def test_utf8_declarado(self):
        raw = b'<meta charset="UTF-8">' + "ç§".encode("utf-8")
        self.assertTrue(cache_html.decodificar(raw).endswith("ç§"))

    def test_utf8_depois_de_4096_ignorado(self):
        raw = b" " * 5000 + b'<meta charset="utf-8">' + "ç".encode("utf-8")
        self.assertTrue(cache_html.decodificar(raw).endswith("Ã§"))


class TestCaminho(unittest.TestCase):
    def test_minusculas(self):
        p = cache_html.caminho_no_cache(pathlib.Path("raiz"), "Decreto-Lei/Del5452.htm")
        self.assertEqual(p.as_posix(), "raiz/www.planalto.gov.br/ccivil_03/decreto-lei/del5452.htm")


if __name__ == "__main__":
    unittest.main()
