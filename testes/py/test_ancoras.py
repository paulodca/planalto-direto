import sys
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import unittest  # noqa: E402

from pd import ancoras as anc  # noqa: E402

# Os textos de início abaixo são sintéticos e curtos (I1).


class TestArtigo(unittest.TestCase):
    def test_numero_diferente(self):
        self.assertFalse(anc.artigo_confere("51", "Art. 923 x"))

    def test_citacao_entre_aspas(self):
        self.assertFalse(anc.artigo_confere("477", "“Art. 477 x"))
        self.assertFalse(anc.artigo_confere("477", '"Art. 477 x'))

    def test_espaco_antes_da_letra(self):
        self.assertTrue(anc.artigo_confere("5", "Art. 5º - A x"))

    def test_letra(self):
        self.assertTrue(anc.artigo_confere("790-B", "Art. 790-B. x"))
        self.assertFalse(anc.artigo_confere("790", "Art. 790-B. x"))
        self.assertTrue(anc.artigo_confere("18-A", "Art. 18 - A (VETADO)"))
        self.assertTrue(anc.artigo_confere("5-A", "Art. 5 º -A x"))
        self.assertFalse(anc.artigo_confere("790-C", "Art. 790-B. x"))

    def test_milhar_e_unico(self):
        self.assertTrue(anc.artigo_confere("1022", "Art. 1.022. x"))
        self.assertTrue(anc.artigo_confere("1", "Artigo único. x"))
        self.assertFalse(anc.artigo_confere("2", "Artigo único. x"))

    def test_zero_a_esquerda(self):
        # o extrator grava "01" para a âncora art01, que marca o "Art. 1º" (I1: início sintético)
        self.assertEqual(anc.verificar("01", "", "Art. 1º x"), ("1", ""))
        self.assertEqual(anc.verificar("1", "", "Art. 1º x"), ("1", ""))
        self.assertTrue(anc.artigo_confere("1", "Art. 01 x"))
        self.assertTrue(anc.artigo_confere("01", "Artigo único. x"))
        # só o zero à esquerda é normalizado: as outras regras continuam valendo
        self.assertFalse(anc.artigo_confere("01", "Art. 10 x"))
        self.assertFalse(anc.artigo_confere("010", "Art. 1º x"))
        self.assertFalse(anc.artigo_confere("01", "“Art. 1º x"))
        self.assertFalse(anc.artigo_confere("01", "| Cabeçalho x"))
        self.assertFalse(anc.artigo_confere("01", "Art. 1º-A x"))
        self.assertEqual(anc.verificar("01", "", "Art. 2º x"), (None, "inicio reprovado (artigo)"))
        self.assertEqual(anc.reparar_letra("01", "a", "Art. 1º-A x", set()), ("01-A", "", "reparo2"))


class TestComponente(unittest.TestCase):
    def test_par(self):
        self.assertTrue(anc.ultimo_componente_confere(("par", "1"), "§ 1º x"))
        self.assertFalse(anc.ultimo_componente_confere(("par", "1"), "§ 1º-A. x"))
        self.assertTrue(anc.ultimo_componente_confere(("par", "1-A"), "§ 1º-A. x"))
        self.assertFalse(anc.ultimo_componente_confere(("par", "2"), "§ 1º x"))

    def test_outros(self):
        self.assertTrue(anc.ultimo_componente_confere(("pu", ""), "Parágrafo único. x"))
        self.assertTrue(anc.ultimo_componente_confere(("inc", "XXIX"), "XXIX - x"))
        self.assertTrue(anc.ultimo_componente_confere(("ali", "a"), "a) x"))
        self.assertTrue(anc.ultimo_componente_confere(("item", "1"), "1. x"))
        self.assertFalse(anc.ultimo_componente_confere(("inc", "I"), "II - x"))


class TestParseDisp(unittest.TestCase):
    def test_exemplos(self):
        self.assertEqual(anc.parse_disp("ii", "II - x"), [("inc", "II")])
        self.assertEqual(anc.parse_disp("ia", "a) 5% x"), [("inc", "I"), ("ali", "a")])
        self.assertEqual(anc.parse_disp("§4i", "I - x"), [("par", "4"), ("inc", "I")])
        self.assertEqual(anc.parse_disp("pi", "I - x"), [("pu", ""), ("inc", "I")])
        self.assertEqual(anc.parse_disp("p", "Parágrafo único. x"), [("pu", "")])
        self.assertEqual(anc.parse_disp("xxix", "XXIX - x"), [("inc", "XXIX")])
        self.assertEqual(anc.parse_disp("§1a", "§ 1º-A. x"), [("par", "1-A")])
        self.assertEqual(anc.parse_disp("§1", "§ 1º x"), [("par", "1")])

    def test_reprovado(self):
        self.assertIsNone(anc.parse_disp("ii", "Art. 2 x"))
        self.assertIsNone(anc.parse_disp("§2", "§ 3º x"))

    def test_canonico(self):
        self.assertEqual(anc.disp_canonico("477", [("par", "4"), ("inc", "I")]), "477|§4|I")
        self.assertEqual(anc.disp_canonico("8", [("pu", "")]), "8|pu")
        self.assertEqual(anc.disp_canonico("790-b", []), "790-B")
        self.assertEqual(anc.verificar("1022", "p", "Parágrafo único. x"), ("1022|pu", ""))

    def test_canonico_valido(self):
        for s in ("477", "790-B", "477|§4|I", "8|pu", "5|LV", "1022|pu", "8|§1-A", "5|I|a|1", "7|XXIX"):
            self.assertTrue(anc.disp_canonico_valido(s), s)
        for s in ("", "477|", "a", "477|§", "8|PU", "5|lv", "477-b", "5|IIII", "8|pu|§1"):
            self.assertFalse(anc.disp_canonico_valido(s), s)


class TestReparo(unittest.TestCase):
    def test_letra_solta(self):
        self.assertEqual(anc.reparar_letra("11", "a§1", "§ 1º x", {"11-A"}), ("11-A", "§1", "reparo1"))
        self.assertEqual(anc.reparar_letra("10", "ai", "I - x", {"10-A"}), ("10-A", "i", "reparo1"))

    def test_sem_artigo_com_letra(self):
        self.assertEqual(anc.reparar_letra("11", "a§1", "§ 1º x", set()), ("11", "a§1", ""))

    def test_inicio_de_artigo_nao_repara(self):
        self.assertEqual(anc.reparar_letra("11", "a§1", "Art. 11 x", {"11-A"}), ("11", "a§1", ""))

    def test_segundo_reparo(self):
        self.assertEqual(anc.reparar_letra("1358", "p", "Art. 1.358-P. x", set()), ("1358-P", "", "reparo2"))
        self.assertEqual(anc.reparar_letra("1358", "p", "Parágrafo único. x", set()), ("1358", "p", ""))

    def test_reparo_e_verificacao_clt(self):
        art, disp, _m = anc.reparar_letra("11", "a§1", "§ 1º x", {"11-A"})
        self.assertEqual(anc.verificar(art, disp, "§ 1º x"), ("11-A|§1", ""))


class TestAlfabeto(unittest.TestCase):
    def test_alfabeto(self):
        self.assertTrue(anc.ancora_valida("art8§1"))
        self.assertTrue(anc.ancora_valida("cf-88-parte-1-titulo-2-capitulo-2-artigo-7"))
        self.assertTrue(anc.ancora_valida("adctart76.2"))
        self.assertFalse(anc.ancora_valida(""))
        self.assertFalse(anc.ancora_valida("art1:~:" + "text=x"))
        self.assertFalse(anc.ancora_valida("art 1"))
        self.assertFalse(anc.ancora_valida("artç"))


if __name__ == "__main__":
    unittest.main()
